"""
Task queue wrappers for API to send tasks to workers.
API never imports worker code directly - just sends task names via Celery.
"""
from celery import Celery
from packages.common.config import settings

# Get Celery instance
celery_app = Celery('curlys_books')
celery_app.conf.broker_url = settings.celery_broker_url
celery_app.conf.result_backend = settings.celery_result_backend


def queue_receipt_ocr(receipt_id: str, entity: str) -> str:
    """Queue a receipt for OCR processing."""
    task = celery_app.send_task(
        'process_receipt_ocr',
        args=[receipt_id, entity]
    )
    return task.id