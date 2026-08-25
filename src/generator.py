import json
import os
from io import BytesIO
from pathlib import Path

import google.generativeai as genai
import arabic_reshaper
import asyncio
import edge_tts
import requests
from bidi.algorithm import get_display
from gtts import gTTS
from moviepy.config import change_settings
from moviepy.editor import AudioFileClip, CompositeAudioClip, ImageClip, VideoFileClip, concatenate_videoclips, vfx
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pydub import AudioSegment

ASSETS_PATH = Path("assets")
FONT_FILE = ASSETS_PATH / "fonts" / "arial.ttf"
BACKGROUND_MUSIC_PATH = ASSETS_PATH / "music" / "bg_music.mp3"
YOUR_NAME = "شياتانيا"
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
ARABIC_VOICE = os.getenv("ARABIC_VOICE", "ar-SA-HamedNeural")

if os.name == "posix" and Path("/usr/bin/convert").exists():
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})


def _model():
    api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("لم يتم ضبط GOOGLE_API_KEY. ضع مفتاح Gemini الحقيقي في الطرفية ثم أعد التشغيل.")
    if api_key in {"مفتاحك_الجديد", "your_api_key", "YOUR_API_KEY"} or not api_key.isascii():
        raise RuntimeError("قيمة GOOGLE_API_KEY غير صالحة. استبدل النص التجريبي بمفتاح Gemini حقيقي من Google AI Studio.")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(MODEL_NAME)


def _json_response(response):
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def generate_curriculum(previous_titles=None):
    history = ""
    if previous_titles:
        history = "العناوين السابقة:\n" + "\n".join(f"- {title}" for title in previous_titles)
    prompt = f"أنشئ منهجًا عربيًا بالكامل من 20 درسًا لسلسلة يوتيوب بعنوان قناة مطوري الذكاء الاصطناعي من {YOUR_NAME}. ابدأ بالمفاهيم للمبتدئين وتدرج إلى موضوعات الذكاء الاصطناعي المتقدمة. تجنب هذه العناوين السابقة:\n{history}\nأعد كائن JSON صحيحًا فقط يحتوي على قائمة lessons. يجب أن تكون قيم chapter وpart رقمية، وأن يكون title عربيًا بالكامل، وأن تكون status مساوية للنص pending وأن تكون youtube_id مساوية للقيمة null. لا تستخدم أي كلمات إنجليزية في العناوين أو المحتوى، باستثناء المصطلحات التقنية الشائعة عند الضرورة."
    curriculum = _json_response(_model().generate_content(prompt))
    if not isinstance(curriculum.get("lessons"), list) or not curriculum["lessons"]:
        raise ValueError("Gemini returned an invalid curriculum.")
    return curriculum


def generate_lesson_content(lesson_title):
    prompt = f"أنشئ درسًا عربيًا بالكامل عن الموضوع التالي: {lesson_title!r}. أعد JSON صحيحًا فقط يحتوي على long_form_slides (من 7 إلى 8 كائنات، لكل منها title وcontent بالعربية)، وshort_form_highlight (ملخص عربي جذاب من جملة أو جملتين)، وhashtags (من 5 إلى 7 وسوم عربية مفصولة بمسافات). لا تكتب أي شرح خارج JSON، ولا تستخدم الإنجليزية إلا داخل المصطلحات التقنية التي يصعب ترجمتها."
    content = _json_response(_model().generate_content(prompt))
    if not isinstance(content.get("long_form_slides"), list) or not content["long_form_slides"]:
        raise ValueError("Gemini returned no lesson slides.")
    return content


def text_to_speech(text, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_mp3 = output_path.with_name(output_path.stem + "_temp.mp3")
    wav_path = output_path.with_suffix(".wav")
    clean_text = str(text).replace("#", "").replace("*", "").strip()
    try:
        asyncio.run(edge_tts.Communicate(clean_text, ARABIC_VOICE).save(str(temporary_mp3)))
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
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        return None
    try:
        response = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": api_key}, params={"query": query, "per_page": 1, "orientation": "portrait" if video_type == "short" else "landscape"}, timeout=15)
        response.raise_for_status()
        photos = response.json().get("photos", [])
        if not photos:
            return None
        image_response = requests.get(photos[0]["src"]["large2x"], timeout=15)
        image_response.raise_for_status()
        return Image.open(BytesIO(image_response.content)).convert("RGBA")
    except requests.RequestException as error:
        print(f"Warning: Pexels unavailable, using fallback: {error}")
        return None


def get_pexels_video(query, video_type, output_path):
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        return None
    try:
        response = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 1, "orientation": "portrait" if video_type == "short" else "landscape"},
            timeout=15,
        )
        response.raise_for_status()
        videos = response.json().get("videos", [])
        if not videos:
            return None
        files = [file for file in videos[0].get("video_files", []) if file.get("link")]
        files.sort(key=lambda file: abs((file.get("width") or 0) - (1080 if video_type == "short" else 1920)))
        if not files:
            return None
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video_response = requests.get(files[0]["link"], timeout=60)
        video_response.raise_for_status()
        output_path.write_bytes(video_response.content)
        return output_path
    except requests.RequestException as error:
        print(f"Warning: Pexels video unavailable, using designed fallback: {error}")
        return None


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
        path = output_dir / f"thumbnail_{video_type}.png"
    else:
        path = output_dir / f"slide_{slide_number:02d}.png"
    image.save(path)
    return str(path)


def create_video(slide_paths, audio_paths, output_path, video_type):
    if not slide_paths or len(slide_paths) != len(audio_paths):
        raise ValueError("Every slide must have exactly one audio clip.")
    clips = []
    try:
        width, height = (1920, 1080) if video_type == "long" else (1080, 1920)
        for index, (slide_path, audio_path) in enumerate(zip(slide_paths, audio_paths)):
            audio = AudioFileClip(str(audio_path))
            duration = audio.duration + 0.5
            if Path(slide_path).suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}:
                source = VideoFileClip(str(slide_path)).without_audio()
                source = source.fx(vfx.loop, duration=duration) if source.duration < duration else source.subclip(0, duration)
                animated_slide = source.resize((width, height)).set_duration(duration).set_audio(audio)
            else:
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
        if BACKGROUND_MUSIC_PATH.exists():
            music = AudioFileClip(str(BACKGROUND_MUSIC_PATH)).volumex(0.15)
            music = music.fx(vfx.loop, duration=video.duration) if music.duration < video.duration else music.subclip(0, video.duration)
            video = video.set_audio(CompositeAudioClip([video.audio.volumex(1.2), music]))
        video.write_videofile(str(output_path), fps=24, codec="libx264", audio_codec="aac", audio_bitrate="192k", preset="medium", threads=4)
    finally:
        for clip in clips:
            clip.close()