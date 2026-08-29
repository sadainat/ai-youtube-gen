import asyncio
import json
import os
import random
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import arabic_reshaper
import edge_tts
import requests
from google import genai
from google.genai import types
from bidi.algorithm import get_display
from gtts import gTTS
from moviepy.config import change_settings
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
    vfx,
)
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pydub import AudioSegment

from src.config import PROJECT_ROOT, REQUIRE_REAL_VIDEO

ASSETS_PATH = PROJECT_ROOT / "assets"
FONT_FILE = ASSETS_PATH / "fonts" / "arial.ttf"
BACKGROUND_MUSIC_PATH = ASSETS_PATH / "music" / "bg_music.mp3"
YOUR_NAME = ""
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip() or "gemini-3.6-flash"
ARABIC_VOICE = os.getenv("ARABIC_VOICE", "ar-SA-HamedNeural").strip() or "ar-SA-HamedNeural"
ARABIC_VOICES = [
    "ar-SA-HamedNeural",
    "ar-SA-ZariyahNeural",
    "ar-EG-ShakirNeural",
    "ar-EG-SalmaNeural",
    "ar-AE-HamdanNeural",
    "ar-AE-FatimaNeural",
    "ar-KW-FahedNeural",
    "ar-KW-NouraNeural",
]
_GEMINI_CLIENT = None

if os.name == "posix" and Path("/usr/bin/convert").exists():
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})


def _model():
    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is not None:
        return _GEMINI_CLIENT

    api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("لم يتم ضبط GOOGLE_API_KEY. ضع مفتاح Gemini الحقيقي في الطرفية ثم أعد التشغيل.")
    if api_key in {"مفتاحك_الجديد", "your_api_key", "YOUR_API_KEY"} or not api_key.isascii():
        raise RuntimeError("قيمة GOOGLE_API_KEY غير صالحة. استبدل النص التجريبي بمفتاح Gemini حقيقي من Google AI Studio.")
    _GEMINI_CLIENT = genai.Client(api_key=api_key)
    return _GEMINI_CLIENT


def _generate_json(prompt):
    response = _model().models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("Gemini returned invalid JSON.") from error


CATEGORIES = [
    "قصص تاريخية وحضارات",
    "قصص إسلامية وأنبياء",
    "أسرار وغموض وحقائق مذهلة",
    "نصائح مالية وتطوير ذات",
    "حقائق عن دول وشعوب",
]


def generate_curriculum(previous_titles=None):
    history = ""
    if previous_titles:
        history = "العناوين السابقة:\n" + "\n".join(f"- {title}" for title in previous_titles)
    categories_str = "\n".join(f"- {c}" for c in CATEGORIES)
    prompt = f"""أنشئ منهجًا عربيًا من 20 حلقة لقناة يوتيوب عربية متنوعة تقدمها {YOUR_NAME}.
وزّع الحلقات بالتساوي بين هذه المحاور بالتناوب:
{categories_str}
اجعل العناوين مثيرة وجذابة وتشوّق المشاهد. تجنب هذه العناوين السابقة:
{history}
أعد كائن JSON صحيحًا فقط يحتوي على قائمة lessons. يجب أن تكون قيم chapter وpart رقمية، وأن يكون title عربيًا بالكامل، وأن تكون status مساوية للنص pending وأن تكون youtube_id مساوية للقيمة null."""
    curriculum = _generate_json(prompt)
    lessons = curriculum.get("lessons") if isinstance(curriculum, dict) else None
    if not isinstance(lessons, list) or not lessons:
        raise ValueError("Gemini returned an invalid curriculum.")
    for lesson in lessons:
        if not isinstance(lesson, dict) or not str(lesson.get("title", "")).strip():
            raise ValueError("Gemini returned a lesson without a title.")
        if lesson.get("status") != "pending" or lesson.get("youtube_id") is not None:
            raise ValueError("Gemini returned a lesson with invalid upload state.")
    return curriculum


def _validate_generated_content(content):
    slides = content.get("long_form_slides") if isinstance(content, dict) else None
    if not isinstance(slides, list) or not slides:
        raise ValueError("Gemini returned no long-form slides.")
    if any(
        not isinstance(slide, dict)
        or not str(slide.get("title", "")).strip()
        or not str(slide.get("content", "")).strip()
        for slide in slides
    ):
        raise ValueError("Gemini returned an invalid slide.")
    if not str(content.get("short_form_highlight", "")).strip():
        raise ValueError("Gemini returned no short-form highlight.")
    return content


