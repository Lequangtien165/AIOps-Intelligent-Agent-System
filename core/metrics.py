# Prometheus Metrics cho AI Ops Agent.
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
import time

# Metrics định nghĩa
ALERTS_PROCESSED_TOTAL = Counter(
    'aiops_alerts_processed_total', 
    'Tổng số alerts đã được xử lý bởi AI Agent',
    ['status'] # 'success' hoặc 'failure'
)

AI_WORKFLOW_LATENCY_SECONDS = Histogram(
    'aiops_ai_workflow_duration_seconds', 
    'Thời gian hoàn tất workflow AI (RAG + LLM)',
    buckets=(1, 5, 10, 30, 60, 120, 300)
)

# Để đo số task đang xử lý đồng thời
ACTIVE_TASKS = Gauge(
    'aiops_active_tasks',
    'Số lượng alert đang được phân tích đồng thời'
)

def get_metrics_response():
    """Trả về dữ liệu metrics theo chuẩn Prometheus."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
