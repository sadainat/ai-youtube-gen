# FILE: src/uploader.py
# This is the new, robust version that handles authentication correctly
# for both local use and GitHub Actions deployment.

import json
import os
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image

from src.config import PROJECT_ROOT

CLIENT_SECRETS_FILE = Path(
    os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", str(PROJECT_ROOT / "client_secrets.json"))
)
CREDENTIALS_FILE = Path(
    os.getenv("YOUTUBE_CREDENTIALS_FILE", str(PROJECT_ROOT / "credentials.json"))
)
YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v23.0").strip() or "v23.0"
if not META_GRAPH_VERSION.startswith("v"):
    META_GRAPH_VERSION = f"v{META_GRAPH_VERSION}"
META_GRAPH_HOST = os.getenv("META_GRAPH_HOST", "https://graph-video.facebook.com").rstrip("/")


def _write_credentials_from_environment():
    """Materialize GitHub Actions credentials only when no local file exists."""
    if CREDENTIALS_FILE.exists():
        return

    raw_credentials = os.getenv("YOUTUBE_CREDENTIALS_JSON", "").strip()
    if not raw_credentials:
        return

    try:
        credentials = json.loads(raw_credentials)
    except json.JSONDecodeError as error:
        raise ValueError("YOUTUBE_CREDENTIALS_JSON must contain valid JSON.") from error
    if not isinstance(credentials, dict):
        raise ValueError("YOUTUBE_CREDENTIALS_JSON must contain a JSON object.")

    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = CREDENTIALS_FILE.with_name(f".{CREDENTIALS_FILE.name}.tmp")
    temporary_file.write_text(json.dumps(credentials), encoding="utf-8")
    temporary_file.replace(CREDENTIALS_FILE)
    print(f"INFO: YouTube credentials restored from YOUTUBE_CREDENTIALS_JSON to {CREDENTIALS_FILE}")


def _raise_for_api_error(response, service_name):
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        detail = response.text.strip().replace("\\n", " ")[:500]
        message = f"{service_name} returned HTTP {response.status_code}"
        if detail:
            message += f": {detail}"
        raise requests.HTTPError(message, response=response) from error


def facebook_upload_configured():
    """Return whether Page credentials are present for a required upload."""
    return bool(
        os.getenv("FACEBOOK_PAGE_ID", "").strip()
        and os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    )


def _upload_to_vercel_blob(file_path):
    """Upload a file to Vercel Blob and return its public URL."""
    token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
    if not token:
        return None
    file_path = Path(file_path)
    with open(file_path, "rb") as f:
        response = requests.put(
            f"https://blob.vercel-storage.com/{file_path.name}",
            headers={
                "authorization": f"Bearer {token}",
                "x-content-type": "video/mp4",
            },
            data=f,
            timeout=300,
        )
    response.raise_for_status()
    return response.json().get("url")


def _delete_vercel_blob(url):
    """Delete a file from Vercel Blob after use."""
    token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
    if not token or not url:
        return
    try:
        requests.delete(
            "https://blob.vercel-storage.com/delete",
            headers={"authorization": f"Bearer {token}"},
            json={"urls": [url]},
            timeout=30,
        )
    except Exception:
        pass


def upload_to_instagram(video_path, caption):
    """Upload a video to Instagram as a Reel via Vercel Blob + Graph API."""
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "").strip()
    access_token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    if not account_id or not access_token:
        print("ℹ️ Instagram upload skipped: credentials are not configured.")
        return None

    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Instagram upload video not found: {video_path}")

    base_url = f"https://graph.facebook.com/{META_GRAPH_VERSION}"
    blob_url = None
    print(f"⬆️ Uploading '{video_path}' to Instagram...")
    try:
        # Step 1: Upload to Vercel Blob for public URL
        blob_url = _upload_to_vercel_blob(video_path)
        if not blob_url:
            print("❌ Instagram upload failed: could not get public video URL.")
            return None

        # Step 2: Create Instagram media container
        container_response = requests.post(
            f"{base_url}/{account_id}/media",
            data={
                "media_type": "REELS",
                "video_url": blob_url,
                "caption": caption,
                "access_token": access_token,
            },
            timeout=60,
        )
        _raise_for_api_error(container_response, "Instagram create container")
        container_id = container_response.json().get("id")
        if not container_id:
            raise RuntimeError("Instagram returned no container ID.")

        # Step 3: Wait for video processing
        import time
        for _ in range(12):
            time.sleep(10)
            status_response = requests.get(
                f"{base_url}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
                timeout=30,
            )
            status = status_response.json().get("status_code", "")
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise RuntimeError("Instagram video processing failed.")

        # Step 4: Publish the container
        publish_response = requests.post(
            f"{base_url}/{account_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=60,
        )
        _raise_for_api_error(publish_response, "Instagram publish")
        media_id = publish_response.json().get("id")
        print(f"✅ Instagram Reel uploaded successfully! Media ID: {media_id}")
        return media_id
    except Exception as error:
        print(f"❌ ERROR: Failed to upload to Instagram: {error}")
        return None
    finally:
        _delete_vercel_blob(blob_url)


