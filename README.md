# Gemini YouTube Automation

The project includes a GitHub Actions workflow that runs daily at 7:00 AM UTC. It:
- Generates lesson scripts using Gemini.
- Produces long-form and short YouTube videos.
- Uploads them automatically with appropriate thumbnails and metadata.

## Project Structure
```text
gemini-youtube-automation/
├── .github/
│   └── workflows/
│       └── main.yml         # GitHub Actions workflow configuration
├── src/                     # Source directory for Python modules
│   ├── init.py          # Initializes the 'src' package
│   ├── generator.py         # Code for generating content and video
│   └── uploader.py          # Code for uploading to YouTube
├── .gitignore               # Files and directories to ignore in version control
├── content_plan.json        # Contains topics for moving forward.
├── main.py                  # Main entry point to run the application
└── requirements.txt         # List of Python packages needed
```

## Setup Instructions

1. **Clone the repository** and open a terminal in the project root (the folder that contains `main.py`).

2. **Create the Python 3.12 environment and install dependencies**:
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate
   python -m pip install -r requirements.txt
   ```

3. **Environment variables**
    - **`GOOGLE_API_KEY`** (required): Google AI / Gemini API key.
    - **`GEMINI_MODEL`** (optional): Gemini model name. Defaults to `gemini-3.6-flash`.
    - **`PEXELS_API_KEY`** (required when `REQUIRE_REAL_VIDEO=true`): Pexels API key used to download real video clips.
    - **`REQUIRE_REAL_VIDEO`** (optional): Defaults to `true`; set to `false` only if image-slide fallback is intentional.
    - **`REQUIRE_FACEBOOK_UPLOAD`** (optional): Defaults to `true`; set to `false` only when Facebook publishing is intentionally disabled.
    - **`ARABIC_VOICE`** (optional): Neural Arabic voice name. Defaults to `ar-SA-HamedNeural` (Saudi Arabic male voice).
    - **`FACEBOOK_PAGE_ID`** (required when Facebook upload is enabled): ID of the Facebook Page used for publishing.
    - **`FACEBOOK_PAGE_ACCESS_TOKEN`** (required when Facebook upload is enabled): Long-lived Page access token. Keep it secret.
    - **`META_GRAPH_VERSION`** (optional): Meta Graph API version. Defaults to `v23.0`.
    - **`YOUTUBE_CREDENTIALS_JSON`** (optional): Complete OAuth credentials JSON for GitHub Actions.

4. **YouTube upload (local)**
   - Create a YouTube Data API OAuth **Desktop app** client in Google Cloud and download the JSON as `client_secrets.json` in the project root.
   - On the first run, the app opens a browser to complete OAuth and writes `credentials.json` for later runs.

## Execution methods

### Run locally

From any directory, after activating the project environment and setting the required variables:

```bash
python /path/to/ai-youtube-gen/main.py
```

The application resolves project files from its own root. With `REQUIRE_REAL_VIDEO=true`, a missing or invalid Pexels clip stops the run instead of silently producing a still-image video. Set it to `false` only when that fallback is acceptable.

On Windows, if `python` is not on your PATH, try `py main.py`.

This loads or creates `content_plan.json`, produces up to one pending lesson (long + short video), uploads to YouTube, updates lesson status, and writes artifacts under `output/`. Ensure [FFmpeg](https://ffmpeg.org/) is available for MoviePy and audio conversion. YouTube OAuth uses local `client_secrets.json`/`credentials.json`, or restores `YOUTUBE_CREDENTIALS_JSON` in automation.

When the Facebook Page variables are configured, the same long-form and Shorts videos are also published to that Page through the Meta Graph API.

### Run on GitHub Actions (scheduled)

The repo is intended to run on a **daily schedule** (for example **7:00 AM UTC**) via a workflow under `.github/workflows/` (for example `main.yml`). Typical setup:

1. In **Settings → Secrets and variables → Actions**, add these repository secrets:
   - `GOOGLE_API_KEY`
   - `PEXELS_API_KEY`
   - `FACEBOOK_PAGE_ID`
   - `FACEBOOK_PAGE_ACCESS_TOKEN`
   - `YOUTUBE_CREDENTIALS_JSON`: the complete contents of your local `credentials.json`.
2. The workflow in `.github/workflows/generate-and-publish.yml` installs Python and FFmpeg, runs `python main.py`, and commits the updated `content_plan.json` so the next run selects the next pending lesson.
3. Push the workflow to the default branch, then use **Actions → Generate and publish Arabic video → Run workflow** for the first test. Scheduled runs execute at 06:00 UTC.

Keep all API keys and OAuth files in GitHub Secrets. Do not commit `.env`, `credentials.json`, or client secrets.

### Repair the first Facebook upload

The first run may have uploaded the two videos to YouTube while Facebook rejected them because the Page token had expired. After replacing `FACEBOOK_PAGE_ACCESS_TOKEN` in `.env` with a valid long-lived Page token, repair the existing files without regenerating or uploading to YouTube:

```bash
cd /Users/mac/Documents/ai/ai-youtube-gen
source venv/bin/activate
python repair_facebook_upload.py --chapter 1 --part 2 --run-id 20260825
```

Add `--force` only when you intentionally want to publish duplicate Facebook videos. The repair command stores `facebook_id` and `facebook_short_id` in `content_plan.json` after each successful upload.

### Retry YouTube thumbnails

If a video was uploaded but its thumbnail hit YouTube's size or rate limit, retry only the thumbnails without uploading duplicate videos:

```bash
python repair_youtube_thumbnails.py --chapter 1 --part 2
```

The script compresses oversized PNG files to JPEG automatically. If YouTube returns `uploadRateLimitExceeded`, it stops after the first affected thumbnail so it does not waste another request; wait about 24 hours and run the same command again. YouTube's API does not expose an exact reset time.

Adjust steps to match your actual workflow file once it is committed.

### Generate a standalone Arabic story

To create an extra story without replacing or advancing a lesson in `content_plan.json`, run:

```bash
cd /Users/mac/Documents/ai/ai-youtube-gen
source venv/bin/activate
python generate_story.py
```

The selected story is **قصة ليان والروبوت الذي تعلّم من أخطائه**. The command generates Arabic narration, validated real Pexels video clips, a long-form video, and a short video, then publishes both to the configured YouTube channel and Facebook Page. Each run is recorded under `output/stories/`; the course plan remains unchanged. If the process is interrupted after the long video is uploaded, use `repair_story_upload.py` with that run ID instead of running `generate_story.py` again.

To resume a cancelled or partially published story without re-uploading an existing YouTube video:

```bash
python repair_story_upload.py --run-id story_YYYYMMDD_HHMMSS_layan_robot
```

The repair command reads recorded IDs, uploads only missing destinations, and updates the story manifest after each successful upload. It does not modify `content_plan.json`.
