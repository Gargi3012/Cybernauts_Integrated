import os
import asyncio
import time
from datetime import datetime
from collections import defaultdict
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from livekit import api
from loguru import logger

router = APIRouter()

# Global manager to keep track of frontend connections
frontend_websockets = []

# --- Security Dependencies ---
security = HTTPBearer()
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")

rate_limit_records = defaultdict(list)
RATE_LIMIT_REQUESTS = 5
RATE_LIMIT_WINDOW = 60

async def rate_limit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    current_time = time.time()
    
    # Cleanup old records
    rate_limit_records[client_ip] = [
        t for t in rate_limit_records[client_ip] 
        if current_time - t < RATE_LIMIT_WINDOW
    ]
    
    if len(rate_limit_records[client_ip]) >= RATE_LIMIT_REQUESTS:
        logger.warning(f"SECURITY: Rate limit exceeded for IP {client_ip} on /api/livekit/join")
        raise HTTPException(status_code=429, detail="Too many requests")
        
    rate_limit_records[client_ip].append(current_time)

async def verify_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        logger.info(f"SECURITY: Successful authentication for user {payload.get('sub', 'unknown')} on /api/livekit/join")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("SECURITY: Expired JWT token attempt")
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        logger.warning("SECURITY: Invalid JWT token attempt")
        raise HTTPException(status_code=403, detail="Invalid authentication token")

from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/api/login")
async def login(payload: LoginRequest):
    from app.db.connection import db_manager
    from app.db.models import User
    from app.services.auth_service import verify_password, create_jwt_token
    from sqlalchemy.future import select
    
    try:
        async with db_manager.get_session() as db:
            result = await db.execute(select(User).where(User.username == payload.username))
            user = result.scalars().first()
    except Exception as db_err:
        logger.error(f"Database error during login: {db_err}")
        raise HTTPException(status_code=500, detail="Database access error")
        
    if not user or not verify_password(user.hashed_password, payload.password):
        logger.warning(f"SECURITY: Failed login attempt for user '{payload.username}'")
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    token = create_jwt_token(payload.username)
    logger.info(f"SECURITY: Successful login for user '{payload.username}'")
    return {"token": token}

@router.post("/api/register")
async def register(payload: LoginRequest):
    from app.db.connection import db_manager
    from app.db.models import User
    from app.services.auth_service import hash_password
    from sqlalchemy.future import select

    if not payload.username or len(payload.username.strip()) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters long")
    if not payload.password or len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long")
        
    try:
        async with db_manager.get_session() as db:
            result = await db.execute(select(User).where(User.username == payload.username))
            existing_user = result.scalars().first()
            
            if existing_user:
                raise HTTPException(status_code=400, detail="Username already exists")
                
            hashed_pwd = hash_password(payload.password)
            new_user = User(
                username=payload.username,
                hashed_password=hashed_pwd
            )
            db.add(new_user)
            await db.commit()
            
            logger.info(f"SECURITY: Successfully registered new user '{payload.username}' in Neon database.")
            return {"status": "success", "message": "User registered successfully"}
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Database error during registration: {e}")
        raise HTTPException(status_code=500, detail="Failed to register user")