def generate_lesson_content(lesson_title):
    prompt = f"""أنشئ حلقة عربية كاملة ومشوّقة عن الموضوع التالي: {lesson_title!r}.
اجعل الأسلوب سردياً جذاباً يشوّق المشاهد ويجعله يكمل الفيديو.
أعد JSON صحيحًا فقط يحتوي على:
- long_form_slides: من 7 إلى 8 كائنات، لكل منها title وcontent بالعربية وsearch_query كلمة بحث إنجليزية واحدة أو اثنتين مناسبة للبحث عن فيديو خلفية
- short_form_highlight: ملخص عربي جذاب من جملة أو جملتين
- hashtags: من 5 إلى 7 وسوم عربية مفصولة بمسافات
لا تكتب أي شرح خارج JSON."""
    return _validate_generated_content(_generate_json(prompt))


def generate_story_content(story_title):
    prompt = f"اكتب قصة عربية تعليمية خيالية ومؤثرة بعنوان {story_title!r} لقناة مطوري الذكاء الاصطناعي. اجعل القصة مناسبة للعائلة، وبها بداية ومشكلة ومحاولات وفشل وتعلم وحل ونهاية ملهمة. اشرح من خلال الأحداث كيف يتعلم الإنسان أو الروبوت من الأخطاء، من دون ادعاء أن الأحداث حقيقية. أعد JSON صحيحًا فقط يحتوي على long_form_slides (من 7 إلى 8 كائنات، لكل منها title وcontent بالعربية، وكل شريحة مشهد متتابع قابل للسرد الصوتي)، وshort_form_highlight (ملخص عربي جذاب من جملة أو جملتين يصلح لفيديو قصير)، وhashtags (من 5 إلى 7 وسوم عربية مفصولة بمسافات). لا تكتب أي شرح خارج JSON، ولا تستخدم الإنجليزية إلا داخل المصطلحات التقنية التي يصعب ترجمتها."
    return _validate_generated_content(_generate_json(prompt))


def text_to_speech(text, output_path, voice=None):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_mp3 = output_path.with_name(output_path.stem + "_temp.mp3")
    wav_path = output_path.with_suffix(".wav")
    clean_text = str(text).replace("#", "").replace("*", "").strip()
    selected_voice = voice or ARABIC_VOICE
    try:
        asyncio.run(edge_tts.Communicate(clean_text, selected_voice).save(str(temporary_mp3)))
        AudioSegment.from_mp3(temporary_mp3).export(wav_path, format="wav", codec="pcm_s16le")
        return wav_path
    except Exception as error:
        print(f"Warning: Gulf neural voice unavailable, using Arabic fallback: {error}")
        gTTS(text=clean_text, lang="ar", slow=False).save(str(temporary_mp3))
        AudioSegment.from_mp3(temporary_mp3).export(wav_path, format="wav", codec="pcm_s16le")
        return wav_path
    finally:
        if temporary_mp3.exists():
            temporary_mp3.unlink()


def get_pexels_image(query, video_type):
    api_key = (os.getenv("PEXELS_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        response = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={
                "query": query,
                "per_page": 1,
                "orientation": "portrait" if video_type == "short" else "landscape",
            },
            timeout=15,
        )
        response.raise_for_status()
        photos = response.json().get("photos", [])
        if not photos:
            return None
        image_response = requests.get(photos[0]["src"]["large2x"], timeout=15)
        image_response.raise_for_status()
        return Image.open(BytesIO(image_response.content)).convert("RGBA")
    except (requests.RequestException, OSError, ValueError, KeyError) as error:
        print(f"Warning: Pexels image unavailable, using fallback: {error}")
        return None


def _is_valid_video(path):
    """Return whether ffprobe can find a video stream in ``path``."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "video" in result.stdout.lower().split()


def get_archive_video(query, output_path):
    """Download a free Public Domain video from Internet Archive as fallback."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"{query} mediatype:movies",
                "fl": "identifier",
                "rows": 5,
                "output": "json",
            },
            timeout=15,
        )
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])
        for doc in docs:
            identifier = doc.get("identifier")
            if not identifier:
                continue
            meta = requests.get(f"https://archive.org/metadata/{identifier}", timeout=15)
            meta.raise_for_status()
            files = meta.json().get("files", [])
            mp4_files = [f for f in files if f.get("name", "").endswith(".mp4")]
            if not mp4_files:
                continue
            url = f"https://archive.org/download/{identifier}/{mp4_files[0]['name']}"
            video_response = requests.get(url, timeout=120, stream=True)
            video_response.raise_for_status()
            temporary_path = output_path.with_name(f".{output_path.name}.part")
            try:
                with open(temporary_path, "wb") as f:
                    for chunk in video_response.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                if not _is_valid_video(temporary_path):
                    continue
                temporary_path.replace(output_path)
                print(f"✅ Internet Archive video downloaded: {identifier}")
                return output_path
            finally:
                temporary_path.unlink(missing_ok=True)
    except (requests.RequestException, OSError, ValueError, KeyError) as error:
        print(f"Warning: Internet Archive video unavailable: {error}")
    return None


