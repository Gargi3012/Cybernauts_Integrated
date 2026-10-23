import uuid
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ConversationSummary, DbSession


class SessionRepository:
    """Handles database operations for Session and ConversationSummary models."""

    @staticmethod
    async def create_session(
        session: AsyncSession, 
        session_id: str, 
        client_id: uuid.UUID,
        started_at: Optional[datetime] = None
    ) -> DbSession:
        """Create a new session record in the database idempotently."""
        stmt = select(DbSession).where(DbSession.session_id == session_id)
        result = await session.execute(stmt)
        existing = result.scalars().first()
        if existing:
            return existing

        db_session = DbSession(
            session_id=session_id,
            client_id=client_id,
            started_at=started_at or datetime.now(timezone.utc),
            status="ACTIVE"
        )
        session.add(db_session)
        await session.flush()
        return db_session

    @staticmethod
    async def close_session(
        session: AsyncSession, 
        session_id: str, 
        duration: Optional[int] = None,
        client_id: Optional[uuid.UUID] = None,
        started_at: Optional[datetime] = None
    ) -> Optional[DbSession]:
        """Mark a session as CLOSED and record its end time and duration.
        
        If the session row was not found (e.g. background creation failed or was skipped),
        defensively insert the closed session if client_id is available.
        """
        stmt = select(DbSession).where(DbSession.session_id == session_id)
        result = await session.execute(stmt)
        db_session = result.scalars().first()

        now_utc = datetime.now(timezone.utc)
        if db_session:
            db_session.status = "CLOSED"
            db_session.ended_at = now_utc
            if duration is not None:
                db_session.duration = duration
            await session.flush()
            return db_session

        # Defensive fallback: session row was never created at call start
        if client_id is not None:
            logger.warning(f"Session {session_id} not found in DB at close time. Performing defensive fallback creation.")
            db_session = DbSession(
                session_id=session_id,
                client_id=client_id,
                started_at=started_at or now_utc,
                ended_at=now_utc,
                duration=duration,
                status="CLOSED"
            )
            session.add(db_session)
            await session.flush()
            return db_session
        else:
            logger.error(f"Cannot close or create fallback DB session {session_id}: client_id is missing and 0 rows updated.")
            return None

    @staticmethod
    async def get_summary(session: AsyncSession, client_id: uuid.UUID) -> Optional[str]:
        """Retrieve the latest conversation summary for a client."""
        stmt = select(ConversationSummary).where(ConversationSummary.client_id == client_id)
        result = await session.execute(stmt)
        summary_record = result.scalars().first()
        return summary_record.summary if summary_record else None

    @staticmethod
    async def save_summary(session: AsyncSession, client_id: uuid.UUID, summary_text: str) -> ConversationSummary:
        """Create or update the conversation summary for a client."""
        stmt = select(ConversationSummary).where(ConversationSummary.client_id == client_id)
        result = await session.execute(stmt)
        summary_record = result.scalars().first()

        from datetime import datetime, timezone
        if summary_record:
            summary_record.summary = summary_text
            summary_record.updated_at = datetime.now(timezone.utc)
        else:
            summary_record = ConversationSummary(client_id=client_id, summary=summary_text)
            session.add(summary_record)
        
        await session.flush()
        return summary_record
