# tasks.py
# FIX #5: Sắp xếp lại imports — stdlib trước, third-party sau, local cuối cùng
import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import redis
from dotenv import load_dotenv
from google import genai
from google.genai import types

from core.celery_app import celery_app
from core.metrics import ACTIVE_TASKS, AI_WORKFLOW_LATENCY_SECONDS, ALERTS_PROCESSED_TOTAL
from core.rag_engine import get_rag_instance
from tools.diag_tools import AGENT_TOOLS
from tools.prometheus_check import get_prometheus_checker
from utils.telegram_bot import send_telegram_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

def valid_env_value(value: str | None) -> str | None:
    if not value:
        return None

    value = value.strip()
    placeholders = ("your_", "change_me", "_here")
    if not value or any(marker in value for marker in placeholders):
        return None

    return value

GEMINI_API_KEY = valid_env_value(os.getenv("GEMINI_API_KEY"))
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Redis Configuration (để lưu incident context)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB   = int(os.getenv("REDIS_DB", "0"))

# FIX #8: Thêm socket_timeout và xử lý lỗi khởi tạo Redis
try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    redis_client.ping()
    logger.info("✅ Redis connected successfully.")
except redis.RedisError as e:
    logger.error(f"❌ Redis connection failed: {e}")
    redis_client = None  # type: ignore


def save_incident_to_redis(incident_id: str, context: dict, ttl: int = 86400):
    if redis_client is None:
        logger.error("Redis client unavailable, skipping incident save.")
        return
    try:
        redis_client.setex(f"incident:{incident_id}", ttl, json.dumps(context))
    except redis.RedisError as e:
        logger.error(f"Error writing to Redis: {e}")


async def run_agent_workflow(incident_details: str):
    if not GEMINI_API_KEY:
        return "❌ Error: GEMINI_API_KEY not configured", None

    client = genai.Client(api_key=GEMINI_API_KEY)
    rag = get_rag_instance()

    runbook_context = "⚠️ RAG Engine không khả dụng."
    if rag:
        runbook_context = rag.query_runbook(incident_details)

    system_instruction = f"""
        Bạn là AI Ops Agent chuyên nghiệp, chuyên xử lý sự cố hạ tầng.
        QUY TRÌNH CHUẨN VÀ LỊCH SỬ INCIDENT từ kho tri thức:
        ---
        {runbook_context}
        ---
        BẮT BUỘC: Dòng cuối cùng của response PHẢI là:
        PROPOSAL_JSON: {{"action": "tên_hành_động", "host": "tên_máy_chủ"}}
    """

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Phân tích sự cố: {incident_details}",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=AGENT_TOOLS,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=5
                )
            )
        )
        full_text = response.text or ""
        proposal  = None
        match = re.search(r"PROPOSAL_JSON:\s*(\{.*\})", full_text)
        if match:
            try:
                proposal = json.loads(match.group(1))
            except json.JSONDecodeError:
                logger.warning("Failed to parse PROPOSAL_JSON from AI response.")
        return full_text if full_text else "AI không phản hồi.", proposal
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return f"❌ Lỗi AI: {e}", None


async def process_single_alert(alert: dict) -> None:
    """Xử lý logic cho một alert đơn lẻ (async)."""
    ACTIVE_TASKS.inc()
    start_time = time.time()
    try:
        alert_name  = alert["labels"].get("alertname", "Unknown")
        instance    = alert["labels"].get("instance", "Unknown")
        summary     = alert["annotations"].get("summary", "")
        description = alert["annotations"].get("description", "")

        if alert.get("status") == "resolved":
            send_telegram_message(f"✅ *ĐÃ KHÔI PHỤC:* {alert_name} trên `{instance}`")
            ALERTS_PROCESSED_TOTAL.labels(status='resolved').inc()
            return

        incident_details = f"Alert: {alert_name} | Host: {instance} | Summary: {summary}"

        ai_analysis, proposal = await run_agent_workflow(incident_details)

        duration = time.time() - start_time
        AI_WORKFLOW_LATENCY_SECONDS.observe(duration)
        ALERTS_PROCESSED_TOTAL.labels(status='success').inc()

        incident_id = uuid.uuid4().hex[:8]
        incident_context = {
            "alert_name": alert_name,
            "instance": instance,
            "incident_details": incident_details,
            "ai_analysis": ai_analysis,
            "proposal": proposal,
            "timestamp": datetime.now(VN_TZ).isoformat()
        }
        save_incident_to_redis(incident_id, incident_context)

        # Merge Phase 7: Buttons for approval + Verification scheduled
        reply_markup = None
        if proposal:
            action_name = proposal.get("action") or "fix"
            reply_markup = {"inline_keyboard": [[
                {"text": f"✅ Thực thi: {action_name[:20]}", "callback_data": f"ok|{incident_id}"},
                {"text": "❌ Bỏ qua", "callback_data": f"ignore|{incident_id}"}
            ]]}

        report = (
            f"*🚨 SỰ CỐ:* {alert_name}\n"
            f"📊 *Server:* `{instance}`\n"
            f"🆔 *ID:* `{incident_id}`\n\n"
            f"🔍 *Phân tích :*\n{ai_analysis}\n\n"
            f"⏱️ Hệ thống sẽ tự động kiểm tra lại sau 5 phút."
        )
        send_telegram_message(report, reply_markup=reply_markup)
        
        # Schedule verification task sau 5 phút
        verification_countdown = 300 
        verify_resolution_task.apply_async(
            args=[incident_id, alert_name, instance],
            countdown=verification_countdown
        )
        logger.info(f"📋 Scheduled verification for incident {incident_id} in {verification_countdown}s")

    except Exception as e:
        ALERTS_PROCESSED_TOTAL.labels(status='failure').inc()
        logger.error(f"Error processing alert: {e}")
        raise  # re-raise để Celery task biết alert này thất bại
    finally:
        ACTIVE_TASKS.dec()

