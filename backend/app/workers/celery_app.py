from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "mcp_rag_notebook",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,
    task_always_eager=(
        settings.celery_task_always_eager
    ),
    broker_connection_retry_on_startup=True,
)