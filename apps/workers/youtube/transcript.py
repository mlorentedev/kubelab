"""YouTube transcript downloading."""

from pathlib import Path
from typing import List, Optional
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

from .config import DEFAULT_LANGUAGES, ENV_TRANSCRIPT_FIXTURES, get_env


class YouTubeTranscriptDownloader:
    def __init__(self, languages: Optional[List[str]] = None):
        self.languages = languages or DEFAULT_LANGUAGES
        self.client = YouTubeTranscriptApi()

    def get_transcript(self, video_id: str) -> str:
        try:
            transcript = self.client.fetch(video_id, languages=self.languages)
            return self._format_transcript(transcript)
        except (TranscriptsDisabled, NoTranscriptFound):
            # Fallback logic could be improved or removed for production worker
            raise RuntimeError(f"No transcript found for video {video_id} in languages {self.languages}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error fetching transcript for {video_id}: {e}")

    def save_transcript(self, video_id: str, output_dir: str) -> str:
        text = self.get_transcript(video_id)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = output_path / f"{video_id}_transcript.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)
        return str(filename)

    def _format_transcript(self, transcript) -> str:
        lines = []
        for entry in transcript:
            text = (
                entry.get("text", "")
                if isinstance(entry, dict)
                else getattr(entry, "text", "")
            )
            text = text.strip()
            if text:
                lines.append(text)
        return "\n".join(lines)
