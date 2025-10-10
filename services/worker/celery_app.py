"""
Celery application configuration for background tasks
"""
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
import structlog

from packages.common.config import get_settings
from packages.common.database import sessionmanager

logger = structlog.get_logger()
settings = get_settings()

# Create Celery app
app = Celery(
    "curlys_books_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Celery configuration
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Halifax",
    enable_utc=True,
    
    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=600,  # 10 minutes hard limit
    task_soft_time_limit=540,  # 9 minutes soft limit
    
    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,
    
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    
    # Task routing
    task_routes={
        "services.worker.tasks.ocr_receipt.*": {"queue": "ocr"},
        "services.worker.tasks.parse_vendor.*": {"queue": "parsing"},
        "services.worker.tasks.match_banking.*": {"queue": "matching"},
        "services.worker.tasks.sync_shopify.*": {"queue": "shopify"},
        "services.worker.tasks.process_pad.*": {"queue": "matching"},
        "services.worker.tasks.backup_to_drive.*": {"queue": "backup"},
    },
    
    # Beat schedule (periodic tasks)
    beat_schedule={
        "process-reimbursement-batch": {
            "task": "services.worker.tasks.process_reimbursements.prepare_monday_batch",
            "schedule": settings.reimbursement_batch_time,
            "options": {"queue": "matching"},
        },
        "sync-shopify-orders": {
            "task": "services.worker.tasks.sync_shopify.sync_orders",
            "schedule": 900.0,  # Every 15 minutes
            "options": {"queue": "shopify"},
        },
        "backup-to-drive": {
            "task": "services.worker.tasks.backup_to_drive.backup_database",
            "schedule": "0 3 * * *",  # 3 AM daily
            "options": {"queue": "backup"},
        },
    },
)

# Import tasks explicitly to register them
from services.worker.tasks import ocr_receipt


@worker_process_init.connect
def init_worker(**kwargs):
    """Initialize worker process"""
    logger.info("celery_worker_starting",
                concurrency=kwargs.get("concurrency", "unknown"))

    # Initialize database session manager for async tasks
    sessionmanager.init(settings.database_url)
    logger.info("celery_database_initialized")


@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    """Clean up worker process"""
    logger.info("celery_worker_shutting_down")

    # Close database connections
    import asyncio
    try:
        asyncio.get_event_loop().run_until_complete(sessionmanager.close())
        logger.info("celery_database_closed")
    except Exception as e:
        logger.error("celery_database_close_failed", error=str(e))


if __name__ == "__main__":
    app.start()