def get_authenticated_service():
    """Return an authenticated YouTube Data API client."""
    _write_credentials_from_environment()
    credentials = None

    if CREDENTIALS_FILE.exists():
        print("INFO: Found existing credentials file.")
        credentials = Credentials.from_authorized_user_file(
            str(CREDENTIALS_FILE), YOUTUBE_UPLOAD_SCOPE
        )

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            print("INFO: Refreshing expired credentials...")
            credentials.refresh(Request())
        else:
            print("INFO: No valid credentials found. Starting new authentication flow...")
            if not CLIENT_SECRETS_FILE.exists():
                raise FileNotFoundError(
                    f"CRITICAL ERROR: {CLIENT_SECRETS_FILE} not found. "
                    "Please download it from Google Cloud Console."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRETS_FILE), scopes=YOUTUBE_UPLOAD_SCOPE
            )
            credentials = flow.run_local_server(port=0)

        CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_FILE.write_text(credentials.to_json(), encoding="utf-8")
        print(f"INFO: Credentials saved to {CREDENTIALS_FILE}")

    return build("youtube", "v3", credentials=credentials)


def _prepare_youtube_thumbnail(thumbnail_path):
    """Return a thumbnail path under YouTube's 2 MB upload limit."""
    thumbnail_path = Path(thumbnail_path)
    max_bytes = 1_900_000
    if thumbnail_path.stat().st_size <= max_bytes:
        return thumbnail_path, None

    compressed_path = thumbnail_path.with_name(f".{thumbnail_path.stem}_youtube.jpg")
    with Image.open(thumbnail_path) as source:
        source = source.convert("RGB")
        for max_dimension in (1920, 1280, 960, 768):
            candidate = source.copy()
            candidate.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
            for quality in (88, 78, 68, 58, 48, 40):
                candidate.save(
                    compressed_path,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                )
                if compressed_path.stat().st_size <= max_bytes:
                    return compressed_path, compressed_path
    compressed_path.unlink(missing_ok=True)
    raise ValueError(f"Could not compress thumbnail below {max_bytes} bytes.")


def upload_youtube_thumbnail(video_id, thumbnail_path, youtube_service=None):
    """Upload one thumbnail, compressing it before the YouTube API call."""
    thumbnail = Path(thumbnail_path)
    if not thumbnail.is_file():
        raise FileNotFoundError(f"YouTube thumbnail not found: {thumbnail}")

    thumbnail_upload_path, temporary_thumbnail = _prepare_youtube_thumbnail(thumbnail)
    try:
        thumbnail_mimetype = (
            "image/jpeg"
            if thumbnail_upload_path.suffix.lower() in {".jpg", ".jpeg"}
            else "image/png"
        )
        youtube = youtube_service or get_authenticated_service()
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(
                str(thumbnail_upload_path), mimetype=thumbnail_mimetype
            ),
        ).execute()
    finally:
        if temporary_thumbnail:
            temporary_thumbnail.unlink(missing_ok=True)


