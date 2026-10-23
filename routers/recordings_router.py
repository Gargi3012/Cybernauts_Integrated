"""
routers/recordings_router.py
============================
FastAPI routes for Call Recordings:
- GET /api/recordings: List & filter recordings
- DELETE /api/recordings/{id}: Remove recording and clean disk
- POST /api/recordings/upload: Ingest WebRTC / LiveKit browser recordings
- POST /api/telephony/recording-callback: Webhook for Plivo carrier recordings
"""

import os
import uuid
import asyncio
import httpx
from typing import Optional
from fastapi import APIRouter, File, Form, UploadFile, Request, HTTPException, Query, BackgroundTasks
from loguru import logger

import recording_manager

router = APIRouter(tags=["recordings"])


async def download_remote_recording(remote_url: str, dest_path: str, session_id: str, db_path: Optional[str] = None):
    """Background helper to download external carrier MP3 and cache locally."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(remote_url)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(dest_path, "wb") as f:
                    f.write(resp.content)
                file_size_kb = max(1, len(resp.content) // 1024)
                rel_url = f"/static/recordings/{os.path.basename(dest_path)}"
                recording_manager.save_recording(
                    session_id=session_id,
                    channel="telephony",
                    file_path=rel_url,
                    file_size_kb=file_size_kb,
                    status="completed",
                    db_path=db_path
                )
                logger.info(f"Successfully cached carrier recording locally: {rel_url}")
    except Exception as e:
        logger.warning(f"Could not cache remote recording {remote_url} locally: {e}")


@router.get("/api/recordings")
async def list_recordings(
    channel: Optional[str] = Query(None, description="'all', 'telephony', or 'livekit'"),
    search: Optional[str] = Query(None, description="Search by lead name, phone, or session ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Retrieve call recordings with optional filtering."""
    try:
        recs = recording_manager.get_recordings(
            channel=channel,
            search=search,
            limit=limit,
            offset=offset
        )
        return {
            "status": "success",
            "count": len(recs),
            "recordings": recs
        }
    except Exception as e:
        logger.exception(f"Error fetching recordings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/recordings/{recording_id}")
async def remove_recording(recording_id: int):
    """Delete a recording entry and its local file if stored locally."""
    success = recording_manager.delete_recording(recording_id)
    if not success:
        raise HTTPException(status_code=404, detail="Recording not found")
    return {"status": "success", "message": "Recording deleted successfully"}


@router.post("/api/recordings/upload")
async def upload_browser_recording(
    audio_file: UploadFile = File(...),
    session_id: str = Form(...),
    channel: str = Form("livekit"),
    lead_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    call_id: Optional[str] = Form(None),
    lead_id: Optional[int] = Form(None),
    duration_seconds: int = Form(0)
):
    """
    Ingest audio recorded directly in the browser (e.g. LiveKit Web Audio mix).
    Saves file to static/recordings/ and records metadata in leads.db.
    """
    try:
        # Determine extension from original filename or content_type
        ext = ".webm"
        if audio_file.filename and "." in audio_file.filename:
            ext = "." + audio_file.filename.rsplit(".", 1)[1].lower()
        elif audio_file.content_type and "wav" in audio_file.content_type:
            ext = ".wav"
        elif audio_file.content_type and "mp3" in audio_file.content_type:
            ext = ".mp3"

        safe_session = "".join(c for c in session_id if c.isalnum() or c in "-_")
        unique_token = uuid.uuid4().hex[:6]
        filename = f"rec_{safe_session}_{unique_token}{ext}"
        target_path = os.path.join(recording_manager.RECORDINGS_DIR, filename)

        contents = await audio_file.read()
        with open(target_path, "wb") as f:
            f.write(contents)

        file_size_kb = max(1, len(contents) // 1024)
        rel_path = f"/static/recordings/{filename}"

        saved = recording_manager.save_recording(
            session_id=session_id,
            channel=channel,
            file_path=rel_path,
            lead_name=lead_name or "Web Prospect",
            phone_number=phone_number or "Browser Client",
            call_id=call_id,
            lead_id=lead_id,
            duration_seconds=duration_seconds,
            file_size_kb=file_size_kb,
            status="completed"
        )

        logger.info(f"Saved LiveKit recording: {rel_path} ({file_size_kb} KB, {duration_seconds}s)")
        return {
            "status": "success",
            "recording": saved
        }
    except Exception as e:
        logger.exception(f"Failed to upload browser recording: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/telephony/recording-callback")
@router.post("/plivo/recording-callback")
async def telephony_recording_callback(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Webhook callback received from Plivo when carrier-level recording completes.
    Stores metadata and initiates async local download of MP3.
    """
    try:
        form = {}
        try:
            form = await request.form()
        except Exception:
            pass

        record_url = form.get("RecordUrl") or form.get("record_url")
        call_uuid = form.get("CallUUID") or form.get("call_uuid")
        duration_str = form.get("RecordingDuration") or form.get("recording_duration") or "0"
        duration_seconds = int(float(duration_str)) if duration_str else 0

        # Query parameter overrides
        session_id = request.query_params.get("session_id") or call_uuid or f"plivo_{uuid.uuid4().hex[:8]}"
        lead_id = request.query_params.get("lead_id")
        lead_name = request.query_params.get("lead_name")
        phone_number = request.query_params.get("phone") or form.get("To") or form.get("From")

        int_lead_id = int(lead_id) if lead_id and lead_id.isdigit() else None

        logger.info(f"Plivo Recording Callback received: CallUUID={call_uuid}, RecordUrl={record_url}, Duration={duration_seconds}s")

        if not record_url:
            return {"status": "ignored", "reason": "No RecordUrl provided"}

        # Store with initial carrier URL
        saved = recording_manager.save_recording(
            session_id=session_id,
            channel="telephony",
            file_path=record_url,
            lead_name=lead_name or "Phone Prospect",
            phone_number=phone_number or "PSTN Call",
            call_id=call_uuid,
            lead_id=int_lead_id,
            duration_seconds=duration_seconds,
            status="completed"
        )

        # Trigger background download to local static/recordings/
        safe_session = "".join(c for c in session_id if c.isalnum() or c in "-_")
        local_filename = f"plivo_{safe_session}.mp3"
        local_dest = os.path.join(recording_manager.RECORDINGS_DIR, local_filename)
        background_tasks.add_task(download_remote_recording, record_url, local_dest, session_id)

        return {
            "status": "success",
            "recording_id": saved.get("id"),
            "session_id": session_id,
            "record_url": record_url
        }
    except Exception as e:
        logger.exception(f"Error handling Plivo recording callback: {e}")
        return {"status": "error", "detail": str(e)}
