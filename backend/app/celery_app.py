from celery import Celery

from app.settings import settings

celery_app = Celery(
    "minsheng_governance",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    timezone="Asia/Shanghai",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

