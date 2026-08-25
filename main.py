import datetime
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

from src.config import PROJECT_ROOT, REQUIRE_FACEBOOK_UPLOAD, REQUIRE_REAL_VIDEO
from src.generator import (
    generate_curriculum,
    generate_lesson_content,
    text_to_speech,
    generate_visuals,
    get_pexels_video,
    create_video,
    YOUR_NAME
)
from src.uploader import (
    facebook_upload_configured,
    upload_to_facebook,
    upload_to_youtube,
)

CONTENT_PLAN_FILE = PROJECT_ROOT / "content_plan.json"
OUTPUT_DIR = PROJECT_ROOT / "output"
CONTENT_OUTPUT_DIR = OUTPUT_DIR / "content"
LESSONS_PER_RUN = 1


def validate_runtime():
    """Fail early when required tools or real-video credentials are missing."""
    missing = []
    if not os.getenv("GOOGLE_API_KEY", "").strip():
        missing.append("GOOGLE_API_KEY")
    if REQUIRE_REAL_VIDEO and not os.getenv("PEXELS_API_KEY", "").strip():
        missing.append("PEXELS_API_KEY (مطلوب للفيديو الحقيقي)")
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg")
    if REQUIRE_REAL_VIDEO and not shutil.which("ffprobe"):
        missing.append("ffprobe (مطلوب للتحقق من الفيديو الحقيقي)")
    if REQUIRE_FACEBOOK_UPLOAD and not facebook_upload_configured():
        missing.append("FACEBOOK_PAGE_ID وFACEBOOK_PAGE_ACCESS_TOKEN")
    if missing:
        raise RuntimeError("متطلبات التشغيل غير مكتملة: " + ", ".join(missing))


def upload_facebook_or_raise(video_path, title, description):
    """Publish to Facebook when enabled and fail instead of masking errors."""
    if not REQUIRE_FACEBOOK_UPLOAD:
        return None
    facebook_id = upload_to_facebook(video_path, title, description)
    if not facebook_id:
        raise RuntimeError(
            "فشل رفع الفيديو إلى Facebook. تحقق من صلاحية FACEBOOK_PAGE_ACCESS_TOKEN."
        )
    return facebook_id


def get_content_plan():
    if not CONTENT_PLAN_FILE.exists():
        print("📄 content_plan.json not found. Generating new plan...")
        new_plan = generate_curriculum()
        with open(CONTENT_PLAN_FILE, 'w') as f:
            json.dump(new_plan, f, ensure_ascii=False, indent=2)
        print(f"✅ New curriculum saved to {CONTENT_PLAN_FILE}")
        return new_plan
    else:
        try:
            with open(CONTENT_PLAN_FILE, 'r') as f:
                plan = json.load(f)
            if not plan.get("lessons") or not isinstance(plan["lessons"], list):
                raise ValueError("⚠️ Invalid or empty lesson plan detected.")
            return plan
        except Exception as e:
            print(f"❌ ERROR loading existing plan: {e}. Regenerating...")
            new_plan = generate_curriculum()
            with open(CONTENT_PLAN_FILE, 'w') as f:
                json.dump(new_plan, f, ensure_ascii=False, indent=2)
            return new_plan


def update_content_plan(plan):
    with open(CONTENT_PLAN_FILE, 'w') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)


