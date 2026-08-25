"""Resume publishing a standalone story without re-uploading existing videos."""

import argparse
import json
import sys
from pathlib import Path

from src.config import PROJECT_ROOT, REQUIRE_FACEBOOK_UPLOAD
from src.uploader import (
    facebook_upload_configured,
    upload_to_facebook,
    upload_to_youtube,
)

STORIES_DIR = PROJECT_ROOT / "output" / "stories"


def _save_manifest(path, manifest):
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_path.replace(path)


def _short_title(highlight, lesson_title):
    highlight = " ".join(str(highlight or "").split())
    if not highlight:
        highlight = f"نصيحة سريعة: {lesson_title}"
    suffix = " #مقاطع_قصيرة"
    return f"{highlight[:100 - len(suffix)].rstrip()}{suffix}"[:100].strip()


def _load_manifest(run_id):
    path = Path(run_id)
    if not path.is_absolute():
        path = STORIES_DIR / path
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    if not path.is_file():
        raise FileNotFoundError(f"Story manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("type") != "standalone_story":
        raise ValueError(f"Not a standalone story manifest: {path}")
    return path, manifest


def _require_video(path, label):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{label} video not found: {path}")
    if path.stat().st_size <= 0:
        raise ValueError(f"{label} video is empty: {path}")
    return path


def repair_story_upload(run_id):
    manifest_path, manifest = _load_manifest(run_id)
    lesson = manifest.get("lesson")
    content = manifest.get("content")
    video_files = manifest.get("video_files")
    thumbnail_files = manifest.get("thumbnail_files", {})
    if not isinstance(lesson, dict) or not isinstance(content, dict):
        raise ValueError(f"Story manifest has invalid lesson/content data: {manifest_path}")
    if not isinstance(video_files, dict):
        raise ValueError(f"Story manifest has no video files: {manifest_path}")

    title = str(manifest.get("title") or lesson.get("title") or "").strip()
    if not title:
        raise ValueError(f"Story manifest has no title: {manifest_path}")
    hashtags = content.get(
        "hashtags", "#الذكاء_الاصطناعي #تعلم_البرمجة #قصص_تعليمية"
    )
    highlight = str(content.get("short_form_highlight") or "").strip()
    short_title = _short_title(highlight, title)
    short_description = f"{highlight}\n\nشاهد القصة الكاملة على القناة.\n\n{hashtags}"
    long_description = (
        f"قصة تعليمية عربية من قناة مطوري الذكاء الاصطناعي التي يقدمها شياتانيا.\n\n"
        f"{title}\n\n{hashtags}"
    )

    long_video = _require_video(video_files.get("long"), "Long-form")
    short_video = _require_video(video_files.get("short"), "Short")
    long_thumbnail = Path(thumbnail_files["long"]) if thumbnail_files.get("long") else None
    short_thumbnail = Path(thumbnail_files["short"]) if thumbnail_files.get("short") else None

    manifest["status"] = "resuming"
    manifest.pop("error", None)
    _save_manifest(manifest_path, manifest)

    if not lesson.get("youtube_id"):
        raise RuntimeError(
            "لا يوجد معرّف YouTube للفيديو الطويل؛ لا يمكن استكماله بأمان دون معرفة هل رُفع سابقًا."
        )
    print(f"ℹ️ Long YouTube video already recorded: {lesson['youtube_id']}")

    if not lesson.get("youtube_short_id"):
        short_id = upload_to_youtube(
            short_video,
            short_title,
            short_description,
            "الذكاء الاصطناعي,قصص تعليمية,مقاطع قصيرة",
            short_thumbnail,
        )
        if not short_id:
            raise RuntimeError("YouTube did not return an ID for the short story video.")
        lesson["youtube_short_id"] = short_id
        _save_manifest(manifest_path, manifest)
        print(f"✅ Short YouTube video recorded: {short_id}")
    else:
        print(f"ℹ️ Short YouTube video already recorded: {lesson['youtube_short_id']}")

    if REQUIRE_FACEBOOK_UPLOAD:
        if not facebook_upload_configured():
            raise RuntimeError(
                "ضع FACEBOOK_PAGE_ID وFACEBOOK_PAGE_ACCESS_TOKEN صالحين في ملف .env أولًا."
            )
        if not lesson.get("facebook_id"):
            facebook_id = upload_to_facebook(long_video, title, long_description)
            if not facebook_id:
                raise RuntimeError("Facebook did not return an ID for the long story video.")
            lesson["facebook_id"] = facebook_id
            _save_manifest(manifest_path, manifest)
            print(f"✅ Long Facebook video recorded: {facebook_id}")
        else:
            print(f"ℹ️ Long Facebook video already recorded: {lesson['facebook_id']}")

        if not lesson.get("facebook_short_id"):
            facebook_short_id = upload_to_facebook(
                short_video, short_title, short_description
            )
            if not facebook_short_id:
                raise RuntimeError("Facebook did not return an ID for the short story video.")
            lesson["facebook_short_id"] = facebook_short_id
            _save_manifest(manifest_path, manifest)
            print(f"✅ Short Facebook video recorded: {facebook_short_id}")
    else:
        print("ℹ️ Facebook publishing is disabled in .env.")

    manifest["status"] = "complete"
    _save_manifest(manifest_path, manifest)
    print(f"✅ اكتمل استكمال القصة: {title}")
    print(f"📄 سجل التشغيل: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Resume a standalone story without re-uploading an existing long YouTube video."
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Story manifest filename or ID, for example story_20260825_175307_layan_robot",
    )
    args = parser.parse_args()
    try:
        repair_story_upload(args.run_id)
    except KeyboardInterrupt:
        print("❌ تم إيقاف الاستكمال. أعد تشغيل نفس الأمر لاحقًا.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"❌ {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