def get_pexels_video(query, video_type, output_path):
    """Download and validate a real MP4 clip from Pexels, with Internet Archive fallback."""
    api_key = (os.getenv("PEXELS_API_KEY") or "").strip()
    if not api_key:
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    orientation = "portrait" if video_type == "short" else "landscape"
    target_width = 1080 if video_type == "short" else 1920
    search_queries = []
    for search_query in (str(query).strip(), "artificial intelligence technology"):
        if search_query and search_query not in search_queries:
            search_queries.append(search_query)

    last_error = None
    for search_query in search_queries:
        try:
            response = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": api_key},
                params={
                    "query": search_query,
                    "per_page": 1,
                    "orientation": orientation,
                },
                timeout=15,
            )
            response.raise_for_status()
            videos = response.json().get("videos", [])
            if not videos:
                continue

            files = [
                file
                for file in videos[0].get("video_files", [])
                if file.get("link")
                and file.get("file_type", "video/mp4") == "video/mp4"
            ]
            files.sort(key=lambda file: abs((file.get("width") or 0) - target_width))
            if not files:
                continue

            video_response = requests.get(files[0]["link"], timeout=120)
            video_response.raise_for_status()
            if not video_response.content:
                continue

            temporary_path = output_path.with_name(f".{output_path.name}.part")
            try:
                temporary_path.write_bytes(video_response.content)
                if not _is_valid_video(temporary_path):
                    continue
                temporary_path.replace(output_path)
                return output_path
            finally:
                temporary_path.unlink(missing_ok=True)
        except (requests.RequestException, OSError, ValueError, KeyError) as error:
            last_error = error

    if last_error:
        print(f"Warning: Pexels video unavailable: {last_error}")

    # Fallback to Internet Archive
    archive_query = search_queries[0] if search_queries else "technology"
    print(f"🔄 Trying Internet Archive for: {archive_query}")
    return get_archive_video(archive_query, output_path)


def _font(size):
    try:
        return ImageFont.truetype(str(FONT_FILE), size)
    except OSError:
        return ImageFont.load_default()


def _rtl(text):
    return get_display(arabic_reshaper.reshape(str(text)))


def _wrap(draw, text, font, max_width):
    lines, current = [], ""
    for word in str(text).split():
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return [_rtl(line) for line in (lines + [current] if current else [""])]


def _fallback_background(width, height, title):
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    seed = sum(ord(char) for char in title) % 80
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = (10 + int(18 * ratio), 34 + int(35 * ratio), 62 + int(70 * ratio), 255)
        for x in range(width):
            pixels[x, y] = color
    draw = ImageDraw.Draw(image)
    accent = (25 + seed, 145, 190, 150)
    for offset in range(-height, width, 150):
        draw.line((offset, height, offset + height, 0), fill=accent, width=5)
    for radius in range(80, min(width, height), 180):
        draw.ellipse((width - radius * 2 - 80, 90, width - 80, 90 + radius * 2), outline=(70, 210, 220, 80), width=4)
    draw.rectangle((int(width * 0.06), int(height * 0.1), int(width * 0.94), int(height * 0.9)), outline=(255, 255, 255, 35), width=3)
    return image


YOUTUBE_MAX_THUMBNAIL_BYTES = 1_900_000


