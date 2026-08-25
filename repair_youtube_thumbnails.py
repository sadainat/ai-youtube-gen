"""Retry YouTube thumbnails without uploading the videos again."""

import argparse
import json
import sys
from pathlib import Path

from googleapiclient.errors import HttpError

from src.config import PROJECT_ROOT
from src.uploader import get_authenticated_service, upload_youtube_thumbnail

CONTENT_PLAN_FILE = PROJECT_ROOT / "content_plan.json"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _thumbnail_path(kind):
    for extension in (".jpg", ".jpeg", ".png"):
        path = OUTPUT_DIR / f"thumbnail_{kind}{extension}"
        if path.is_file():
            return path
    raise FileNotFoundError(f"Thumbnail for {kind} video was not found in {OUTPUT_DIR}")


def _is_thumbnail_rate_limit(error):
    """Identify YouTube's channel-level custom-thumbnail throttle."""
    status = getattr(getattr(error, "resp", None), "status", None)
    if not isinstance(error, HttpError) or str(status) != "429":
        return False

    content = getattr(error, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    return "uploadRateLimitExceeded" in str(content) or "uploadRateLimitExceeded" in str(error)


def repair_youtube_thumbnails(chapter, part):
    plan = json.loads(CONTENT_PLAN_FILE.read_text(encoding="utf-8"))
    lesson = next(
        (
            item
            for item in plan.get("lessons", [])
            if item.get("chapter") == chapter and item.get("part") == part
        ),
        None,
    )
    if lesson is None:
        raise ValueError(f"Lesson {chapter}/{part} was not found in {CONTENT_PLAN_FILE}")

    uploads = []
    if lesson.get("youtube_id"):
        uploads.append(("long", lesson["youtube_id"], _thumbnail_path("long")))
    if lesson.get("youtube_short_id"):
        uploads.append(
            ("short", lesson["youtube_short_id"], _thumbnail_path("short"))
        )
    if not uploads:
        raise ValueError("No YouTube video IDs were found for this lesson.")

    youtube = get_authenticated_service()
    failures = []
    for kind, video_id, thumbnail in uploads:
        try:
            upload_youtube_thumbnail(video_id, thumbnail, youtube_service=youtube)
            print(f"✅ {kind} thumbnail uploaded: {video_id}")
        except Exception as error:
            if _is_thumbnail_rate_limit(error):
                message = (
                    "YouTube رفض رفع الصور المصغّرة مؤقتًا بسبب حد القناة "
                    "(uploadRateLimitExceeded). انتظر نحو 24 ساعة ثم أعد تشغيل الأمر."
                )
                failures.append(f"{kind}: {message}")
                print(f"⚠️ {message}")
                break
            failures.append(f"{kind}: {error}")
            print(f"❌ {kind} thumbnail failed: {error}")

    if failures:
        raise RuntimeError("Thumbnail repair failed: " + " | ".join(failures))


def main():
    parser = argparse.ArgumentParser(
        description="Retry existing YouTube thumbnails without re-uploading videos."
    )
    parser.add_argument("--chapter", type=int, default=1)
    parser.add_argument("--part", type=int, default=2)
    args = parser.parse_args()
    try:
        repair_youtube_thumbnails(args.chapter, args.part)
    except Exception as error:
        print(f"❌ {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
