# Workers - Background Job Processing

Background job processing services for asynchronous tasks in the KubeLab platform.

## Overview

The Workers application handles background jobs, scheduled tasks, and async processing that don't need to block web requests. This includes email sending, data processing, file generation, cleanup jobs, and other long-running operations.

## Architecture

```
apps/workers/
├── notifier/           # Notification service worker
├── pdf-generator/      # PDF generation worker
├── scraper/            # Web scraping worker
├── Dockerfile          # Container build configuration
└── README.md           # This file
```

## Worker Services

### 1. Notifier

Handles all notification delivery across multiple channels.

**Capabilities:**
- Email notifications (SMTP, SendGrid, etc.)
- Push notifications (web push, mobile)
- Slack/Discord webhooks
- SMS notifications (Twilio integration)

**Queue:** `notifications`

**Example Job:**
```json
{
  "type": "email",
  "to": "user@example.com",
  "subject": "Deployment Complete",
  "template": "deployment-success",
  "data": {
    "app": "api",
    "version": "v1.2.3",
    "environment": "production"
  }
}
```

### 2. PDF Generator

Generates PDF documents from HTML templates or markdown.

**Capabilities:**
- HTML to PDF conversion
- Markdown to PDF export
- Custom styling and branding
- Report generation
- Invoice/receipt creation

**Queue:** `pdf-generation`

**Example Job:**
```json
{
  "type": "report",
  "template": "monthly-metrics",
  "data": {
    "month": "2025-11",
    "metrics": {...}
  },
  "output": "s3://reports/2025-11-metrics.pdf"
}
```

### 3. Scraper

Web scraping and data collection jobs.

**Capabilities:**
- Website content extraction
- API data aggregation
- RSS feed processing
- Sitemap generation
- Link validation

**Queue:** `scraping`

**Example Job:**
```json
{
  "type": "rss-fetch",
  "sources": [
    "https://example.com/feed.xml"
  ],
  "filters": {
    "published_after": "2025-11-01"
  },
  "callback": "https://api.kubelab.live/webhooks/rss"
}
```

## Technology Stack

**Language:** Python 3.12
**Task Queue:** Celery + Redis
**Message Broker:** Redis/RabbitMQ
**Storage:** S3-compatible (MinIO)
**Monitoring:** Grafana + Prometheus

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Redis (for task queue)
- Python 3.12+ (for local development)

### Environment Variables

Create `.env` file in `infra/compose/apps/workers/`:

```bash
# Redis Configuration
REDIS_URL=redis://redis:6379/0

# Celery Configuration
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
CELERY_TASK_SERIALIZER=json
CELERY_RESULT_SERIALIZER=json
CELERY_ACCEPT_CONTENT=["json"]
CELERY_TIMEZONE=UTC

# Worker Configuration
WORKER_CONCURRENCY=4
WORKER_PREFETCH_MULTIPLIER=4
WORKER_MAX_TASKS_PER_CHILD=1000

# Notification Settings
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=notifications@mlorente.dev
SMTP_PASSWORD=app_password
SMTP_FROM=KubeLab <no-reply@mlorente.dev>

# PDF Generation
WKHTMLTOPDF_PATH=/usr/bin/wkhtmltopdf
PDF_DPI=300
PDF_PAPER_SIZE=A4

# Scraper Settings
SCRAPER_USER_AGENT=KubeLab-Bot/1.0
SCRAPER_MAX_RETRIES=3
SCRAPER_TIMEOUT=30

# Storage (S3-compatible)
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=kubelab-workers

# Logging
LOG_LEVEL=INFO
SENTRY_DSN=https://xxx@sentry.io/xxx
```

### Local Development

```bash
# Install dependencies
cd apps/workers
pip install -r requirements.txt

# Start Redis (via Docker)
docker run -d -p 6379:6379 redis:alpine

# Start Celery worker
celery -A workers worker --loglevel=info

# Start Celery beat (for scheduled tasks)
celery -A workers beat --loglevel=info

# Monitor with Flower
celery -A workers flower --port=5555
```

