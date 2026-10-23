"""
recording_manager.py
====================
Database persistence and management for Call Recordings (Telephony & LiveKit WebRTC).
Integrates with SQLite leads.db and handles local / remote recording metadata.
"""

import os
import sqlite3
from typing import Any, Dict, List, Optional
from loguru import logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "leads.db")
RECORDINGS_DIR = os.path.join(BASE_DIR, "static", "recordings")

os.makedirs(RECORDINGS_DIR, exist_ok=True)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    target = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(target, timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_recordings_db(db_path: Optional[str] = None) -> None:
    """Initialize the canonical call_recordings table and indexes."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS call_recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE,
                    call_id TEXT,
                    lead_id INTEGER,
                    lead_name TEXT,
                    phone_number TEXT,
                    channel TEXT NOT NULL,
                    duration_seconds INTEGER DEFAULT 0,
                    file_path TEXT NOT NULL,
                    file_size_kb INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(lead_id) REFERENCES flowiz_leads(id) ON DELETE SET NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_channel ON call_recordings(channel)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_created ON call_recordings(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_session ON call_recordings(session_id)")
        logger.info("call_recordings table initialized successfully in leads.db")
    except Exception as e:
        logger.error(f"Error initializing call_recordings table: {e}")
        raise
    finally:
        conn.close()


def save_recording(
    session_id: str,
    channel: str,
    file_path: str,
    lead_name: Optional[str] = None,
    phone_number: Optional[str] = None,
    call_id: Optional[str] = None,
    lead_id: Optional[int] = None,
    duration_seconds: int = 0,
    file_size_kb: int = 0,
    status: str = "completed",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Insert or update a call recording record."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO call_recordings (
                    session_id, call_id, lead_id, lead_name, phone_number,
                    channel, duration_seconds, file_path, file_size_kb, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    duration_seconds = excluded.duration_seconds,
                    file_path = excluded.file_path,
                    file_size_kb = excluded.file_size_kb,
                    status = excluded.status,
                    lead_name = COALESCE(excluded.lead_name, call_recordings.lead_name),
                    phone_number = COALESCE(excluded.phone_number, call_recordings.phone_number),
                    call_id = COALESCE(excluded.call_id, call_recordings.call_id)
                """,
                (
                    session_id, call_id, lead_id, lead_name or "Anonymous Prospect",
                    phone_number or "Web Session", channel, duration_seconds,
                    file_path, file_size_kb, status
                )
            )
            rec_id = cursor.lastrowid
            
        return get_recording_by_session(session_id, db_path) or {"id": rec_id, "session_id": session_id}
    finally:
        conn.close()


def get_recording_by_session(session_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM call_recordings WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_recordings(
    channel: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieve call recordings with optional filtering."""
    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM call_recordings WHERE 1=1"
        params: List[Any] = []

        if channel and channel.lower() != "all":
            query += " AND channel = ?"
            params.append(channel.lower())

        if search and search.strip():
            term = f"%{search.strip()}%"
            query += " AND (lead_name LIKE ? OR phone_number LIKE ? OR session_id LIKE ?)"
            params.extend([term, term, term])

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_recording(rec_id: int, db_path: Optional[str] = None) -> bool:
    """Delete a recording entry and its local file if stored locally."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT file_path FROM call_recordings WHERE id = ?", (rec_id,)).fetchone()
        if not row:
            return False

        file_path = row["file_path"]
        # Delete local file if inside static/recordings/
        if file_path and file_path.startswith("/static/recordings/"):
            rel_name = file_path.replace("/static/recordings/", "")
            full_file_path = os.path.join(RECORDINGS_DIR, rel_name)
            if os.path.exists(full_file_path):
                try:
                    os.remove(full_file_path)
                    logger.info(f"Deleted local recording file: {full_file_path}")
                except Exception as ex:
                    logger.warning(f"Could not delete physical file {full_file_path}: {ex}")

        with conn:
            conn.execute("DELETE FROM call_recordings WHERE id = ?", (rec_id,))
        return True
    finally:
        conn.close()
