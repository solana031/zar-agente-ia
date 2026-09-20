"""
ZAR v27.14 - YouTube publishing integration.

Additive integration for an existing Flask/ZAR application.
It supports:
- OAuth authorization using the existing Google OAuth client credentials.
- Reading the authenticated YouTube channel.
- Uploading a local video file as private/unlisted/public.
- Scheduling a video by supplying publishAt (YouTube requires privacyStatus=private).
- Updating a thumbnail when a local image is supplied.

Environment variables:
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
  GOOGLE_REDIRECT_URI   (optional; otherwise request host callback is used)
  ZAR_YOUTUBE_REDIRECT_PATH (default /youtube/callback)
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from datetime import datetime, timezone

from flask import Blueprint, request, redirect, session, jsonify, url_for

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
DEFAULT_REDIRECT_PATH = "/youtube/callback"

youtube_bp = Blueprint("youtube_publish", __name__, url_prefix="/youtube")


def _credentials():
    try:
        from google.oauth2.credentials import Credentials
        return Credentials
    except Exception as exc:
        raise RuntimeError(
            "Faltan dependencias de Google OAuth. Instala google-auth y google-auth-oauthlib."
        ) from exc


def _flow(redirect_uri: str):
    try:
        from google_auth_oauthlib.flow import Flow
    except Exception as exc:
        raise RuntimeError(
            "Falta google-auth-oauthlib en requirements.txt."
        ) from exc

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Configura GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en Railway."
        )

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def _redirect_uri():
    configured = os.getenv("GOOGLE_REDIRECT_URI")
    if configured:
        return configured
    path = os.getenv("ZAR_YOUTUBE_REDIRECT_PATH", DEFAULT_REDIRECT_PATH)
    return request.host_url.rstrip("/") + path


def _get_creds():
    token = session.get("youtube_credentials")
    if not token:
        return None
    Credentials = _credentials()
    return Credentials.from_authorized_user_info(token, SCOPES)


def _save_creds(creds):
    session["youtube_credentials"] = json.loads(creds.to_json())
    session.modified = True


def _youtube_service(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


@youtube_bp.get("/connect")
def connect():
    flow = _flow(_redirect_uri())
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["youtube_oauth_state"] = state
    return redirect(auth_url)


@youtube_bp.get("/callback")
def callback():
    state = session.get("youtube_oauth_state")
    flow = _flow(_redirect_uri())
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    _save_creds(creds)
    session.pop("youtube_oauth_state", None)
    return redirect("/?youtube=connected")


@youtube_bp.get("/status")
def status():
    creds = _get_creds()
    if not creds:
        return jsonify({"connected": False})
    try:
        service = _youtube_service(creds)
        response = service.channels().list(part="snippet,contentDetails", mine=True).execute()
        items = response.get("items", [])
        if not items:
            return jsonify({"connected": True, "channel": None})
        ch = items[0]
        return jsonify({
            "connected": True,
            "channel": {
                "id": ch["id"],
                "title": ch["snippet"]["title"],
                "thumbnail": ch["snippet"]["thumbnails"].get("default", {}).get("url"),
            }
        })
    except Exception as exc:
        return jsonify({"connected": False, "error": str(exc)}), 401


@youtube_bp.post("/upload")
def upload():
    """
    Expects multipart/form-data:
      video: local video file
      title, description, privacyStatus
      publishAt (optional ISO 8601 UTC, e.g. 2026-09-13T18:00:00Z)
      thumbnail (optional image)
    """
    creds = _get_creds()
    if not creds:
        return jsonify({"ok": False, "error": "YouTube no está conectado."}), 401

    video = request.files.get("video")
    if not video:
        return jsonify({"ok": False, "error": "Falta el archivo de vídeo."}), 400

    title = (request.form.get("title") or "Vídeo de ZAR").strip()
    description = request.form.get("description") or ""
    privacy = (request.form.get("privacyStatus") or "private").lower()
    publish_at = (request.form.get("publishAt") or "").strip() or None

    if privacy not in {"private", "unlisted", "public"}:
        return jsonify({"ok": False, "error": "privacyStatus inválido."}), 400

    # A scheduled upload must initially be private and include publishAt.
    if publish_at:
        privacy = "private"
        try:
            dt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            publish_at = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            return jsonify({"ok": False, "error": "publishAt debe ser ISO 8601."}), 400

    temp_dir = Path(os.getenv("ZAR_UPLOAD_DIR", "/tmp/zar_youtube"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    video_path = temp_dir / video.filename
    video.save(video_path)

    try:
        from googleapiclient.http import MediaFileUpload

        body = {
            "snippet": {
                "title": title,
                "description": description,
            },
            "status": {
                "privacyStatus": privacy,
            },
        }
        if publish_at:
            body["status"]["publishAt"] = publish_at

        service = _youtube_service(creds)
        request_upload = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=MediaFileUpload(
                str(video_path),
                chunksize=8 * 1024 * 1024,
                resumable=True,
            ),
        )
        result = None
        while result is None:
            _, result = request_upload.next_chunk()

        video_id = result.get("id")
        thumb = request.files.get("thumbnail")
        thumb_path = None
        if thumb and video_id:
            thumb_path = temp_dir / ("thumb_" + thumb.filename)
            thumb.save(thumb_path)
            service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumb_path))
            ).execute()

        return jsonify({
            "ok": True,
            "videoId": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
            "privacyStatus": body["status"]["privacyStatus"],
            "publishAt": publish_at,
        })
    finally:
        try:
            video_path.unlink(missing_ok=True)
        except Exception:
            pass


def register_youtube(app):
    """Register the blueprint. Safe to call once."""
    if "youtube_publish" not in app.blueprints:
        app.register_blueprint(youtube_bp)
