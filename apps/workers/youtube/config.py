"""Configuration and constants for YouTube worker."""

import os
from pathlib import Path

# Duration thresholds (seconds)
SHORT_VIDEO_MAX = 300      # 5 minutes
MEDIUM_VIDEO_MAX = 900     # 15 minutes

# Default values
DEFAULT_LANGUAGES = ["es", "en"]
DEFAULT_MAX_RESULTS = 50
DEFAULT_OUTPUT_DIR = Path("/app/data/youtube")  # Docker volume path

# API limits
YOUTUBE_API_BATCH_SIZE = 50

# Environment variable keys
ENV_API_KEY = "YOUTUBE_API_KEY"
ENV_TRANSCRIPT_FIXTURES = "YOUTUBE_TRANSCRIPT_FIXTURES_DIR"


def get_env(key: str, default=None):
    """Get environment variable with optional default."""
    return os.environ.get(key, default)


def format_number(value) -> str:
    """Format number with thousand separators or return 'N/A'."""
    if value is None:
        return 'N/A'
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return 'N/A'