def _save_thumbnail(image, path):
    """Save a readable JPEG small enough for YouTube's thumbnail limit."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    source = image.convert("RGB")
    for max_dimension in (1920, 1280, 960, 768):
        candidate = source.copy()
        candidate.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
        for quality in (88, 78, 68, 58, 48, 40):
            candidate.save(
                path,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
            if path.stat().st_size <= YOUTUBE_MAX_THUMBNAIL_BYTES:
                return path
    raise ValueError(f"Could not compress thumbnail below {YOUTUBE_MAX_THUMBNAIL_BYTES} bytes: {path}")


def generate_visuals(output_dir, video_type, slide_content=None, thumbnail_title=None, slide_number=0, total_slides=0):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    is_thumbnail = thumbnail_title is not None
    width, height = (1920, 1080) if video_type == "long" else (1080, 1920)
    title = thumbnail_title if is_thumbnail else (slide_content or {}).get("title", "")
    background = get_pexels_image(title, video_type) or _fallback_background(width, height, title)
    if is_thumbnail:
        image = background.resize((width, height)).convert("RGB")
    else:
        image = Image.alpha_composite(background.resize((width, height)).filter(ImageFilter.GaussianBlur(4)), Image.new("RGBA", (width, height), (0, 0, 0, 145))).convert("RGB")
    draw = ImageDraw.Draw(image)
    title_font, content_font, footer_font = _font(80 if video_type == "long" else 90), _font(45 if video_type == "long" else 55), _font(25 if video_type == "long" else 35)
    header_height = int(height * 0.2)
    if not is_thumbnail:
        draw.rectangle((0, 0, width, header_height), fill=(25, 40, 65))
    if not is_thumbnail:
        title_lines = _wrap(draw, title, title_font, width * 0.86)
        y = (header_height - len(title_lines) * 90) / 2
        for line in title_lines:
            box = draw.textbbox((0, 0), line, font=title_font)
            draw.text(((width - box[2] + box[0]) / 2, y), line, font=title_font, fill="white")
            y += 90
    if not is_thumbnail:
        y = header_height + 100
        for line in _wrap(draw, (slide_content or {}).get("content", ""), content_font, width * 0.84):
            box = draw.textbbox((0, 0), line, font=content_font)
            draw.text(((width - box[2] + box[0]) / 2, y), line, font=content_font, fill=(230, 230, 230))
            y += 60
        footer_height = int(height * 0.06)
        draw.rectangle((0, height - footer_height, width, height), fill=(25, 40, 65))
        footer_text = _rtl(f"مطورو الذكاء الاصطناعي من {YOUR_NAME}")
        draw.text((40, height - footer_height + 12), footer_text, font=footer_font, fill=(180, 180, 180))
        if total_slides:
            marker = _rtl(f"الشريحة {slide_number} من {total_slides}")
            box = draw.textbbox((0, 0), marker, font=footer_font)
            draw.text((width - box[2] - 40, height - footer_height + 12), marker, font=footer_font, fill=(180, 180, 180))
    if is_thumbnail:
        path = _save_thumbnail(image, output_dir / f"thumbnail_{video_type}.jpg")
    else:
        path = output_dir / f"slide_{slide_number:02d}.png"
        image.save(path)
    return str(path)


def create_video(slide_paths, audio_paths, output_path, video_type):
    """Combine real source clips (or explicit image fallbacks) with narration."""
    if not slide_paths or len(slide_paths) != len(audio_paths):
        raise ValueError("Every slide must have exactly one audio clip.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clips = []
    sources = []
    audio_clips = []
    video = None
    music = None
    try:
        width, height = (1920, 1080) if video_type == "long" else (1080, 1920)
        for index, (slide_path, audio_path) in enumerate(zip(slide_paths, audio_paths)):
            slide_path = Path(slide_path)
            audio_path = Path(audio_path)
            if not slide_path.is_file():
                raise FileNotFoundError(f"Slide media not found: {slide_path}")
            if not audio_path.is_file():
                raise FileNotFoundError(f"Narration audio not found: {audio_path}")

            audio = AudioFileClip(str(audio_path))
            audio_clips.append(audio)
            duration = audio.duration + 0.5
            if duration <= 0:
                raise ValueError(f"Narration audio is empty: {audio_path}")

            is_video_file = slide_path.suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}
            if is_video_file:
                if not _is_valid_video(slide_path):
                    raise ValueError(f"Downloaded media is not a valid video: {slide_path}")
                source = VideoFileClip(str(slide_path)).without_audio()
                sources.append(source)
                if source.duration < duration:
                    animated_slide = source.fx(vfx.loop, duration=duration)
                else:
                    animated_slide = source.subclip(0, duration)
                animated_slide = animated_slide.resize((width, height)).set_duration(duration).set_audio(audio)
            else:
                if REQUIRE_REAL_VIDEO:
                    raise ValueError(f"Image fallback is disabled for real-video mode: {slide_path}")
                direction = 1 if index % 2 == 0 else -1
                animated_slide = (
                    ImageClip(str(slide_path))
                    .set_duration(duration)
                    .resize(lambda time: 1.0 + 0.06 * time / duration)
                    .set_position(lambda time: (direction * 12 * time / duration, 0))
                    .set_audio(audio)
                    .fadein(0.3)
                    .fadeout(0.3)
                )
            clips.append(animated_slide)

        video = concatenate_videoclips(clips, method="compose")
        if BACKGROUND_MUSIC_PATH.is_file() and video.audio is not None:
            music = AudioFileClip(str(BACKGROUND_MUSIC_PATH)).volumex(0.15)
            music = music.fx(vfx.loop, duration=video.duration) if music.duration < video.duration else music.subclip(0, video.duration)
            video = video.set_audio(CompositeAudioClip([video.audio.volumex(1.2), music]))
        video.write_videofile(
            str(output_path),
            fps=24,
            codec="libx264",
            audio_codec="aac",
            audio_bitrate="192k",
            preset="medium",
            threads=4,
        )
    finally:
        if video is not None:
            video.close()
        if music is not None:
            music.close()
        for clip in clips:
            clip.close()
        for source in sources:
            source.close()
        for audio in audio_clips:
            audio.close()