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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing unified server lifespan...")
    
    # Initialize Team A SQLite Database
    try:
        team_a_module.init_db()
        logger.info("Team A SQLite database (leads.db) initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Team A SQLite database: {e}")

    # Initialize Team B PostgreSQL Database Pool
    try:
        db_manager.init_db()
        async def prewarm():
            async with db_manager.get_session() as db:
                from sqlalchemy import text
                await db.execute(text("SELECT 1"))
        await asyncio.wait_for(prewarm(), timeout=1.0)
        logger.info("Team B PostgreSQL database connection pool initialized.")
    except Exception as e:
        logger.warning(f"Team B Database startup notice (degrading gracefully): {e}")

    yield

    logger.info("Shutting down database connection pools...")
    await db_manager.close()


app = FastAPI(
    title="Cybernauts Integrated — Lead Intelligence & AI Voice Platform",
    version="2.0.0",
    lifespan=lifespan
)

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

# Strip out conflicting root redirects and standalone frontend mounts from Team B before including
conflicting_paths = {
    "/", "/index.html", "/voice", "/voice/", "/voice/frontend",
    "/voice/frontend/", "/voice/frontend/index.html", "/frontend", "/frontend/index.html"
}
team_b_app.router.routes = [
    r for r in team_b_app.router.routes
    if getattr(r, "path", None) not in conflicting_paths and getattr(r, "name", None) not in ["frontend", "voice_frontend"]
]

# Include Team B REST & WebSocket endpoints (/inbound-call, /ws, /api/login, /api/register, /api/livekit/join, /api/twilio/outbound, /ws/frontend)
app.include_router(team_b_app.router)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=True)