def upload_to_youtube(video_path, title, description, tags, thumbnail_path=None):
    """Upload an MP4 to YouTube with metadata and an optional thumbnail."""
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"YouTube upload video not found: {video_path}")
    if video_path.stat().st_size <= 0:
        raise ValueError(f"YouTube upload video is empty: {video_path}")

    print(f"⬆️ Uploading '{video_path}' to YouTube...")
    try:
        youtube = get_authenticated_service()
        tags_list = [tag.strip() for tag in str(tags).split(",") if tag.strip()]
        request_body = {
            "snippet": {
                "title": str(title).strip()[:100],
                "description": str(description).strip(),
                "tags": tags_list,
                "categoryId": "28",
            },
            "status": {
                "privacyStatus": os.getenv("YOUTUBE_PRIVACY_STATUS", "public").strip() or "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path), mimetype="video/mp4", chunksize=-1, resumable=True
        )
        request = youtube.videos().insert(
            part=",".join(request_body.keys()),
            body=request_body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%.")

        video_id = response.get("id")
        if not video_id:
            raise RuntimeError(f"YouTube returned no video ID: {response}")
        print(f"✅ Video uploaded successfully! Video ID: {video_id}")

        thumbnail = Path(thumbnail_path) if thumbnail_path else None
        if thumbnail and thumbnail.is_file():
            print(f"⬆️ Uploading thumbnail '{thumbnail}' for video ID: {video_id}...")
            try:
                upload_youtube_thumbnail(video_id, thumbnail, youtube_service=youtube)
                print("✅ Thumbnail uploaded successfully!")
            except Exception as error:
                print(f"❌ ERROR: Failed to upload thumbnail: {error}")
        else:
            print("⚠️ No thumbnail file found. Skipping thumbnail upload.")

        return video_id
    except Exception as error:
        print(f"❌ ERROR: Failed to upload to YouTube. {error}")
        raise


def upload_to_facebook(video_path, title, description):
    """Upload a video to a Facebook Page using the resumable Page API."""
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    access_token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not access_token:
        print("ℹ️ Facebook upload skipped: page credentials are not configured.")
        return None

    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Facebook upload video not found: {video_path}")
    file_size = video_path.stat().st_size
    if file_size <= 0:
        raise ValueError(f"Facebook upload video is empty: {video_path}")

    endpoint = f"{META_GRAPH_HOST}/{META_GRAPH_VERSION}/{page_id}/videos"
    print(f"⬆️ Uploading '{video_path}' to Facebook Page...")
    try:
        start_response = requests.post(
            endpoint,
            params={
                "access_token": access_token,
                "upload_phase": "start",
                "file_size": file_size,
            },
            timeout=60,
        )
        _raise_for_api_error(start_response, "Facebook start upload")
        session = start_response.json()
        upload_session_id = session["upload_session_id"]
        video_id = session.get("video_id")
        start_offset = int(session.get("start_offset", 0))
        end_offset = int(session.get("end_offset", file_size))
        if end_offset <= start_offset:
            end_offset = file_size

        with video_path.open("rb") as video_file:
            while start_offset < file_size:
                video_file.seek(start_offset)
                chunk = video_file.read(end_offset - start_offset)
                if not chunk:
                    raise RuntimeError("Facebook returned an empty upload chunk.")

                transfer_response = requests.post(
                    endpoint,
                    params={
                        "access_token": access_token,
                        "upload_phase": "transfer",
                        "upload_session_id": upload_session_id,
                        "start_offset": start_offset,
                    },
                    files={"video_file_chunk": (video_path.name, chunk, "video/mp4")},
                    timeout=1800,
                )
                _raise_for_api_error(transfer_response, "Facebook transfer upload")
                offsets = transfer_response.json()
                next_start = int(offsets.get("start_offset", file_size))
                next_end = int(offsets.get("end_offset", file_size))
                if next_start <= start_offset:
                    raise RuntimeError("Facebook did not advance the upload offset.")
                if next_start > file_size:
                    raise RuntimeError("Facebook returned an invalid upload offset.")
                start_offset = next_start
                end_offset = file_size if next_end <= start_offset else next_end

        finish_params = {
            "access_token": access_token,
            "upload_phase": "finish",
            "upload_session_id": upload_session_id,
            "title": title,
            "description": description,
            "published": "true",
        }
        if video_id:
            finish_params["video_id"] = video_id
        finish_response = requests.post(endpoint, params=finish_params, timeout=180)
        _raise_for_api_error(finish_response, "Facebook finish upload")
        result = finish_response.json()
        if result.get("success") is False:
            raise RuntimeError(f"Facebook rejected the video: {finish_response.text[:300]}")
        print(f"✅ Facebook video uploaded successfully! Video ID: {video_id or result.get('id')}")
        return video_id or result.get("id")
    except requests.RequestException as error:
        print(f"❌ ERROR: Failed to upload to Facebook Page: {error}")
        return None

