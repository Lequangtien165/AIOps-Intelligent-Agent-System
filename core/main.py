# main.py
import os
import json
import logging
import redis
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from typing import List, Optional, cast 
from dotenv import load_dotenv

from core.tasks import process_alerts_task
from utils.telegram_bot import send_telegram_message, set_telegram_webhook
from core.rag_engine import get_rag_instance
from core.metrics import get_metrics_response

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

AI_AGENT_PORT       = int(os.getenv("AI_AGENT_PORT", "8000"))
AI_AGENT_PUBLIC_URL = valid_env_value(os.getenv("AI_AGENT_PUBLIC_URL"))
ENABLE_COMPRESSION  = os.getenv("ENABLE_COMPRESSION", "true").lower() == "true"
COMPRESSION_MIN_SIZE = int(os.getenv("COMPRESSION_MINIMUM_SIZE", "500"))
CORS_ORIGINS        = os.getenv("CORS_ORIGINS", "*").split(",")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB   = int(os.getenv("REDIS_DB", "0"))
REDIS_POOL_SIZE = int(os.getenv("REDIS_POOL_SIZE", "10"))

# FIX #9: Thêm socket_timeout + connection pooling để tránh treo khi Redis down
redis_pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    max_connections=REDIS_POOL_SIZE,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
    retry_on_timeout=True,
)
redis_client = redis.Redis(connection_pool=redis_pool)

# ─────────────────────────────────────────────
# FIX #4: Dùng lifespan thay cho @app.on_event("startup") (deprecated từ FastAPI 0.93)
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up AIOps Agent...")
    if AI_AGENT_PUBLIC_URL:
        try:
            set_telegram_webhook(AI_AGENT_PUBLIC_URL)
            logger.info("Telegram webhook configured successfully")
        except Exception as e:
            logger.error(f"Failed to set Telegram webhook: {e}")
    # Warm up RAG engine
    try:
        rag = get_rag_instance()
        logger.info("RAG engine initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize RAG engine: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down AIOps Agent...")
    try:
        redis_pool.disconnect()
    except Exception as e:
        logger.warning(f"Redis cleanup error: {e}")

app = FastAPI(
    title="AIOps Intelligent Agent (Celery Enabled)",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json"
)

# Add middleware for compression
if ENABLE_COMPRESSION:
    app.add_middleware(GZipMiddleware, minimum_size=COMPRESSION_MIN_SIZE)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Performance monitoring middleware
@app.middleware("http")
async def add_performance_headers(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Powered-By"] = "AIOps-Agent/1.0"
    response.headers["Cache-Control"] = "public, max-age=300"
    return response

# ─────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────

class Alert(BaseModel):
    status: str
    labels: dict
    annotations: dict
    startsAt: str
    endsAt: Optional[str] = None
    generatorURL: str

class AlertmanagerPayload(BaseModel):
    alerts: List[Alert]
    status: str

# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.post("/webhook")
async def prometheus_webhook(payload: AlertmanagerPayload):
    """
    PHASE 3: Tiếp nhận Alert và đẩy ngay vào Celery để xử lý bất đồng bộ.
    
    AlertManager gửi webhook POST → FastAPI nhận → enqueue to Celery
    """
    logger.info(f"Received {len(payload.alerts)} alerts from Prometheus")
    process_alerts_task.delay(payload.model_dump())
    return {
        "status": "enqueued",
        "alert_count": len(payload.alerts),
        "timestamp": time.time()
    }


@app.post("/telegram/webhook")
async def telegram_callback(request: Request):
    """Xử lý phản hồi từ Telegram (Approved/Rejected)."""
    try:
        data = await request.json()
        if "callback_query" not in data:
            return {"status": "ok"}

        cb      = data["callback_query"]
        cb_data = cb.get("data", "")
        parts   = cb_data.split("|")

        if len(parts) < 2:
            return {"status": "ok"}

        action_type, incident_id = parts[0], parts[1]

        # FIX #8: Wrap Redis read trong try-except
        try:
            ctx_raw = redis_client.get(f"incident:{incident_id}")
        except redis.RedisError as e:
            logger.error(f"Redis read error: {e}")
            send_telegram_message("⚠️ Lỗi kết nối Redis, không thể xử lý callback.")
            return {"status": "error"}

        if not ctx_raw:
            send_telegram_message(f"⚠️ Hết hạn context cho sự cố `{incident_id}`.")
            return {"status": "ok"}

        ctx = json.loads(cast(str, ctx_raw))
        rag = get_rag_instance()

        if action_type == "ok":
            action = ctx.get("proposal", {}).get("action", "fix")
            send_telegram_message(f"⚙️ *Thực thi:* `{action}` trên `{ctx['instance']}`...")
            if rag:
                rag.save_incident(
                    alert_name=ctx["alert_name"],
                    description=ctx["incident_details"],
                    ai_analysis=ctx["ai_analysis"],
                    resolution=action,
                    outcome="executed_by_human"
                )
            send_telegram_message(f"🚀 *Hoàn tất:* `{action}` thành công!")

        elif action_type == "ignore":
            send_telegram_message(f"🚫 *Bỏ qua:* `{ctx['alert_name']}`.")

        # FIX #8: Wrap Redis delete trong try-except
        try:
            redis_client.delete(f"incident:{incident_id}")
        except redis.RedisError as e:
            logger.error(f"Redis delete error: {e}")

    except Exception as e:
        logger.error(f"Callback error: {e}")

    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    """Get Prometheus metrics"""
    response = get_metrics_response()
    return response


@app.get("/health")
async def health():
    """Health check endpoint with detailed status"""
    # Kiểm tra Redis health
    try:
        redis_client.ping()
        redis_status = "connected"
    except redis.RedisError as e:
        logger.warning(f"Redis health check failed: {e}")
        redis_status = "disconnected"
    
    return {
        "status": "healthy",
        "version": "1.0.0",
        "queue": "celery-redis",
        "redis": redis_status,
        "timestamp": time.time()
    }


@app.get("/")
async def root():
    """Root endpoint with API info"""
    return {
        "name": "AIOps Intelligent Agent",
        "version": "1.0.0",
        "environment": os.getenv("ENVIRONMENT", "production"),
        "endpoints": {
            "webhook": "POST /webhook",
            "health": "GET /health",
            "metrics": "GET /metrics",
            "docs": "GET /docs"
        }
    }


if __name__ == "__main__":
    import uvicorn
    workers = int(os.getenv("WORKERS", "4"))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=AI_AGENT_PORT,
        workers=workers,
        access_log=os.getenv("ACCESS_LOG", "true").lower() == "true"
    )
