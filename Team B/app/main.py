"""
Real-Time Voice Pipeline — Unified Entry Point

Supports Dual-Transport architecture:
1. LiveKit (WebRTC) for browser testing
2. Plivo (Telephony) for outbound and inbound phone calls

Usage:
    python -m app.main
    (The app automatically launches FastAPI for Plivo WebSockets and LiveKit endpoints).
"""

import asyncio
import uuid
import sys
import os
import ssl
from typing import Optional, Dict, Any, List, Union
import certifi
from xml.sax.saxutils import escape as xml_escape

os.environ["SSL_CERT_FILE"] = certifi.where()
ssl._create_default_https_context = ssl._create_unverified_context

from loguru import logger
logger.add("server_logs.txt", rotation="10 MB")
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect

from app.config import DAILY_ROOM_URL, LIVEKIT_URL, BOT_NAME, TRANSPORT_MODE
from app.conversation.state_machine import ConversationStateMachine
from app.conversation.transitions import ConversationState
from app.events.bus import EventBus
from app.events.event_types import SessionCreated, SessionClosed
from app.pipeline.factory import PipelineFactory
from app.session.manager import SessionManager
from app.session.state import SessionState

from app.adapters.pipecat.factory import PipecatFactory
from app.adapters.pipecat.transport import PlivoTransportAdapter


import time

# ── FastAPI App for Plivo & LiveKit ────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware
from app.routers import livekit_router
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

