import os
from celery import Celery

# Set default settings
os.environ.setdefault('CELERY_BROKER_URL', 'redis://redis:6379/0')
os.environ.setdefault('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

app = Celery('workers')

# Configure Celery
app.conf.update(
    broker_url=os.getenv('CELERY_BROKER_URL'),
    result_backend=os.getenv('CELERY_RESULT_BACKEND'),
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
    # Optimize for different types of tasks
    task_routes={
        'youtube.*': {'queue': 'youtube'},
        'notifier.*': {'queue': 'notifications'},
        'media.*': {'queue': 'media'},
    }
)

# Auto-discover tasks in packages
# We will treat 'youtube', 'notifier', etc. as packages inside the current directory
app.autodiscover_tasks([
    'youtube',
    'media',
    'ai',
    'data',
    'system',
    # 'notifier', # Uncomment when migrated
], force=True)

if __name__ == '__main__':
    app.start()
