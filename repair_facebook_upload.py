"""Repair Facebook publishing for an already generated lesson."""

import argparse
import json
from pathlib import Path

from src.config import PROJECT_ROOT
from src.uploader import facebook_upload_configured, upload_to_facebook

CONTENT_PLAN_FILE = PROJECT_ROOT / "content_plan.json"
OUTPUT_DIR = PROJECT_ROOT / "output"
CONTENT_OUTPUT_DIR = OUTPUT_DIR / "content"


def _save_plan(plan):
    temporary_file = CONTENT_PLAN_FILE.with_name(f".{CONTENT_PLAN_FILE.name}.repair.tmp")
    temporary_file.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_file.replace(CONTENT_PLAN_FILE)


def _load_lesson_content(chapter, part):
    content_file = CONTENT_OUTPUT_DIR / f"lesson_{chapter}_{part}.json"
    if not content_file.is_file():
        raise FileNotFoundError(f"Lesson content file not found: {content_file}")
    payload = json.loads(content_file.read_text(encoding="utf-8"))
    content = payload.get("content")
    if not isinstance(content, dict):
        raise ValueError(f"Invalid lesson content file: {content_file}")
    return content


def _short_title(highlight, lesson_title):
    highlight = " ".join(str(highlight or "").split())
    if not highlight:
        highlight = f"نصيحة سريعة: {lesson_title}"
    suffix = " #مقاطع_قصيرة"
    return f"{highlight[:100 - len(suffix)].rstrip()}{suffix}"[:100].strip()


def repair_facebook_upload(chapter, part, run_id, force=False):
    if not facebook_upload_configured():
        raise RuntimeError(
            "ضع FACEBOOK_PAGE_ID وFACEBOOK_PAGE_ACCESS_TOKEN صالحين في ملف .env أولًا."
        )

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

    lesson_content = _load_lesson_content(chapter, part)
    lesson_title = lesson["title"]
    hashtags = lesson_content.get(
        "hashtags", "#الذكاء_الاصطناعي #تعلم_البرمجة #تعلم_الذكاء_الاصطناعي"
    )
    long_description = (
        f"هذا الفيديو جزء من سلسلة مطوري الذكاء الاصطناعي التي يقدمها شياتانيا.\n\n"
        f"درس اليوم: {lesson_title}\n\n{hashtags}"
    )
    highlight = str(lesson_content.get("short_form_highlight") or "").strip()
    if not highlight:
        highlight = f"نصيحة سريعة: {lesson_title}"
    short_title = _short_title(highlight, lesson_title)
    short_description = (
        f"{highlight}\n\n"
        f"شاهد الدرس الكامل على القناة.\n\n{hashtags}"
    )

    long_video = OUTPUT_DIR / f"long_video_{run_id}_{chapter}_{part}.mp4"
    short_video = OUTPUT_DIR / f"short_video_{run_id}_{chapter}_{part}.mp4"
    missing = [str(path) for path in (long_video, short_video) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing generated video files: " + ", ".join(missing))

    if lesson.get("facebook_id") and not force:
        print(f"ℹ️ Long Facebook video already recorded: {lesson['facebook_id']}")
    else:
        facebook_id = upload_to_facebook(long_video, lesson_title, long_description)
        if not facebook_id:
            raise RuntimeError("Facebook did not return an ID for the long video.")
        lesson["facebook_id"] = facebook_id
        _save_plan(plan)
        print(f"✅ Long Facebook video recorded: {facebook_id}")

    if lesson.get("facebook_short_id") and not force:
        print(f"ℹ️ Short Facebook video already recorded: {lesson['facebook_short_id']}")
    else:
        facebook_short_id = upload_to_facebook(
            short_video, short_title, short_description
        )
        if not facebook_short_id:
            raise RuntimeError("Facebook did not return an ID for the short video.")
        lesson["facebook_short_id"] = facebook_short_id
        _save_plan(plan)
        print(f"✅ Short Facebook video recorded: {facebook_short_id}")


def main():
    parser = argparse.ArgumentParser(
        description="Upload existing lesson videos to Facebook without regenerating them."
    )
    parser.add_argument("--chapter", type=int, default=1)
    parser.add_argument("--part", type=int, default=2)
    parser.add_argument(
        "--run-id",
        default="20260825",
        help="Date/run prefix used by the generated video filenames.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Upload again even when a Facebook ID is already recorded.",
    )
    args = parser.parse_args()
    repair_facebook_upload(args.chapter, args.part, args.run_id, args.force)


if __name__ == "__main__":
    main()
