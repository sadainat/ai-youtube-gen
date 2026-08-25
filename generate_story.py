"""Generate and publish one standalone Arabic educational story.

This script reuses the normal production pipeline but never changes
content_plan.json, so one-off stories cannot disturb the course sequence.
"""

import argparse
import datetime
import json
from pathlib import Path

from main import OUTPUT_DIR, produce_lesson_videos, validate_runtime
from src.generator import generate_story_content

STORY_TITLE = "قصة ليان والروبوت الذي تعلّم من أخطائه"
STORY_KEY = "layan_robot"


def _write_manifest(path, manifest):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_path.replace(path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate and publish one standalone Arabic educational story."
    )
    parser.add_argument(
        "--title",
        default=STORY_TITLE,
        help="Arabic story title (defaults to the selected channel story).",
    )
    args = parser.parse_args()
    story_title = args.title.strip() or STORY_TITLE

    validate_runtime()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_id = f"story_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{STORY_KEY}"
    manifest_path = OUTPUT_DIR / "stories" / f"{run_id}.json"
    long_video_path = OUTPUT_DIR / f"long_video_{run_id}.mp4"
    short_video_path = OUTPUT_DIR / f"short_video_{run_id}.mp4"
    lesson = {
        "chapter": "story",
        "part": STORY_KEY,
        "title": story_title,
        "status": "standalone",
        "youtube_id": None,
        "youtube_short_id": None,
    }
    story_content = generate_story_content(story_title)
    manifest = {
        "type": "standalone_story",
        "status": "in_progress",
        "run_id": run_id,
        "title": story_title,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "lesson": lesson,
        "content": story_content,
        "video_files": {
            "long": str(long_video_path),
            "short": str(short_video_path),
        },
        "thumbnail_files": {
            "long": str(OUTPUT_DIR / "thumbnail_long.jpg"),
            "short": str(OUTPUT_DIR / "thumbnail_short.jpg"),
        },
    }
    _write_manifest(manifest_path, manifest)

    try:
        long_video_id = produce_lesson_videos(
            lesson,
            lesson_content=story_content,
            run_id=run_id,
        )
        if not long_video_id:
            raise RuntimeError("لم يُرجع رفع الفيديو الطويل معرّفًا صالحًا.")
        manifest["status"] = "complete"
    except KeyboardInterrupt:
        manifest["status"] = "cancelled"
        manifest["error"] = "تم إيقاف التشغيل يدويًا قبل اكتمال النشر."
        raise
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        raise
    finally:
        manifest["lesson"] = lesson
        _write_manifest(manifest_path, manifest)

    print(f"✅ اكتمل تجهيز القصة المستقلة: {story_title}")
    print(f"📄 سجل التشغيل: {manifest_path}")
    print(f"🎬 الفيديو الطويل: {long_video_path}")
    print(f"🎬 الفيديو القصير: {short_video_path}")
    print(f"▶️ YouTube الطويل: {lesson.get('youtube_id')}")
    print(f"▶️ YouTube القصير: {lesson.get('youtube_short_id')}")
    print(f"📘 Facebook الطويل: {lesson.get('facebook_id')}")
    print(f"📘 Facebook القصير: {lesson.get('facebook_short_id')}")


if __name__ == "__main__":
    main()