@router.post("/api/livekit/join", dependencies=[Depends(rate_limit), Depends(verify_jwt)])
async def join_livekit_room(request: dict = None):
    if os.getenv("TRANSPORT_MODE") != "livekit":
        raise HTTPException(status_code=400, detail="Not in LiveKit mode")
        
    # Generate token
    from app.config import LIVEKIT_ROOM
    room_name = LIVEKIT_ROOM
    participant_name = "user-frontend"
    
    try:
        token = api.AccessToken(
            os.getenv("LIVEKIT_API_KEY"), 
            os.getenv("LIVEKIT_API_SECRET")
        )
        token = token.with_identity(participant_name)
        token = token.with_name(participant_name)
        token = token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
        ))
        
        try:
            from app.main import run_voice_session
            asyncio.create_task(run_voice_session())
        except Exception as e:
            logger.exception(f"Failed to start voice session background task: {e}")
        
        return {
            "token": token.to_jwt(),
            "roomUrl": os.getenv("LIVEKIT_URL")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate token: {str(e)}")


@router.post("/api/plivo/outbound", dependencies=[Depends(verify_jwt)])
@router.post("/api/telephony/outbound", dependencies=[Depends(verify_jwt)])
@router.post("/api/twilio/outbound", dependencies=[Depends(verify_jwt)])
async def trigger_outbound_call(payload: dict):
    phone_number = payload.get("phoneNumber") or payload.get("phone_number")
    if not phone_number:
        raise HTTPException(status_code=400, detail="phoneNumber is required")

    company_context = payload.get("company_context") or payload.get("companyContext")
    import json
    import uuid
    company_context_str = json.dumps(company_context) if isinstance(company_context, dict) else (company_context or None)
    lead_id = payload.get("lead_id")
    session_id = payload.get("session_id") or f"sess_{uuid.uuid4().hex[:12]}"
    dispatch_id = payload.get("dispatch_id") or f"disp_{uuid.uuid4().hex[:12]}"
    transport_mode = os.getenv("TRANSPORT_MODE", "plivo").lower()

    # Call Prompt / Script Validation and Registration
    from app.services.call_config_registry import CallPromptConfig, call_config_registry
    prompt_config = None
    raw_prompt = payload.get("call_prompt")
    if raw_prompt is not None and str(raw_prompt).strip():
        try:
            prompt_config = CallPromptConfig(
                call_prompt=str(raw_prompt),
                objective=payload.get("objective"),
                custom_qualification_criteria=payload.get("custom_qualification_criteria") or [],
            )
            call_config_registry.set(
                session_id=session_id,
                config=prompt_config,
                dispatch_id=dispatch_id,
            )
        except ValueError as val_err:
            raise HTTPException(status_code=422, detail=str(val_err))
        except Exception as p_err:
            raise HTTPException(status_code=422, detail=f"Invalid call_prompt: {p_err}")

    try:
        if transport_mode == "twilio":
            from Pillar_2.outbound_call import place_outbound_call
            call_sid = await asyncio.to_thread(place_outbound_call, phone_number, company_context_str)
            return {
                "status": "success",
                "callSid": call_sid,
                "call_id": call_sid,
                "provider": "twilio",
                "session_id": session_id,
                "dispatch_id": dispatch_id,
                "call_prompt_attached": bool(prompt_config is not None),
            }
        else:
            try:
                from Pillar_2.outbound_call import place_outbound_call
                call_id = await asyncio.to_thread(
                    place_outbound_call,
                    phone_number,
                    company_context=company_context_str,
                    lead_id=lead_id,
                    session_id=session_id,
                    dispatch_id=dispatch_id,
                )
            except Exception:
                from Pillar_2.plivo_outbound import place_plivo_outbound_call
                call_id = await asyncio.to_thread(place_plivo_outbound_call, phone_number, company_context_str)
            return {
                "status": "success",
                "callSid": call_id,
                "call_id": call_id,
                "provider": "plivo",
                "session_id": session_id,
                "dispatch_id": dispatch_id,
                "call_prompt_attached": bool(prompt_config is not None),
            }
    except Exception as e:
        if prompt_config:
            call_config_registry.delete(session_id=session_id, dispatch_id=dispatch_id, reason="dispatch_failed")
        logger.exception(f"Failed to place outbound call via {transport_mode}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/telephony/hangup")
@router.post("/api/plivo/hangup-call")
async def manual_telephony_hangup(payload: dict):
    """Explicitly hang up an active Plivo carrier phone call."""
    call_id = payload.get("call_id") or payload.get("callSid") or payload.get("call_uuid")
    auth_id = os.getenv("PLIVO_AUTH_ID")
    auth_token = os.getenv("PLIVO_AUTH_TOKEN")

    if not call_id:
        raise HTTPException(status_code=400, detail="call_id is required")

    if not auth_id or not auth_token:
        raise HTTPException(status_code=500, detail="Plivo credentials not configured")

    try:
        import aiohttp
        endpoint = f"https://api.plivo.com/v1/Account/{auth_id}/Call/{call_id}/"
        async with aiohttp.ClientSession() as session:
            auth = aiohttp.BasicAuth(auth_id, auth_token)
            async with session.delete(endpoint, auth=auth) as resp:
                logger.info(f"Manual hangup executed for call_id={call_id}: HTTP {resp.status}")
                return {"status": "success", "call_id": call_id, "http_status": resp.status}
    except Exception as err:
        logger.error(f"Manual hangup failed for {call_id}: {err}")
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/api/call-history")
async def get_call_history():
    from app.db.connection import db_manager
    from app.db.models import DbSession, Client, ConversationSummary
    from sqlalchemy.future import select
    from sqlalchemy.orm import selectinload

    try:
        async with db_manager.get_session() as db:
            stmt = select(DbSession).options(
                selectinload(DbSession.client).selectinload(Client.summary)
            ).order_by(DbSession.started_at.desc()).limit(50)
            result = await db.execute(stmt)
            sessions = result.scalars().all()

            history = []
            for s in sessions:
                phone = s.client.phone_number if s.client else "Unknown"
                summary = s.client.summary.summary if (s.client and s.client.summary) else "No summary recorded."
                duration_str = f"{s.duration}s" if s.duration else "—"
                t_mode = os.getenv("TRANSPORT_MODE", "plivo").lower()
                if "plivo" in s.session_id.lower():
                    t_label = "Plivo Telephony"
                elif "twilio" in s.session_id.lower():
                    t_label = "Twilio Telephony"
                elif phone.startswith("+"):
                    t_label = "Plivo Telephony" if t_mode == "plivo" else "Twilio Telephony"
                else:
                    t_label = "LiveKit WebRTC"

                history.append({
                    "id": str(s.id),
                    "sessionId": s.session_id,
                    "phone": phone,
                    "transport": t_label,
                    "duration": duration_str,
                    "status": s.status or "COMPLETED",
                    "summary": summary,
                    "startedAt": s.started_at.isoformat() if s.started_at else None
                })
            return {"calls": history}
    except Exception as e:
        logger.warning(f"Failed to fetch call history from DB: {e}")

    return {"calls": []}


@router.websocket("/ws/frontend")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    frontend_websockets.append(websocket)
    
    # Send initial transport mode
    await websocket.send_json({
        "event": "transport_mode",
        "mode": os.getenv("TRANSPORT_MODE", "livekit"),
        "timestamp": datetime.now().isoformat()
    })
    
    try:
        while True:
            # Keep connection open, frontend only receives
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in frontend_websockets:
            frontend_websockets.remove(websocket)


async def broadcast_frontend_event(event_name: str, data: dict = None):
    """
    Helper function to call from Pipeline to push state to the UI.
    """
    if data is None:
        data = {}
    payload = {
        "event": event_name, 
        "timestamp": datetime.now().isoformat(),
        **data
    }
    
    # Send to all connected frontends
    disconnected = []
    for ws in frontend_websockets:
        try:
            await ws.send_json(payload)
        except Exception:
            disconnected.append(ws)
            
    # Cleanup stale connections
    for ws in disconnected:
        if ws in frontend_websockets:
            frontend_websockets.remove(ws)
