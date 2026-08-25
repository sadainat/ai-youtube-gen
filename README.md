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

2. **Install dependencies** (Python 3 recommended):
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment variables**
   - **`GOOGLE_API_KEY`** (required): Google AI / Gemini API key.
   - **`PEXELS_API_KEY`** (optional): If unset, slide backgrounds fall back to solid colors.
   - **`ARABIC_VOICE`** (optional): Neural Arabic voice name. Defaults to `ar-SA-HamedNeural` (Saudi Arabic male voice).
   - **`FACEBOOK_PAGE_ID`** (optional): ID of the Facebook Page used for publishing.
   - **`FACEBOOK_PAGE_ACCESS_TOKEN`** (optional): Long-lived Page access token. Keep it secret.

4. **YouTube upload (local)**
   - Create a YouTube Data API OAuth **Desktop app** client in Google Cloud and download the JSON as `client_secrets.json` in the project root.
   - On the first run, the app opens a browser to complete OAuth and writes `credentials.json` for later runs.

## Execution methods

### Run locally

From the project root, with `GOOGLE_API_KEY` set (and optionally `PEXELS_API_KEY`):

```bash
python main.py
```

On Windows, if `python` is not on your PATH, try `py main.py`.

This loads or creates `content_plan.json`, produces up to one pending lesson (long + short video), uploads to YouTube, updates lesson status, and writes artifacts under `output/`. Ensure [FFmpeg](https://ffmpeg.org/) is available if MoviePy or audio conversion fails on your system.

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

Adjust steps to match your actual workflow file once it is committed.