# ─────────────────────────────────────────────────────────────────────
# Automatic Verification Logic (Merged from develop)
# ─────────────────────────────────────────────────────────────────────

async def verify_resolution(incident_id: str, alert_name: str, instance: str):
    """PHASE 9: Automatic Verification - kiểm lại sau 5-10 phút"""
    logger.info(f"🔍 Starting verification for incident {incident_id} ({alert_name} on {instance})")
    
    try:
        if redis_client is None:
            return
            
        try:
            ctx_raw = redis_client.get(f"incident:{incident_id}")
        except redis.RedisError as e:
            logger.error(f"Redis read error during verification: {e}")
            send_telegram_message(f"⚠️ Không thể xác nhận kết quả vì Redis unavailable")
            return
        
        if not ctx_raw:
            logger.warning(f"Incident context expired for {incident_id}")
            # send_telegram_message(f"⚠️ Context hết hạn cho sự cố `{incident_id}`")
            return
        
        ctx = json.loads(cast(str, ctx_raw))
        
        logger.info(f"📊 Checking current metrics for {instance}...")
        is_resolved = await check_alert_resolved(alert_name, instance)
        
        if is_resolved:
            outcome = "resolved_by_human"
            message = (
                f"✅ *SỰ CỐ ĐÃ ĐƯỢC KHÔI PHỤC*\n"
                f"Alert: {alert_name}\n"
                f"Server: {instance}\n"
                f"ID: {incident_id}\n\n"
                f"Metrics hiện tại đã trở lại bình thường."
            )
        else:
            outcome = "failed_to_resolve"
            message = (
                f"❌ *SỰ CỐ VẪN TỒN TẠI*\n"
                f"Alert: {alert_name}\n"
                f"Server: {instance}\n"
                f"ID: {incident_id}\n\n"
                f"⚠️ Các metrics vẫn còn cao.\n"
                f"💡 Gợi ý: Hãy thử giải pháp thay thế hoặc escalate."
            )
        
        send_telegram_message(message)
        
        rag = get_rag_instance()
        if rag:
            rag.save_incident(
                alert_name=ctx["alert_name"],
                description=ctx["incident_details"],
                ai_analysis=ctx["ai_analysis"],
                resolution=ctx.get("proposal", {}).get("action", "manual_fix"),
                outcome=outcome
            )
            logger.info(f"✅ Saved incident to ChromaDB with outcome: {outcome}")
        
        try:
            redis_client.delete(f"incident:{incident_id}")
        except redis.RedisError as e:
            logger.warning(f"Error deleting incident from Redis: {e}")
    
    except Exception as e:
        logger.error(f"Error during verification: {e}")
        send_telegram_message(f"⚠️ Lỗi kiểm tra kết quả: {str(e)}")


async def check_alert_resolved(alert_name: str, instance: str) -> bool:
    """Check nếu alert đã được resolve bằng cách query Prometheus."""
    try:
        logger.info(f"Checking if {alert_name} is resolved on {instance}...")
        
        checker = get_prometheus_checker()
        is_resolved = checker.is_alert_resolved(alert_name, instance)
        
        if is_resolved:
            logger.info(f"✅ Alert {alert_name} is RESOLVED")
        else:
            logger.warning(f"❌ Alert {alert_name} is STILL FAILING")
        
        metrics = checker.get_alert_metrics(instance)
        logger.info(f"📊 Current metrics: {metrics}")
        
        return is_resolved
    
    except Exception as e:
        logger.error(f"Error checking alert resolution: {e}")
        return False


@celery_app.task(name="verify_resolution_task", bind=True, max_retries=2)
def verify_resolution_task(self, incident_id: str, alert_name: str, instance: str):
    """Celery task để verify resolution (chạy sau 5-10 phút)"""
    try:
        logger.info(f"🔄 Running verification for {incident_id}")
        asyncio.run(verify_resolution(incident_id, alert_name, instance))
    except Exception as e:
        logger.error(f"Verification task failed: {e}")
        raise self.retry(exc=e, countdown=60)


# FIX #2 + #1 (Critical):
# - FIX #2: Chạy TẤT CẢ alerts trong một lần asyncio.run() duy nhất với gather()
# - FIX #1: Tách xử lý lỗi per-alert ra khỏi retry của toàn bộ task.
@celery_app.task(name="process_alerts_task", bind=True, max_retries=3)
def process_alerts_task(self, payload_dict: dict):
    """Celery task xử lý alert payload từ Prometheus."""
    alerts = payload_dict.get("alerts", [])
    if not alerts:
        logger.info("No alerts in payload, skipping.")
        return

    async def _run_all():
        results = await asyncio.gather(
            *[process_single_alert(alert) for alert in alerts],
            return_exceptions=True
        )
        failed = [
            (i, str(exc)) for i, exc in enumerate(results)
            if isinstance(exc, Exception)
        ]
        if failed:
            for idx, err in failed:
                alert_name = alerts[idx].get("labels", {}).get("alertname", "unknown")
                logger.error(f"Alert[{idx}] '{alert_name}' failed: {err}")
            if len(failed) == len(alerts):
                raise RuntimeError(f"All {len(alerts)} alerts failed. Last error: {failed[-1][1]}")

    try:
        asyncio.run(_run_all())
    except RuntimeError as e:
        raise self.retry(exc=e, countdown=10)