### Docker Deployment

```bash
# Build image
docker build -t kubelab-workers:latest .

# Run with docker-compose
cd infra/compose/apps/workers
docker compose up -d

# View logs
docker compose logs -f workers

# Scale workers
docker compose up -d --scale workers=4
```

## Creating New Workers

### 1. Define Task

Create a new file in the appropriate worker directory:

```python
# apps/workers/notifier/tasks.py
from celery import shared_task
from .email import send_email

@shared_task(bind=True, max_retries=3)
def send_notification(self, notification_type, recipient, message):
    try:
        if notification_type == 'email':
            send_email(recipient, message)
        elif notification_type == 'slack':
            send_slack(recipient, message)
        else:
            raise ValueError(f"Unknown notification type: {notification_type}")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
```

### 2. Register Task

Tasks are auto-discovered by Celery from `**/tasks.py` files.

### 3. Queue Task

From your application code:

```python
from workers.notifier.tasks import send_notification

# Async execution
send_notification.delay(
    notification_type='email',
    recipient='user@example.com',
    message={'subject': 'Hello', 'body': 'World'}
)

# With ETA (execute at specific time)
from datetime import datetime, timedelta
send_notification.apply_async(
    args=[...],
    eta=datetime.now() + timedelta(hours=1)
)

# With retry policy
send_notification.apply_async(
    args=[...],
    retry=True,
    retry_policy={
        'max_retries': 3,
        'interval_start': 0,
        'interval_step': 0.2,
        'interval_max': 0.2,
    }
)
```

## Monitoring

### Flower Web UI

Access at: `http://localhost:5555`

**Features:**
- Real-time task monitoring
- Worker status and statistics
- Task history and results
- Rate limiting configuration
- Task routing control

### Metrics (Prometheus)

Celery exports metrics for Prometheus:

```yaml
# docker-compose.yml
workers:
  environment:
    - CELERY_PROMETHEUS_METRICS=true
  labels:
    - "prometheus.scrape=true"
    - "prometheus.port=9808"
```

**Metrics exposed:**
- `celery_tasks_total` - Total tasks by state
- `celery_task_runtime_seconds` - Task execution time
- `celery_workers_total` - Number of workers
- `celery_queue_length` - Queue depth

### Logging

Structured JSON logging to stdout:

```json
{
  "timestamp": "2025-11-15T10:30:00Z",
  "level": "INFO",
  "task_id": "abc123",
  "task_name": "notifier.send_email",
  "message": "Email sent successfully",
  "recipient": "user@example.com"
}
```

## Scheduled Tasks

Define periodic tasks in `celerybeat-schedule.py`:

```python
from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    'cleanup-old-logs': {
        'task': 'workers.cleanup.delete_old_logs',
        'schedule': crontab(hour=2, minute=0),  # 2 AM daily
    },
    'generate-daily-reports': {
        'task': 'workers.pdf_generator.daily_report',
        'schedule': crontab(hour=6, minute=0),  # 6 AM daily
    },
    'fetch-rss-feeds': {
        'task': 'workers.scraper.fetch_feeds',
        'schedule': crontab(minute='*/30'),  # Every 30 minutes
    },
}
```

## Error Handling

### Retry Logic

```python
@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def flaky_task(self):
    try:
        # Task logic
        pass
    except (ConnectionError, TimeoutError) as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    except Exception as exc:
        # Log and don't retry
        logger.error(f"Fatal error in task: {exc}")
        raise
```

### Dead Letter Queue

Failed tasks after max retries go to DLQ:

```python
# celeryconfig.py
task_reject_on_worker_lost = True
task_acks_late = True
task_routes = {
    '*': {'queue': 'default'},
    'workers.*.failed': {'queue': 'dead_letter'},
}
```

### Alerts

Configure alerting for critical failures:

```python
from celery.signals import task_failure

@task_failure.connect
def task_failure_handler(sender, task_id, exception, **kwargs):
    # Send alert to monitoring system
    send_alert(
        severity='error',
        message=f'Task {sender.name} failed: {exception}',
        task_id=task_id
    )
```

## Performance Tuning

### Worker Concurrency

```bash
# Process-based (CPU-bound tasks)
celery -A workers worker --concurrency=8 --pool=prefork

# Thread-based (I/O-bound tasks)
celery -A workers worker --concurrency=100 --pool=gevent

# Async coroutines
celery -A workers worker --pool=eventlet
```

### Prefetch Optimization

```python
# celeryconfig.py
worker_prefetch_multiplier = 4  # How many tasks to grab at once
worker_max_tasks_per_child = 1000  # Restart worker after N tasks
```

### Queue Priority

```python
# High priority queue
send_notification.apply_async(
    args=[...],
    queue='high_priority',
    priority=10
)

# celeryconfig.py
task_routes = {
    'workers.notifier.send_critical': {'queue': 'high_priority'},
    'workers.scraper.*': {'queue': 'low_priority'},
}
```

## Security

### Task Validation

```python
from celery import Task

class SecureTask(Task):
    def apply_async(self, args=None, kwargs=None, **options):
        # Validate input
        if not self.validate_args(args, kwargs):
            raise ValueError("Invalid task arguments")
        return super().apply_async(args, kwargs, **options)
```

### Encryption

Encrypt sensitive task arguments:

```python
from cryptography.fernet import Fernet

cipher = Fernet(settings.ENCRYPTION_KEY)

@shared_task
def process_payment(encrypted_card_data):
    card_data = cipher.decrypt(encrypted_card_data)
    # Process payment
```

## Testing

### Unit Tests

```python
# tests/test_notifier.py
from workers.notifier.tasks import send_notification

def test_send_email_notification():
    result = send_notification.apply(
        args=('email', 'test@example.com', {'subject': 'Test'})
    )
    assert result.successful()
```

### Integration Tests

```python
# tests/integration/test_workers.py
def test_worker_processes_task(celery_worker):
    task = send_notification.delay('email', 'test@example.com', {})
    result = task.get(timeout=10)
    assert result == 'success'
```

## Troubleshooting

### Workers Not Processing Tasks

```bash
# Check worker status
celery -A workers inspect active
celery -A workers inspect stats

# Check queue depth
celery -A workers inspect reserved

# Restart workers
docker compose restart workers
```

### Redis Connection Issues

```bash
# Test Redis connectivity
redis-cli -h localhost -p 6379 ping

# Check Redis memory
redis-cli info memory

# Clear all queues (CAUTION)
redis-cli FLUSHDB
```

### Task Timeout

```python
# Set task timeout
@shared_task(time_limit=300, soft_time_limit=270)
def long_running_task():
    # Will be killed after 300 seconds
    # SoftTimeLimitExceeded raised at 270 seconds
    pass
```

## Best Practices

1. **Idempotent Tasks** - Tasks should be safe to retry
2. **Small Payloads** - Pass IDs, not entire objects
3. **Timeouts** - Always set task time limits
4. **Monitoring** - Track task duration and failure rates
5. **Rate Limiting** - Prevent API rate limit errors
6. **Cleanup** - Remove old task results regularly
7. **Testing** - Test tasks in isolation
8. **Logging** - Use structured logging for debugging
9. **Versioning** - Version task signatures
10. **Graceful Degradation** - Handle worker outages

## References

- [Celery Documentation](https://docs.celeryproject.org/)
- [Redis Documentation](https://redis.io/documentation)
- [Flower Monitoring](https://flower.readthedocs.io/)
- [Best Practices Guide](https://docs.celeryproject.org/en/stable/userguide/tasks.html#best-practices)

## Support

For issues or questions:

1. Check worker logs: `docker compose logs -f workers`
2. Monitor Flower dashboard: `http://localhost:5555`
3. Review Celery documentation
4. Create an issue in the project repository
