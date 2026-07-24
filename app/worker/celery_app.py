import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    # ADD THIS: Tell celery where the tasks are
    include=['app.worker.tasks'] 
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Optional: ensure tasks are acknowledged only after they succeed
    task_acks_late=True, 
)

celery_app.conf.beat_schedule = {
    "daily-ai-content-generation": {
        "task": "generate_all_users_feed",
        "schedule": crontab(hour=2, minute=0), # Runs every day at 2:00 AM
    },
    "check-daily-reminders": {
        "task": "process_daily_reminders",
        "schedule": crontab(minute="*"), # Runs every minute of every day
    },
}