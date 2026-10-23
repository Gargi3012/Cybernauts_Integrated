"""
Unified Application Server for Cybernauts Integrated Platform
Combines Team A (Lead Intelligence & Discovery) and Team B (AI Voice Agent & Telephony)
into a single FastAPI application server on Port 8000.
"""

import os
import sys
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

# Ensure root, Team A, Team B, and pillar1 subdirectories are in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEAM_A_DIR = os.path.join(BASE_DIR, "Team A")
TEAM_B_DIR = os.path.join(BASE_DIR, "Team B")
PILLAR1_DIR = os.path.join(TEAM_A_DIR, "pillar1")

for p in [PILLAR1_DIR, TEAM_A_DIR, TEAM_B_DIR, BASE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Import Team A and Team B FastAPI instances / routers
import api as team_a_module
from app.main import app as team_b_app
from app.db.connection import db_manager
from loguru import logger


# Module-level readiness state for server lifecycle and health checks
APP_STATE = {
    "is_ready": False,
    "db_team_a": False,
    "db_recordings": False,
    "db_team_b": False
}


def validate_production_configuration():
    """
    Validate critical security configuration on server startup.
    In production environments (ENVIRONMENT=production/prod), strictly ensures that required
    secrets (such as JWT_SECRET) are securely configured and compliant with RFC 7518.
    Fails server startup immediately if required production secrets are missing or insecure.
    """
    env = os.getenv("ENVIRONMENT", "").strip().lower()
    if env in ("production", "prod"):
        from app.services.auth_service import get_jwt_secret
        get_jwt_secret()  # Strictly raises RuntimeError or ValueError


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing unified server lifespan...")
    
    # 0. Validate production security configuration
    validate_production_configuration()

    # Initialize Team A SQLite Database
    try:
        team_a_module.init_db()
        APP_STATE["db_team_a"] = True
        logger.info("Team A SQLite database (leads.db) initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Team A SQLite database: {e}")

    # Initialize Team B PostgreSQL Database Pool & mark readiness
    from app.main import APP_STATE as team_b_app_state
    team_b_app_state["is_ready"] = True
    try:
        db_manager.init_db()
        async def prewarm():
            async with db_manager.get_session() as db:
                from sqlalchemy import text
                await db.execute(text("SELECT 1"))
        await asyncio.wait_for(prewarm(), timeout=1.0)
        APP_STATE["db_team_b"] = True
        logger.info("Team B PostgreSQL database connection pool initialized.")
    except Exception as e:
        logger.warning(f"Team B Database startup notice (degrading gracefully): {e}")

    # Pre-warm canonical persona greetings in background for 0ms startup voice latency
    async def _prewarm_persona_greetings():
        try:
            from app.adapters.pipecat.sarvam_tts_service import prewarm_tts_audio
            from app.services.persona_registry import CANONICAL_PERSONAS
            for p_id, p_obj in CANONICAL_PERSONAS.items():
                await prewarm_tts_audio(p_obj.greeting_en, voice=p_obj.voice, sample_rate=16000)
            logger.info("Canonical persona greeting audios pre-warmed in memory.")
        except Exception as pw_err:
            logger.debug(f"Persona audio pre-warm notice: {pw_err}")
    asyncio.create_task(_prewarm_persona_greetings())

    # Sync Team B APP_STATE readiness
    try:
        from app.main import APP_STATE as TEAM_B_APP_STATE
        TEAM_B_APP_STATE["is_ready"] = True
    except Exception as state_err:
        logger.debug(f"Team B APP_STATE sync notice: {state_err}")

    # Check Team B database requirement policy
    # Team B uses PostgreSQL for active streams and multi-agent session records.
    # By default, PostgreSQL is designed to degrade gracefully (optional) if not provisioned,
    # but can be enforced as mandatory in production clusters via REQUIRE_TEAM_B_DB=true.
    require_team_b_db = os.getenv("REQUIRE_TEAM_B_DB", "false").lower() in ("true", "1")
    APP_STATE["team_b_db_required"] = require_team_b_db

    sqlite_ready = bool(APP_STATE.get("db_team_a") and APP_STATE.get("db_recordings"))
    team_b_ready = bool(APP_STATE.get("db_team_b")) if require_team_b_db else True

    if sqlite_ready and team_b_ready:
        APP_STATE["is_ready"] = True
        logger.info(f"Unified server verified healthy & ready for traffic (Team B DB required: {require_team_b_db}).")
    else:
        APP_STATE["is_ready"] = False
        logger.error(
            f"Unified server startup incomplete: sqlite_ready={sqlite_ready}, "
            f"team_b_db={APP_STATE.get('db_team_b')} (required: {require_team_b_db})."
        )

    yield

    APP_STATE["is_ready"] = False
    try:
        from app.main import APP_STATE as TEAM_B_APP_STATE
        TEAM_B_APP_STATE["is_ready"] = False
    except Exception:
        pass

    logger.info("Shutting down database connection pools...")
    team_b_app_state["is_ready"] = False
    await db_manager.close()


app = FastAPI(
    title="Cybernauts Integrated — Lead Intelligence & AI Voice Platform",
    version="2.0.0",
    lifespan=lifespan
)

# Production health & readiness check for Cybernauts Integrated platform
@app.get("/health")
def health_check():
    """Readiness & liveness verification endpoint for load balancers & CI/CD deployment."""
    require_team_b_db = APP_STATE.get("team_b_db_required", False)
    if not APP_STATE.get("is_ready"):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "message": "Server initializing or database initialization incomplete",
                "team_a_db": APP_STATE.get("db_team_a", False),
                "recordings_db": APP_STATE.get("db_recordings", False),
                "team_b_db": APP_STATE.get("db_team_b", False),
                "team_b_db_required": require_team_b_db,
            }
        )
    return {
        "status": "ok",
        "app": "cybernauts-integrated",
        "version": "2.0.0",
        "ready": True,
        "team_a_db": APP_STATE.get("db_team_a", False),
        "recordings_db": APP_STATE.get("db_recordings", False),
        "team_b_db": APP_STATE.get("db_team_b", False),
        "team_b_db_required": require_team_b_db,
    }

