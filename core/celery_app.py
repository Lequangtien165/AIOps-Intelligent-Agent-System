# celery_app.py
import os
from celery import Celery
from kombu import Exchange, Queue
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB   = int(os.getenv("REDIS_DB", "0"))
REDIS_POOL_SIZE = int(os.getenv("REDIS_POOL_SIZE", "10"))

CELERY_CONCURRENCY = int(os.getenv("CELERY_CONCURRENCY", "4"))
CELERY_PREFETCH_MULTIPLIER = int(os.getenv("CELERY_PREFETCH_MULTIPLIER", "2"))
CELERY_TIME_LIMIT = int(os.getenv("CELERY_TIME_LIMIT", "600"))
CELERY_SOFT_TIME_LIMIT = int(os.getenv("CELERY_SOFT_TIME_LIMIT", "540"))
CELERY_BROKER_POOL_LIMIT = int(os.getenv("CELERY_BROKER_POOL_LIMIT", "10"))
CELERY_RESULT_EXPIRES = int(os.getenv("CELERY_RESULT_EXPIRES", "3600"))

CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

celery_app = Celery(
    "aiops_tasks",
    broker=CELERY_BROKER_URL,
    backend=CELERY_BROKER_URL,
    include=["core.tasks"]
)

# Define queues for better task routing
default_exchange = Exchange('celery', type='direct')
default_queue = Queue('default', exchange=default_exchange, routing_key='default', queue_arguments={'x-max-priority': 10})

# Task-specific queues
alert_queue = Queue('alerts', exchange=default_exchange, routing_key='alerts', queue_arguments={'x-max-priority': 10})
analysis_queue = Queue('analysis', exchange=default_exchange, routing_key='analysis', queue_arguments={'x-max-priority': 5})

celery_app.conf.update(
    # Broker configuration
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    broker_pool_limit=CELERY_BROKER_POOL_LIMIT,
    broker_transport_options={
        'master_name': 'mymaster',
        'password': os.getenv('REDIS_PASSWORD'),
        'connection_class': 'redis.connection.HiredisConnection',
    },
    
    # Task serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # Timezone
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    
    # Task configuration
    task_track_started=True,
    task_time_limit=CELERY_TIME_LIMIT,
    task_soft_time_limit=CELERY_SOFT_TIME_LIMIT,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Worker configuration
    worker_prefetch_multiplier=CELERY_PREFETCH_MULTIPLIER,
    worker_max_tasks_per_child=1000,
    
    # Result backend configuration
    result_expires=CELERY_RESULT_EXPIRES,
    result_compression='gzip',
    result_backend_transport_options={
        'master_name': 'mymaster',
        'password': os.getenv('REDIS_PASSWORD'),
    },
    
    # Queue configuration
    task_queues=(default_queue, alert_queue, analysis_queue),
    task_default_queue='default',
    task_default_exchange='celery',
    task_default_routing_key='default',
    
    # Advanced options
    worker_disable_rate_limits=False,
    task_always_eager=False,
    task_eager_propagates=False,
    
    # Monitoring
    worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
    worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s] [%(task_name)s(%(task_id)s)] %(message)s',
)