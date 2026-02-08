# Worker Modules & Architecture Roadmap

This document outlines the architectural vision for the `apps/workers` service. We follow a **Modular Monolith** pattern: a single Docker service running Celery that hosts multiple distinct "domains" (modules) of logic.

## 🏗 Architecture Strategy

*   **Technology:** Python 3.12 + Celery + Redis.
*   **Why Python?** Superior ecosystem for Data Science, AI, and Media wrappers.
*   **Why Monolith?** Reduces infrastructure overhead (1 pod vs 5) and simplifies dependency management for a personal platform.
*   **Scalability:** The entire worker service can be scaled horizontally (add more replicas) to handle increased load across any domain.

---

## 📂 Module Catalog

### 1. 📺 YouTube (Active)
**Status:** ✅ Implemented
**Directory:** `apps/workers/youtube/`

The core content engine. It automates the retrieval and analysis of video content to feed downstream creative processes.

*   **Key Responsibilities:**
    *   **Transcript Download:** Fetches subtitles (official or auto-generated) for any video.
    *   **Channel Analysis:** Analyzing growth metrics, engagement rates, and posting schedules.
    *   **Report Generation:** Creating CSV/Text summaries of channel performance.
*   **Dependencies:** `youtube-transcript-api`, `google-api-python-client`.

### 2. 🎬 Media Processing (Proposed)
**Status:** 🚧 Skeleton Created
**Directory:** `apps/workers/media/`

Handles heavy CPU-bound tasks related to image and video manipulation. This keeps the web API fast by offloading processing.

*   **Key Responsibilities:**
    *   **Audio Extraction:** Convert Video -> MP3 (for transcription).
    *   **Image Optimization:** Convert upload (PNG/JPG) -> WebP/AVIF + Resize (Thumbnails).
    *   **Video Snippets:** Extract viral clips from long-form content based on timestamps.
*   **Technical Requirements:** Requires `ffmpeg` installed in the Docker container (Done).

### 3. 🧠 AI & LLM (Proposed)
**Status:** 🚧 Skeleton Created
**Directory:** `apps/workers/ai/`

The intelligence layer. It acts as the bridge between raw data (transcripts, logs) and usable content using Large Language Models.

*   **Key Responsibilities:**
    *   **Summarization:** Transcript -> Blog Post Draft / Tweet Thread.
    *   **RAG Ingestion:** Chunking text and generating Vector Embeddings for a Chatbot.
    *   **Sentiment Analysis:** Classifying comments or feedback.
*   **Dependencies:** `openai`, `langchain`, `chromadb` (or similar vector store client).

### 4. 📊 Data Aggregator (Proposed)
**Status:** 🚧 Skeleton Created
**Directory:** `apps/workers/data/`

Feeds the "Digital Garden". It runs on a schedule (Celery Beat) to fetch your digital footprints from external platforms.

*   **Key Responsibilities:**
    *   **GitHub Sync:** Fetch recent commits/PRs for a "Coding Activity" widget.
    *   **Spotify/Letterboxd:** Sync "What I'm listening/watching".
    *   **Health:** Sync Strava/Garmin activity data.
*   **Goal:** Create a `json` or DB record that the Frontend can read instantly without hitting external APIs.

### 5. 🛠 System & DevOps (Proposed)
**Status:** 🚧 Skeleton Created
**Directory:** `apps/workers/system/`

Maintenance tasks to ensure platform health and data safety.

*   **Key Responsibilities:**
    *   **Database Backups:** Dump Postgres -> Compress -> Upload to S3 (MinIO).
    *   **Link Rot Monitor:** Crawl `sitemap.xml` weekly to find 404 errors.
    *   **Cleanup:** Delete temp files and old logs to prevent disk saturation.

---

## 🔄 Integration Patterns

### How to Trigger
1.  **From Python (Internal):**
    ```python
    from workers.youtube.tasks import download_transcript
    download_transcript.delay(video_id="123")
    ```
2.  **From Go API / n8n (External):**
    Push a JSON message to the Redis Queue `celery`.
    *   **Queue:** `youtube` (or `default`)
    *   **Task Name:** `youtube.tasks.download_transcript`
    *   **Args:** `["123"]`

### Future: n8n Orchestration
n8n will act as the "Manager", deciding *when* to run things, while these Celery workers act as the "Employees" executing the hard skills.

*   **Example Flow:**
    1.  **n8n:** Trigger: "New YouTube Video Uploaded".
    2.  **n8n:** Action: Call Worker `youtube.download_transcript`.
    3.  **Worker:** Downloads text, saves to storage, returns path.
    4.  **n8n:** Action: Call Worker `ai.summarize_text` with that path.
    5.  **Worker:** Generates summary.
    6.  **n8n:** Action: Send Telegram message with summary.