APP_STATE = {"is_ready": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB on startup with non-blocking 0.5s timeout
    logger.info("Initializing database connection pool...")
    from app.db.connection import db_manager
    try:
        db_manager.init_db()
        async def prewarm():
            async with db_manager.get_session() as db:
                from sqlalchemy import text
                await db.execute(text("SELECT 1"))
        await asyncio.wait_for(prewarm(), timeout=0.5)
        logger.info("Database connection pool initialized successfully.")
    except Exception as e:
        logger.warning(f"Database pre-warm startup notice (degrading gracefully): {e}")

    # Ensure all database tables exist
    try:
        from app.db.base import Base
        import app.db.models
        async def create_schemas():
            async with db_manager._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        await asyncio.wait_for(create_schemas(), timeout=0.5)
    except Exception as schema_err:
        logger.warning(f"Schema creation notice: {schema_err}")

    # Seed default admin user
    try:
        from app.services.auth_service import seed_default_user_if_empty
        async def seed():
            async with db_manager.get_session() as db:
                await seed_default_user_if_empty(db)
        await asyncio.wait_for(seed(), timeout=0.5)
    except Exception:
        pass

    # Pre-load FAQ context cache on startup
    try:
        from app.llm.company_faq import refresh_faq_cache
        await asyncio.wait_for(refresh_faq_cache(), timeout=0.5)
    except Exception:
        pass

    # Mark as ready immediately so FastAPI serves requests instantly
    APP_STATE["is_ready"] = True
    logger.info("FastAPI backend marked READY instantly.")
    
    async def stale_session_cleanup_task():
        import asyncio
        from sqlalchemy import text
        from app.db.connection import db_manager
        while APP_STATE.get("is_ready", False):
            try:
                async with db_manager.get_session() as db:
                    # Clean up orphaned Plivo stream claims older than 2 hours
                    await db.execute(text("DELETE FROM active_streams WHERE started_at < NOW() - INTERVAL '2 hours'"))
            except Exception as e:
                logger.error(f"Stale session cleanup task failed: {e}")
            await asyncio.sleep(600)  # Run every 10 minutes

    # Start cleanup task in the background
    cleanup_task = asyncio.create_task(stale_session_cleanup_task())
    
    yield
    
    logger.info("Shutting down database connection pool...")
    APP_STATE["is_ready"] = False
    
    # Cancel the cleanup task
    if 'cleanup_task' in locals():
        cleanup_task.cancel()
        
    await db_manager.close()

app = FastAPI(lifespan=lifespan, root_path=os.getenv("ROOT_PATH", ""))

from fastapi.responses import FileResponse, RedirectResponse

@app.get("/")
@app.get("/voice/frontend/index.html")
@app.get("/voice/frontend/")
@app.get("/voice/frontend")
@app.get("/voice")
@app.get("/voice/")
@app.get("/frontend")
@app.get("/frontend/")
@app.get("/frontend/index.html")
def root_redirect():
    return RedirectResponse(url="/", status_code=302)

@app.get("/health")
def health_check():
    """Backend readiness verification before accepting requests."""
    if APP_STATE.get("is_ready"):
        return {"status": "ok"}
    raise HTTPException(status_code=503, detail="Service not ready")

env_origins = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [origin.strip() for origin in env_origins.split(",") if origin.strip()]

if os.getenv("ENVIRONMENT", "development").lower() == "development":
    allowed_origins.extend([
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ])

if not allowed_origins:
    logger.warning("No ALLOWED_ORIGINS set in environment. Restricting to strict localhost.")
    allowed_origins = ["http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(livekit_router.router)

@app.api_route("/inbound-call", methods=["GET", "POST"])
@app.api_route("/plivo/incoming", methods=["GET", "POST"])
async def handle_inbound_call(request: Request):
    """Plivo webhook endpoint. Returns Plivo XML <Stream> to connect to our WebSocket."""
    webhook_processing_start = time.perf_counter()
    logger.info("Incoming Plivo call webhook received")
    
    # ── Backend Readiness ──
    if not APP_STATE.get("is_ready"):
        logger.warning("Incoming Plivo call rejected: Backend not ready.")
        raise HTTPException(status_code=503, detail="Service not ready")
        
    form_data = {}
    if request.method == "POST":
        try:
            form_data = dict(await request.form())
        except Exception:
            try:
                form_data = await request.json()
            except Exception:
                form_data = {}
    
    # ── Security: Plivo Signature Validation ───────────────────────────
    from app.config import PLIVO_AUTH_TOKEN
    import os
    
    auth_token = PLIVO_AUTH_TOKEN or os.getenv("PLIVO_AUTH_TOKEN", "")
    signature = request.headers.get("X-Plivo-Signature-V2") or request.headers.get("X-Plivo-Signature-V3") or request.headers.get("X-Plivo-Signature")
    nonce = request.headers.get("X-Plivo-Signature-V2-Nonce") or request.headers.get("X-Plivo-Signature-V3-Nonce") or ""
    
    if signature and auth_token and not auth_token.startswith("dummy_"):
        try:
            from plivo.utils import validate_signature
            req_url = str(request.url)
            is_valid = validate_signature(req_url, nonce, signature, auth_token)
            if not is_valid:
                if os.getenv("ENVIRONMENT", "development").lower() == "development":
                    logger.warning("SECURITY: Invalid Plivo signature. Bypassing in development mode.")
                else:
                    logger.warning("SECURITY: Invalid Plivo signature. Rejecting request.")
                    raise HTTPException(status_code=403, detail="Forbidden: Invalid Plivo Signature")
        except Exception as sig_err:
            logger.warning(f"Plivo signature validation check skipped/errored: {sig_err}")
    elif os.getenv("ENVIRONMENT", "development").lower() != "development" and auth_token and not auth_token.startswith("dummy_"):
        logger.warning("SECURITY: Missing Plivo signature in production request.")
        
    # Extract call identifiers and lead parameters
    call_uuid = form_data.get("CallUUID") or request.query_params.get("CallUUID") or form_data.get("call_uuid") or request.query_params.get("call_uuid") or ""
    phone_number = form_data.get("To") or request.query_params.get("To") or form_data.get("From") or request.query_params.get("From") or "unknown_client"
    lead_id = form_data.get("lead_id") or request.query_params.get("lead_id") or ""
    domain = form_data.get("domain") or request.query_params.get("domain") or ""
    session_id = form_data.get("session_id") or request.query_params.get("session_id") or ""
    dispatch_id = form_data.get("dispatch_id") or request.query_params.get("dispatch_id") or ""
    
    import urllib.parse
    
    # Resolve the WebSocket stream URL for Plivo media streaming instantly (<5ms)
    client_id_str = ""
    previous_summary = ""

    # Resolve the WebSocket stream URL for Plivo media streaming
    public_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if public_url:
        stream_base = public_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
    else:
        host = request.headers.get("host", "localhost:8000")
        scheme = "wss" if "ngrok" in host or request.headers.get("x-forwarded-proto") == "https" else "ws"
        stream_base = f"{scheme}://{host}/ws"
        
    query_params = []
    if phone_number:
        query_params.append(f"phone={urllib.parse.quote(phone_number)}")
    if lead_id:
        query_params.append(f"lead_id={urllib.parse.quote(lead_id)}")
    if domain:
        query_params.append(f"domain={urllib.parse.quote(domain)}")
    if call_uuid:
        query_params.append(f"call_uuid={urllib.parse.quote(call_uuid)}")
    if client_id_str:
        query_params.append(f"client_id={urllib.parse.quote(client_id_str)}")
    if session_id:
        query_params.append(f"session_id={urllib.parse.quote(session_id)}")
    if dispatch_id:
        query_params.append(f"dispatch_id={urllib.parse.quote(dispatch_id)}")
        
    stream_url = f"{stream_base}?{'&amp;'.join(query_params)}" if query_params else stream_base
        
    plivo_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" contentType="audio/x-mulaw;rate=8000" keepCallAlive="true">{stream_url}</Stream>
</Response>"""
    return HTMLResponse(content=plivo_xml, media_type="application/xml")


@app.post("/plivo/hangup")
async def handle_plivo_hangup(request: Request):
    """Callback triggered by Plivo when call completes."""
    logger.info("Plivo call hangup callback received.")
    return {"status": "hangup_recorded"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Plivo WebSocket endpoint for bidirectional Pipecat audio stream."""
    media_stream_connection = time.perf_counter()
    try:
        await websocket.accept()
        logger.info("WebSocket connection accepted from Plivo")
    except Exception as accept_err:
        logger.error(f"Failed to accept WebSocket connection: {accept_err}")
        return
    
    stream_sid = None
    import json
    import asyncio
    try:
        for _ in range(5):  # Don't loop forever
            data = await websocket.receive_text()
            logger.debug(f"Raw Plivo WS message: {data[:200]}")
            msg = json.loads(data)
            if msg.get("event") == "start":
                start_obj = msg.get("start", {})
                stream_sid = start_obj.get("streamId") or start_obj.get("streamSid") or start_obj.get("callId")

                # Prevention of duplicate session creation via Postgres atomic insert
                from sqlalchemy.exc import IntegrityError
                from app.db.connection import db_manager
                from app.db.models import ActiveStream
                import os

                try:
                    async def claim_stream():
                        async with db_manager.get_session() as db:
                            worker_id = str(os.getpid())
                            active_stream = ActiveStream(stream_sid=stream_sid, worker_id=worker_id)
                            db.add(active_stream)
                            await db.flush()
                    await asyncio.wait_for(claim_stream(), timeout=1.0)
                except IntegrityError:
                    logger.warning(f"[Worker-{os.getpid()}] Duplicate WebSocket connection for stream {stream_sid}. Already claimed by another worker. Rejecting.")
                    return
                except Exception as e:
                    logger.warning(f"[Worker-{os.getpid()}] Stream ownership claim skipped/timed-out for {stream_sid}: {e}. Proceeding with call.")

                logger.info(f"[Worker-{os.getpid()}] Successfully claimed ownership of stream {stream_sid}")

                # Extract parameters from query params and start event
                custom_params = start_obj.get("customParameters", {})
                phone_number = websocket.query_params.get("phone") or custom_params.get("phone", "unknown_client")
                client_id_str = websocket.query_params.get("client_id") or custom_params.get("client_id", "")
                company_context_raw = websocket.query_params.get("company_context") or custom_params.get("company_context", "")
                lead_id = websocket.query_params.get("lead_id") or custom_params.get("lead_id", "")
                domain = websocket.query_params.get("domain") or custom_params.get("domain", "")
                call_uuid = websocket.query_params.get("call_uuid") or start_obj.get("callId", "")
                session_id_val = websocket.query_params.get("session_id") or custom_params.get("session_id") or None
                dispatch_id_val = websocket.query_params.get("dispatch_id") or custom_params.get("dispatch_id") or ""
                webhook_processing_start = float(custom_params.get("webhook_processing_start", 0.0))
                previous_summary = custom_params.get("previous_summary", "")

                company_context = None
                if company_context_raw:
                    if isinstance(company_context_raw, dict):
                        company_context = company_context_raw
                    elif isinstance(company_context_raw, str):
                        try:
                            company_context = json.loads(company_context_raw)
                        except Exception:
                            company_context = {"company_name": company_context_raw}

                # If company_context wasn't fully supplied, pull directly from Team A's database
                if not company_context and (lead_id or domain):
                    try:
                        from database.repository import LeadRepository
                        repo = LeadRepository()
                        lead_rec = repo.get_lead_by_id_or_domain(domain or lead_id)
                        if lead_rec:
                            company_context = {
                                "lead_id": str(lead_rec.domain or lead_rec.id),
                                "company_name": lead_rec.company_name,
                                "domain": lead_rec.domain or lead_rec.website,
                                "industry": lead_rec.industry,
                                "location": lead_rec.location,
                                "tech_stack": lead_rec.tech_stack,
                                "company_summary": lead_rec.description,
                                "contact_name": lead_rec.people[0].name if lead_rec.people else "",
                                "contact_title": lead_rec.people[0].designation if lead_rec.people else "",
                                "lead_score": lead_rec.lead_score or 0,
                                "lead_quality": lead_rec.lead_quality or "",
                            }
                    except Exception as lead_err:
                        logger.warning(f"Could not load Team A lead for {lead_id or domain}: {lead_err}")

                first_audio_packet = time.perf_counter()
                connection_metrics = {
                    "webhook_processing_start": webhook_processing_start,
                    "media_stream_connection": media_stream_connection,
                    "first_audio_packet": first_audio_packet,
                }
                masked_phone = f"{phone_number[:3]}******{phone_number[-4:]}" if len(phone_number) > 7 and phone_number != "unknown_client" else phone_number
                logger.info(f"Plivo stream started: {stream_sid} | phone: {masked_phone} | lead: {lead_id or domain}")
                break
            elif msg.get("event") == "connected":
                logger.info("Plivo connected event received")
                continue

        if not stream_sid:
            logger.error("Did not receive 'start' event from Plivo")
            await websocket.close()
            return

    except Exception as ws_err:
        logger.error(f"WebSocket closed unexpectedly before start event: {ws_err}")
        return

    transport = PlivoTransportAdapter(
        websocket=websocket,
        stream_id=stream_sid,
        call_id=call_uuid,
        auth_id=os.getenv("PLIVO_AUTH_ID"),
        auth_token=os.getenv("PLIVO_AUTH_TOKEN"),
    )

    # ── Database Pre-fetch FALLBACK ──
    if not previous_summary and (client_id_str or phone_number != "unknown_client"):
        try:
            from app.db.connection import db_manager
            from app.repositories.session_repository import SessionRepository
            from app.repositories.client_repository import ClientRepository
            import uuid

            async def fetch_db_ws():
                nonlocal client_id_str
                async with db_manager.get_session() as db:
                    if client_id_str:
                        client_uuid = uuid.UUID(client_id_str)
                    else:
                        client = await ClientRepository.get_or_create_client(db, phone_number)
                        client_uuid = client.id
                        client_id_str = str(client_uuid)

                    return await SessionRepository.get_summary(db, client_uuid)

            summary_text = await asyncio.wait_for(fetch_db_ws(), timeout=1.0)
            if summary_text:
                logger.info(f"Retrieved DB summary for {client_id_str}: {summary_text[:50]}...")
                previous_summary = summary_text
        except asyncio.TimeoutError:
            logger.info("DB pre-fetch timed out (1.0s) in websocket. Proceeding without context.")
        except Exception as e:
            logger.error(f"Failed to fetch summary in websocket: {e}")

    # Block and run the voice session on this websocket
    try:
        await run_voice_session(
            transport=transport, 
            phone_number=phone_number, 
            company_context=company_context,
            lead_id=lead_id or domain,
            provider_call_id=call_uuid,
            client_id_str=client_id_str,
            previous_summary=previous_summary,
            connection_metrics=connection_metrics,
            session_id=session_id_val,
            dispatch_id=dispatch_id_val,
        )
    except WebSocketDisconnect as e:
        logger.warning(f"Plivo WebSocket disconnected in endpoint: code={e.code}, reason={e.reason}")
    except Exception as exc:
        logger.exception(f"Unhandled exception in websocket endpoint: {exc}")
    finally:
        try:
            from fastapi.websockets import WebSocketState
            if websocket.client_state != WebSocketState.DISCONNECTED:
                logger.info("Closing Plivo WebSocket connection gracefully")
                await websocket.close()
        except Exception as close_err:
            logger.warning(f"Error while closing Plivo WebSocket: {close_err}")
            
        # Cleanup of abandoned streams from distributed store
        if stream_sid:
            try:
                from sqlalchemy import delete
                from app.db.connection import db_manager
                from app.db.models import ActiveStream
                async with db_manager.get_session() as db:
                    await db.execute(delete(ActiveStream).where(ActiveStream.stream_sid == stream_sid))
                import os
                logger.info(f"[Worker-{os.getpid()}] Released distributed ownership for stream {stream_sid}")
            except Exception as e:
                logger.error(f"Failed to cleanup active stream {stream_sid} from DB: {e}")


# ── Core Pipeline Session ───────────────────────────────────────────────
async def run_voice_session(
    transport=None, 
    phone_number: str = "unknown_client", 
    company_context: Optional[dict] = None,
    lead_id: Optional[str] = None,
    provider_call_id: Optional[str] = None,
    client_id_str: str = "",
    previous_summary: str = "",
    connection_metrics: dict = None,
    session_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
) -> None:
    """Bootstrap and execute a single real-time voice session."""

    from app.db.connection import db_manager
    from app.repositories.session_repository import SessionRepository

    # ── 1. Session ──────────────────────────────────────────────────────
    session_manager = SessionManager()
    session = await session_manager.create_session(
        session_id=session_id,
        metadata={
            "client_id": client_id_str,
            "previous_summary": previous_summary,
            "company_context": company_context or {},
            "lead_id": lead_id or "",
            "provider_call_id": provider_call_id or "",
            "phone_number": phone_number,
            "dispatch_id": dispatch_id or "",
        }
    )
    session_id = session.session_id
    masked_phone = f"{phone_number[:3]}******{phone_number[-4:]}" if len(phone_number) > 7 and phone_number != "unknown_client" else phone_number
    logger.info("Session created | session_id={sid} | client={client}", sid=session_id, client=masked_phone)
    
    # Persist the Session in DB
    if client_id_str:
        try:
            c_id = uuid.UUID(client_id_str)
            async with db_manager.get_session() as db:
                await SessionRepository.create_session(db, session_id, c_id)
        except Exception as e:
            logger.error(f"Failed to persist Session: {e}")

    # ── 2. Event Bus ────────────────────────────────────────────────────
    event_bus = EventBus()
    
    # Subscribe to SessionClosed for DB Persistence
    async def on_session_closed(event: SessionClosed) -> None:
        from app.repositories.client_repository import ClientRepository
        async with db_manager.get_session() as db_session:
            sess_data = await session_manager.get_session(event.session_id)
            if not sess_data:
                return
            
            c_id_str = sess_data.metadata.get("client_id")
            c_id = None

            if c_id_str:
                try:
                    c_id = uuid.UUID(c_id_str)
                except ValueError:
                    c_id = None

            if not c_id:
                # Fallback: client_id wasn't passed through properly (e.g. websocket
                # query param missing/lost upstream), so look up/create the client
                # using the phone_number stored on the session instead.
                fallback_phone = sess_data.metadata.get("phone_number") or "unknown_client"
                fallback_client = await ClientRepository.get_or_create_client(db_session, fallback_phone)
                c_id = fallback_client.id
                masked_fallback = f"{fallback_phone[:3]}******{fallback_phone[-4:]}" if len(fallback_phone) > 7 and fallback_phone != "unknown_client" else fallback_phone
                logger.warning(
                    "client_id was missing in session metadata for {sid}; fell back to phone_number lookup ({phone})",
                    sid=event.session_id, phone=masked_fallback,
                )

            if c_id:
                
                # Mock LLM Summary Generation (in real prod, call an LLM API here with transcript)
                # Real LLM Summary Generation — combines previous summary + this call's
                # transcript into one updated, concise summary (overwrites the old one).
                from app.config import LLM_PROVIDER
                from app.session.message import Message

                history_texts = [
                    f"{msg.role}: {msg.content}"
                    for msg in sess_data.history
                    if msg.role != "system"
                ]
                transcript = "\n".join(history_texts)

                prev_summary_text = sess_data.metadata.get("previous_summary", "")

                summary_prompt = (
                    "You are maintaining a running memory of a caller for a voice assistant. "
                    "Combine the previous summary with the new call transcript below into ONE "
                    "updated summary. Keep it concise (3-5 sentences), factual, and focused on "
                    "details useful for future calls (who they are, what they asked about, any "
                    "preferences or unresolved issues). Do not include greetings or small talk. "
                    "If there is no meaningful conversation, do NOT speculate about technical glitches or silent calls, just state that no new information was gathered.\n\n"
                    "Additionally, analyze the overall call emotion of the caller based on their speech and tone in the transcript, and append it at the very end of your response in the format: '[Overall Call Emotion: Happy/Frustrated/Confused/Neutral]'. Let the overall emotion be chosen from Happy, Frustrated, Confused, or Neutral.\n\n"
                    f"Previous summary:\n{prev_summary_text if prev_summary_text else '(none, first call)'}\n\n"
                    f"New call transcript:\n{transcript if transcript else '(no conversation recorded)'}"
                )

                try:
                    if LLM_PROVIDER.lower() == "openai":
                        from app.llm.client import OpenAILLMClient
                        summary_client = OpenAILLMClient()
                    else:
                        from app.llm.client import GroqLLMClient
                        summary_client = GroqLLMClient()
                        
                    summary_messages = [
                        Message(role="system", content="You write concise caller memory summaries."),
                        Message(role="user", content=summary_prompt),
                    ]
                    generated_summary = ""
                    async for chunk in summary_client.stream_response(summary_messages):
                        generated_summary += chunk
                    generated_summary = generated_summary.strip()
                    import re
                    # Strip Qwen / DeepSeek internal <think>...</think> reasoning chain blocks
                    generated_summary = re.sub(r'<think>.*?</think>', '', generated_summary, flags=re.DOTALL).strip()
                    if "Here's a thinking process:" in generated_summary:
                        generated_summary = generated_summary.split("\n\n")[-1].strip()
                    
                    if not generated_summary:
                        generated_summary = prev_summary_text  # fallback: keep old summary
                    
                    # Extract overall emotion using regex
                    overall_emotion = "Neutral"
                    match = re.search(r'\[Overall Call Emotion:\s*(.*?)\]', generated_summary, re.IGNORECASE)
                    if match:
                        overall_emotion = match.group(1).strip()
                        # Clean the tag from the summary text to keep the database summary clean
                        generated_summary = re.sub(r'\s*\[Overall Call Emotion:.*?\]', '', generated_summary, flags=re.IGNORECASE).strip()
                    
                    logger.info(f"Session closed: Extracted overall_emotion='{overall_emotion}' | summary='{generated_summary[:50]}...'")
                    
                    # Broadcast to frontend so they can see the post-call analytics live
                    await broadcast_frontend_event("session_analytics", {
                        "summary": generated_summary,
                        "overall_emotion": overall_emotion
                    })
                except Exception as summary_err:
                    logger.error(
                        "Summary generation failed for session {sid}: {err}",
                        sid=event.session_id, err=summary_err,
                    )
                    generated_summary = prev_summary_text  # fallback: don't lose old summary on failure

                await SessionRepository.save_summary(db_session, c_id, generated_summary)
                await SessionRepository.close_session(db_session, event.session_id, int(sess_data.duration_seconds))
                logger.info("Persisted call summary and closed DB session for {sid}", sid=event.session_id)

            # ── Team A Integration Feedback Loop (Section 13) ─────────────────
            lead_ref = sess_data.metadata.get("lead_id")
            if not lead_ref and isinstance(sess_data.metadata.get("company_context"), dict):
                lead_ref = sess_data.metadata.get("company_context", {}).get("domain")

            if lead_ref:
                try:
                    from database.repository import LeadRepository
                    repo = LeadRepository()
                    
                    # Extract qualification signals from conversation transcript
                    t_lower = transcript.lower() if 'transcript' in locals() and transcript else ""
                    has_intent = any(w in t_lower for w in ["yes", "interested", "demo", "pricing", "cost", "budget", "meeting", "call back", "integrate", "pilot", "sure", "sounds good"])
                    has_rejection = any(w in t_lower for w in ["not interested", "no thank", "stop calling", "don't call", "wrong number", "busy"])
                    
                    if has_intent and not has_rejection:
                        qual_status = "qualified"
                        qual_score = 85
                    elif has_rejection:
                        qual_status = "unqualified"
                        qual_score = 25
                    else:
                        qual_status = "follow_up"
                        qual_score = 55
                        
                    qual_payload = {
                        "call_status": "completed",
                        "qualification_status": qual_status,
                        "qualification_score": qual_score,
                        "interest_level": "High" if qual_score >= 80 else ("Low" if qual_score < 40 else "Moderate"),
                        "pain_points": overall_emotion if 'overall_emotion' in locals() else "Neutral",
                        "budget": "Discussed on call" if ("budget" in t_lower or "cost" in t_lower) else "Not specified",
                        "timeline": "Immediate" if ("asap" in t_lower or "urgent" in t_lower or "soon" in t_lower) else "Standard",
                        "conversation_summary": generated_summary if 'generated_summary' in locals() and generated_summary else "Outbound qualification call completed.",
                        "provider_call_id": sess_data.metadata.get("provider_call_id", ""),
                        "session_id": event.session_id,
                    }
                    from models.lead_record import QualificationResult
                    validated_qual = QualificationResult(**qual_payload)
                    updated = repo.update_lead_qualification(lead_ref, validated_qual)
                    logger.info(f"Team A flowiz_leads qualification updated for lead '{lead_ref}': success={updated}")
                    
                    # Broadcast lead qualification result to frontend
                    await broadcast_frontend_event("lead_qualification_completed", {
                        "lead_id": lead_ref,
                        "qualification": validated_qual.model_dump()
                    })
                except Exception as q_err:
                    logger.error(f"Failed to update Team A lead qualification for {lead_ref}: {q_err}")

    sub_ids = []
    sub_ids.append(await event_bus.subscribe("SessionClosed", on_session_closed))
                
    await event_bus.start()
    event_bus.publish_sync(SessionCreated(session_id=session_id))
    logger.info("EventBus started")
    
    # ── 2b. UI WebSocket Bridges ────────────────────────────────────────
    from app.routers.livekit_router import broadcast_frontend_event
    from app.events.event_types import (
        AssistantGreetingStarted, AssistantGreetingCompleted,
        TranscriptReady, ThinkingStarted, ResponseGenerated,
        SpeakingStarted, SpeakingFinished, ErrorOccurred
    )

    async def on_greeting_started(e: AssistantGreetingStarted):
        await broadcast_frontend_event("greeting_started")

    async def on_greeting_completed(e: AssistantGreetingCompleted):
        await broadcast_frontend_event("greeting_complete")

    async def on_transcript_ready(e: TranscriptReady):
        if e.session_id != session_id:
            return
        text = e.payload.get("text", "")
        emotion = "Neutral"  # no emoji — Windows logger can't handle emoji
        detected_lang = "unknown"
        if text:
            # Strip any [System: ...] prompt engineering suffixes just in case
            import re
            text = re.sub(r'\s*\[System:.*?\]', '', text, flags=re.DOTALL).strip()
            logger.info(f"on_transcript_ready: cleaned_text='{text}'")
            
            # Detect language from the raw text (before stripping)
            devanagari_count = len(re.findall(r'[\u0900-\u097F]', text))
            hinglish_indicators = {'hai','mujhe','kya','kaise','chahiye','mera','ko','se','mein','kar','hu','tha','sakte','batao','koi','nahi','haan','rha'}
            words = set(re.findall(r'\b\w+\b', text.lower()))
            if devanagari_count > 10:
                detected_lang = "Hindi"
            elif len(words.intersection(hinglish_indicators)) >= 1:
                detected_lang = "Hinglish"
            else:
                detected_lang = "English"

            # Analyze user emotion
            from app.services.emotion_analyzer import analyze_emotion
            emotion = analyze_emotion(text)
            logger.info(f"on_transcript_ready: lang={detected_lang} | emotion={emotion}")
            
            await session_manager.add_message(session_id, role="user", content=text)
        await broadcast_frontend_event("transcription_received", {
            "text": text,
            "language": detected_lang,
            "latency_ms": e.payload.get("latency_ms", 0),
            "emotion": emotion
        })
        
    async def on_thinking_started(e: ThinkingStarted):
        if e.session_id != session_id:
            return
        await broadcast_frontend_event("llm_response_generating", {
            "latency_so_far_ms": e.payload.get("latency_so_far_ms", 0)
        })

    async def on_response_generated(e: ResponseGenerated):
        if e.session_id != session_id:
            return
        text = e.payload.get("text", "")
        if text:
            # Clean up function tags and JSON parameters from history text
            import re
            cleaned_text = re.sub(r'(?:\(|<)?\s*function=save_lead.*?(?:\s*<\/function>|\s*\)|>)?', '', text, flags=re.DOTALL).strip()
            cleaned_text = cleaned_text.replace("</function>", "").strip()
            
            await session_manager.add_message(session_id, role="assistant", content=cleaned_text)
            
            await broadcast_frontend_event("llm_response_complete", {
                "response_text": cleaned_text,
                "full_text": cleaned_text,
                "latency_ms": e.payload.get("latency_ms", 0)
            })
        else:
            await broadcast_frontend_event("llm_response_complete", {
                "response_text": "",
                "full_text": "",
                "latency_ms": e.payload.get("latency_ms", 0)
            })

    async def on_speaking_started(e: SpeakingStarted):
        await broadcast_frontend_event("tts_playing", {
            "duration_ms": e.payload.get("duration_ms", 0),
            "latency_ms": e.payload.get("latency_ms", 0)
        })
        
    async def on_speaking_finished(e: SpeakingFinished):
        await broadcast_frontend_event("tts_complete", {
            "latency_ms": e.payload.get("latency_ms", 0)
        })

    async def on_error(e: ErrorOccurred):
        await broadcast_frontend_event("error", {
            "error_message": str(e.payload.get("error", "Unknown pipeline error")),
            "component": e.payload.get("component", "unknown")
        })

    sub_ids.append(await event_bus.subscribe("AssistantGreetingStarted", on_greeting_started))
    sub_ids.append(await event_bus.subscribe("AssistantGreetingCompleted", on_greeting_completed))
    sub_ids.append(await event_bus.subscribe("TranscriptReady", on_transcript_ready))
    sub_ids.append(await event_bus.subscribe("ThinkingStarted", on_thinking_started))
    sub_ids.append(await event_bus.subscribe("ResponseGenerated", on_response_generated))
    sub_ids.append(await event_bus.subscribe("SpeakingStarted", on_speaking_started))
    sub_ids.append(await event_bus.subscribe("SpeakingFinished", on_speaking_finished))
    sub_ids.append(await event_bus.subscribe("ErrorOccurred", on_error))

    # ── 3. Conversation FSM ─────────────────────────────────────────────
    fsm = ConversationStateMachine(session_id=session_id)
    fsm.transition_to(ConversationState.LISTENING, reason="session initialized")

    # ── 4. Pipeline DAG ─────────────────────────────────────────────────
    pipeline_builder = PipelineFactory.create_voice_pipeline(
        event_bus=event_bus,
        session_id=session_id,
    )
    pipeline = pipeline_builder.build()
    logger.info("Pipeline DAG built | pipeline_id={pid}", pid=pipeline.pipeline_id)

    # ── 5. Transport Selection ──────────────────────────────────────────
    if not transport:
        if TRANSPORT_MODE.lower() == "livekit":
            from app.adapters.pipecat.transport import LiveKitTransportAdapter
            transport = LiveKitTransportAdapter(
                room_url=LIVEKIT_URL,
                bot_name=BOT_NAME,
            )
            # LiveKitTransport does not have a register_events method to call here
            logger.info("LiveKitTransportAdapter ready | room={r}", r=LIVEKIT_URL)
        else:
            raise ValueError(f"TRANSPORT_MODE '{TRANSPORT_MODE}' is invalid. Supported: 'plivo', 'livekit'.")
    else:
        logger.info("PlivoTransportAdapter injected via WebSocket.")

    # ── 6. Execution UUID ───────────────────────────────────────────────
    execution_id = str(uuid.uuid4())

    # ── 7. Pipecat Adapter ──────────────────────────────────────────────
    from app.metrics.latency import LatencyTracker
    latency_tracker = LatencyTracker()
    
    adapter = PipecatFactory.create_adapter(
        pipeline=pipeline,
        event_bus=event_bus,
        session_id=session_id,
        execution_id=execution_id,
        transport=transport,
        fsm=fsm,
        latency_tracker=latency_tracker,
        previous_summary=previous_summary,
        company_context=company_context,
        lead_id=lead_id,
    )
    logger.info("PipecatAdapter ready | execution_id={eid}", eid=execution_id)

    from app.adapters.pipecat.transport import LiveKitTransportAdapter
    if isinstance(transport, LiveKitTransportAdapter):
        raw_transport = transport.get_pipecat_transport()
        @raw_transport.event_handler("on_participant_disconnected")
        async def on_participant_disconnected(transport_instance, participant_id):
            logger.info("Participant {pid} disconnected. Queueing EndFrame to close pipeline.", pid=participant_id)
            from pipecat.frames.frames import EndFrame
            if adapter.task:
                await adapter.task.queue_frame(EndFrame())

    # ── 8. Update session state ─────────────────────────────────────────
    await session_manager.set_state(session_id, SessionState.LISTENING)

    # ── 9. Run ──────────────────────────────────────────────────────────
    try:
        logger.info("Starting pipeline processing loop.")
        # P0 Fix: Enforce wait_for to prevent infinite hangs if supported, or just catch disconnects
        await adapter.run()

    except WebSocketDisconnect as e:
        logger.warning(f"Plivo WebSocket disconnected abruptly: code={e.code}, reason={e.reason}")
    except asyncio.CancelledError:
        logger.warning("Pipeline task was cancelled by system")
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — shutting down gracefully")
    except Exception as exc:
        logger.exception("Pipeline error: {e}", e=exc)
    finally:
        # P0 Fix: Zombie Pipeline Cleanup
        # If the adapter is still running, ensure it's stopped.
        logger.info("Executing pipeline cleanup.")
        
        # Ensure the pipecat task is canceled to prevent hanging background workers
        if adapter and getattr(adapter, 'task', None):
            try:
                if hasattr(adapter.task, 'cancel'):
                    import inspect
                    cancel_res = adapter.task.cancel()
                    if inspect.iscoroutine(cancel_res):
                        await cancel_res
                    logger.info("Pipecat adapter task cancelled.")
            except Exception as cancel_err:
                logger.warning(f"Error canceling Pipecat adapter task: {cancel_err}")

        try:
            fsm.close(reason="pipeline finished")
        except Exception as e:
            logger.exception("Failed to close FSM cleanly")

        await session_manager.set_state(session_id, SessionState.CLOSED)
        event_bus.publish_sync(SessionClosed(session_id=session_id))
        await event_bus._queue.join()  # Wait for SessionClosed to be processed (persists summary) before stopping


        # Unsubscribe event listeners for this session
        for sub_id in sub_ids:
            try:
                await event_bus.unsubscribe(sub_id)
            except Exception as e:
                logger.warning("Failed to unsubscribe handler {sub_id}: {e}", sub_id=sub_id, e=e)

        await event_bus.stop()

        # Delete session from temporary SessionManager RAM store (Neon DB records remain saved)
        await session_manager.delete_session(session_id)
        logger.info("Session closed and temporary RAM cleaned | session_id={sid}", sid=session_id)
        
        # Dump latency profiles
        if connection_metrics:
            for k, v in connection_metrics.items():
                # Only log remaining global connection metrics
                logger.info(f"[LATENCY] {k} = {v}")
        
        # Print turn-by-turn benchmark summary
        latency_tracker.print_summary()

# Legacy Team B standalone frontend mounts removed. The single production frontend is served from root /static/index.html


def main() -> None:
    """Synchronous entry point."""
    import uvicorn
    logger.info(f"TRANSPORT_MODE is set to '{TRANSPORT_MODE}'. Starting FastAPI server on port 8000...")
    # Always run the FastAPI server so the frontend can hit /api/livekit/join and /ws/frontend
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["app"])

if __name__ == "__main__":
    main()