# Configure CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve Unified Light-Theme Frontend SPA first so it always takes precedence at root
static_dir = os.path.join(BASE_DIR, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static_files")
    
    @app.get("/")
    @app.get("/index.html")
    def serve_index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    # If user's browser is cached or directed to old Team B frontend path, redirect back to root integrated SPA
    @app.get("/frontend/index.html")
    @app.get("/frontend")
    @app.get("/frontend/")
    @app.get("/voice/frontend/index.html")
    @app.get("/voice/frontend")
    @app.get("/voice/frontend/")
    @app.get("/voice")
    @app.get("/voice/")
    def redirect_to_unified():
        return RedirectResponse(url="/", status_code=302)

# Include Team A REST API endpoints (/api/search, /api/status, /api/leads, /api/categories)
app.include_router(team_a_module.app.router)

# Include Team B REST & WebSocket endpoints (/inbound-call, /plivo/incoming, /ws, /api/login, /api/register, /api/livekit/join, /api/plivo/outbound, /ws/frontend)
# Filter without mutating team_b_app.router.routes in-place to preserve test and process isolation
from fastapi import APIRouter
conflicting_paths = {
    "/", "/index.html", "/health", "/voice", "/voice/", "/voice/frontend",
    "/voice/frontend/", "/voice/frontend/index.html", "/frontend", "/frontend/index.html"
}
filtered_b_router = APIRouter(
    routes=[
        r for r in team_b_app.router.routes
        if getattr(r, "path", None) not in conflicting_paths and getattr(r, "name", None) not in ["frontend", "voice_frontend"]
    ]
)
app.include_router(filtered_b_router)

# Include Call Recordings REST APIs & Webhooks (/api/recordings, /api/recordings/upload, /api/telephony/recording-callback)
from routers.recordings_router import router as recordings_router
app.include_router(recordings_router)

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    is_dev = os.getenv("ENVIRONMENT", "development").lower() == "development"
    reload_dirs = [BASE_DIR] if is_dev else None
    uvicorn.run("server:app", host=host, port=port, reload=is_dev, reload_dirs=reload_dirs)
