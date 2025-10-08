"""Task queue wrappers - API sends task names, never imports worker code."""
from celery import Celery
from packages.common.config import get_settings

settings = get_settings()

celery_app = Celery('curlys_books')
celery_app.conf.broker_url = settings.celery_broker_url
celery_app.conf.result_backend = settings.celery_result_backend


def queue_receipt_ocr(receipt_id: str, entity: str, file_path: str, content_hash: str, source: str) -> str:
    """Queue receipt for OCR."""
    task = celery_app.send_task(
        'services.worker.tasks.ocr_receipt.process_receipt_task',  
        args=[receipt_id, entity, file_path, content_hash, source]
    )
    return task.id