def save_lesson_content(lesson, lesson_content):
    CONTENT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    content_file = CONTENT_OUTPUT_DIR / f"lesson_{lesson['chapter']}_{lesson['part']}.json"
    content_file.write_text(
        json.dumps(
            {
                "chapter": lesson["chapter"],
                "part": lesson["part"],
                "title": lesson["title"],
                "content": lesson_content,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"📝 Arabic lesson content saved to: {content_file}")
    return content_file



def produce_lesson_videos(lesson, lesson_content=None, run_id=None):
    print(f"\n▶️ Starting production for Lesson: '{lesson['title']}'")
    unique_id = run_id or f"{datetime.datetime.now().strftime('%Y%m%d')}_{lesson['chapter']}_{lesson['part']}"

    if lesson_content is None:
        print("\n--- Creating Arabic Lesson Content ---")
        lesson_content = generate_lesson_content(lesson['title'])
    else:
        print("\n--- Using prepared Arabic Story Content ---")
    save_lesson_content(lesson, lesson_content)

    print("\n--- Producing Long-Form Video ---")

    intro_slide = {"title": lesson['title'], "content": f"الفصل {lesson['chapter']} | الجزء {lesson['part']}"}
    outro_slide = {"title": "شكرًا على المشاهدة", "content": "أعجبك المحتوى؟ شاركه واشترك في القناة لمزيد من دروس الذكاء الاصطناعي\n#مطورو_الذكاء_الاصطناعي"}
    all_slides = [intro_slide] + lesson_content['long_form_slides'] + [outro_slide]

    slide_scripts = [
        f"درسنا اليوم بعنوان: {lesson['title']}.",
        *[s['content'] for s in lesson_content['long_form_slides']],
        "شكرًا على المشاهدة. إذا وجدت هذا الدرس مفيدًا، اشترك في القناة واضغط زر الإعجاب."
    ]

    slide_audio_paths = []
    for i, script in enumerate(slide_scripts):
        audio_path = OUTPUT_DIR / f"audio_slide_{i+1}_{unique_id}.mp3"
        wav_path = text_to_speech(script, audio_path)
        slide_audio_paths.append(wav_path)
    print(f"🎧 Total slide audios: {len(slide_audio_paths)}")

    slide_dir = OUTPUT_DIR / f"slides_long_{unique_id}"
    slide_paths = []
    for i, slide in enumerate(all_slides):
        fallback_path = None
        if not REQUIRE_REAL_VIDEO:
            fallback_path = generate_visuals(
                output_dir=slide_dir,
                video_type="long",
                slide_content=slide,
                slide_number=i + 1,
                total_slides=len(all_slides),
            )
        video_path = OUTPUT_DIR / "media" / f"long_{unique_id}_{i + 1}.mp4"
        real_video_path = get_pexels_video(slide.get("title", lesson["title"]), "long", video_path)
        if real_video_path:
            slide_paths.append(real_video_path)
        elif REQUIRE_REAL_VIDEO:
            raise RuntimeError(
                f"لم يتم العثور على مقطع فيديو حقيقي للشريحة {i + 1}: {slide.get('title', '')}"
            )
        else:
            slide_paths.append(fallback_path)

    long_video_path = OUTPUT_DIR / f"long_video_{unique_id}.mp4"
    print(f"🎥 Creating long-form video at: {long_video_path}")
    create_video(slide_paths, slide_audio_paths, long_video_path, 'long')

    long_thumb_path = generate_visuals(
        output_dir=OUTPUT_DIR,
        video_type='long',
        thumbnail_title=lesson['title']
    )

    print("\n--- Producing Short Video ---")
    # short_script = f"{lesson_content['short_form_highlight']}"
    short_script = lesson_content['short_form_highlight']
    short_audio_mp3_path = OUTPUT_DIR / f"short_audio_{unique_id}.mp3"
    short_audio_path = text_to_speech(short_script, short_audio_mp3_path)

    short_slide_dir = OUTPUT_DIR / f"slides_short_{unique_id}"
    short_slide_content = {
        "title": "نصيحة سريعة",
        "content": f"{lesson_content['short_form_highlight']}\n\n#مطورو_الذكاء_الاصطناعي",
    }
    short_slide_path = None
    if not REQUIRE_REAL_VIDEO:
        short_slide_path = generate_visuals(
            output_dir=short_slide_dir,
            video_type="short",
            slide_content=short_slide_content,
            slide_number=1,
            total_slides=1,
        )
    short_visual_path = OUTPUT_DIR / "media" / f"short_{unique_id}.mp4"
    short_media_path = get_pexels_video(lesson["title"], "short", short_visual_path)
    if not short_media_path:
        if REQUIRE_REAL_VIDEO:
            raise RuntimeError(
                f"لم يتم العثور على مقطع فيديو حقيقي للفيديو القصير: {lesson['title']}"
            )
        short_media_path = short_slide_path

    short_video_path = OUTPUT_DIR / f"short_video_{unique_id}.mp4"
    print(f"🎥 Creating short video at: {short_video_path}")
    create_video([short_media_path], [short_audio_path], short_video_path, 'short')

    short_thumb_path = generate_visuals(
        output_dir=OUTPUT_DIR,
        video_type='short',
        thumbnail_title=f"نصيحة سريعة: {lesson['title']}"
    )

    print("\n📤 Uploading to YouTube...")
    hashtags = lesson_content.get("hashtags", "#الذكاء_الاصطناعي #تعلم_البرمجة #تعلم_الذكاء_الاصطناعي")
    long_desc = f"هذا الفيديو جزء من سلسلة مطوري الذكاء الاصطناعي التي يقدمها {YOUR_NAME}.\n\nدرس اليوم: {lesson['title']}\n\n{hashtags}"
    long_tags = "الذكاء الاصطناعي, البرمجة, المطورون, التقنية, تعليم, " + lesson['title'].replace(" ", ", ")

    long_video_id = lesson.get('youtube_id')
    if long_video_id:
        print(f"ℹ️ Long video already uploaded: {long_video_id}. Skipping duplicate upload.")
    else:
        long_video_id = upload_to_youtube(
            long_video_path,
            lesson['title'],
            long_desc,
            long_tags,
            long_thumb_path
        )
        if long_video_id:
            lesson['youtube_id'] = long_video_id

    if long_video_id:
        facebook_long_id = upload_facebook_or_raise(
            long_video_path,
            lesson["title"],
            long_desc,
        )
        if facebook_long_id:
            lesson["facebook_id"] = facebook_long_id
        print("⏳ Waiting 30 seconds before uploading the short...")
        time.sleep(30)
        highlight = (lesson_content.get('short_form_highlight') or '').strip()
        if not highlight:
            highlight = f"نصيحة سريعة: {lesson['title']}"
        highlight = " ".join(highlight.split())
        short_suffix = " #مقاطع_قصيرة"
        short_title = f"{highlight[:100 - len(short_suffix)].rstrip()}{short_suffix}"
        if not short_title:
            short_title = f"نصيحة سريعة: {lesson['title']}"[:100].rstrip()
        short_desc = (f"{lesson_content['short_form_highlight']}\n\n"
                      f"شاهد الدرس الكامل مع {YOUR_NAME} هنا: https://www.youtube.com/watch?v={long_video_id}\n\n"
                      f"{hashtags}")
        short_video_id = upload_to_youtube(
            short_video_path,
            short_title.strip(),
            short_desc,
            "الذكاء الاصطناعي,مقاطع قصيرة,نصيحة تقنية",
            short_thumb_path,
        )
        if not short_video_id:
            raise RuntimeError("YouTube did not return an ID for the short video.")
        lesson["youtube_short_id"] = short_video_id
        facebook_short_id = upload_facebook_or_raise(
            short_video_path,
            short_title.strip(),
            short_desc,
        )
        if facebook_short_id:
            lesson["facebook_short_id"] = facebook_short_id
        return long_video_id
    return None


def main():
    print("🚀 Starting Autonomous AI Course Generator")
    print(f"📁 Current working dir: {os.getcwd()}")
    print(f"📁 OUTPUT_DIR: {OUTPUT_DIR.resolve()}")

    validate_runtime()
    run_failed = False
    try:
        OUTPUT_DIR.mkdir(exist_ok=True)
        print(f"📁 Created output folder: {OUTPUT_DIR.exists()}")
        plan = get_content_plan()
        pending = [(i, lesson) for i, lesson in enumerate(plan['lessons']) if lesson['status'] == 'pending']

        if not pending:
            print("🎉 All lessons produced! Generating new content plan to restart from scratch...")

            previous_titles = [lesson['title'] for lesson in plan['lessons']]
            new_plan = generate_curriculum(previous_titles=previous_titles)  # 🔁 Pass prior titles
            update_content_plan(new_plan)
            plan = new_plan
            pending = [(i, lesson) for i, lesson in enumerate(new_plan['lessons']) if lesson['status'] == 'pending']
            if not pending:
                print("⚠️ Curriculum generated but no valid lessons found.")
                return

        for lesson_index, lesson in pending[:LESSONS_PER_RUN]:
            try:
                video_id = produce_lesson_videos(lesson)
                if video_id:
                    for original_lesson in plan['lessons']:
                        if original_lesson['title'].strip().lower() == lesson['title'].strip().lower():
                            original_lesson['status'] = 'complete'
                            original_lesson['youtube_id'] = video_id
                            print(f"✅ Completed lesson: {lesson['title']}")
                            break
                    else:
                        print(f"⚠️ Could not find lesson in plan to mark as complete: {lesson['title']}")
                else:
                    print(f"⚠️ Upload failed: {lesson['title']}")
            except Exception as e:
                run_failed = True
                print(f"❌ Failed producing lesson: {lesson['title']}")
                traceback.print_exc()
            finally:
                update_content_plan(plan)
                print("📦 Content plan updated.")
                print(f"✅ Updated content plan for lesson: {lesson['title']}")
    except Exception as e:
        run_failed = True
        print("❌ Critical error in main()")
        traceback.print_exc()

    try:
        for file in OUTPUT_DIR.glob("*.wav"):
            file.unlink()
            print(f"🧹 Deleted: {file}")
    except Exception as e:
        print(f"⚠️ Could not clean up .wav files: {e}")

    if run_failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
