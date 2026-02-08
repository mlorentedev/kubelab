"""Celery tasks for YouTube operations."""

from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from .transcript import YouTubeTranscriptDownloader
from .analyzer import YouTubeChannelAnalyzer
from .exporters import (
    export_to_csv,
    export_channel_stats,
    export_engagement_trends_report,
    export_best_videos_report,
    export_latest_videos_report,
    export_output_readme
)
from .config import DEFAULT_OUTPUT_DIR, DEFAULT_MAX_RESULTS

logger = get_task_logger(__name__)

@shared_task(bind=True, max_retries=3)
def download_transcript(self, video_id: str, languages: Optional[List[str]] = None):
    """
    Download transcript for a specific video.

    Args:
        video_id: YouTube Video ID.
        languages: List of preferred languages (e.g., ['en', 'es']).
    """
    logger.info(f"Starting transcript download for video {video_id}")
    try:
        downloader = YouTubeTranscriptDownloader(languages=languages)
        output_dir = DEFAULT_OUTPUT_DIR / "transcripts"
        file_path = downloader.save_transcript(video_id, str(output_dir))
        logger.info(f"Transcript saved to {file_path}")
        return {"status": "success", "file_path": file_path}
    except Exception as exc:
        logger.error(f"Failed to download transcript for {video_id}: {exc}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True)
def analyze_channels_report(self, channels: List[Dict], max_results: int = DEFAULT_MAX_RESULTS):
    """
    Analyze a list of channels and generate a full report.
    This is a long-running task that processes multiple channels.
    """
    logger.info(f"Starting analysis for {len(channels)} channels")

    try:
        analyzer = YouTubeChannelAnalyzer()

        # Validate API Key first
        analyzer.validate_api_key()

        # Fetch Data
        channels_data = analyzer.get_multiple_channels_videos(
            channels,
            max_results_per_channel=max_results
        )

        if not channels_data:
            return {"status": "warning", "message": "No data retrieved"}

        # Prepare Output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_OUTPUT_DIR / "reports" / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate Reports
        export_to_csv(channels_data, output_dir / f"channels_videos_{timestamp}.csv")
        export_channel_stats(channels_data, output_dir / f"channel_stats_{timestamp}.txt")
        export_engagement_trends_report(channels_data, output_dir / f"engagement_trends_{timestamp}.txt")
        export_best_videos_report(channels_data, output_dir / f"best_videos_{timestamp}.txt")
        export_latest_videos_report(channels_data, output_dir / f"latest_videos_{timestamp}.txt")
        export_output_readme(output_dir, timestamp, channels_data)

        logger.info(f"Reports generated in {output_dir}")
        return {"status": "success", "output_dir": str(output_dir)}

    except Exception as exc:
        logger.error(f"Analysis failed: {exc}")
        raise self.retry(exc=exc, countdown=300)  # Retry in 5 mins if API fails
