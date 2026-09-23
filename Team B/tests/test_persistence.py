import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Client, DbSession, ConversationSummary
from app.repositories.client_repository import ClientRepository
from app.repositories.session_repository import SessionRepository

# Note: This requires pytest-asyncio to run properly
pytestmark = pytest.mark.asyncio

async def test_create_and_get_client(db_session: AsyncSession):
    phone = "+1234567890"
    client = await ClientRepository.get_or_create_client(db_session, phone)
    assert client is not None
    assert client.phone_number == phone
    
    # Fetch again should return the same client
    client2 = await ClientRepository.get_or_create_client(db_session, phone)
    assert client.id == client2.id

async def test_session_lifecycle(db_session: AsyncSession):
    client = await ClientRepository.get_or_create_client(db_session, "+0987654321")
    sess_id = str(uuid.uuid4())
    
    db_sess = await SessionRepository.create_session(db_session, sess_id, client.id)
    assert db_sess.status == "ACTIVE"
    
    closed_sess = await SessionRepository.close_session(db_session, sess_id, duration=42)
    assert closed_sess.status == "CLOSED"
    assert closed_sess.duration == 42
    assert closed_sess.ended_at is not None

async def test_summary_persistence(db_session: AsyncSession):
    client = await ClientRepository.get_or_create_client(db_session, "+1122334455")
    
    # Initially no summary
    summary = await SessionRepository.get_summary(db_session, client.id)
    assert summary is None
    
    # Save new summary
    await SessionRepository.save_summary(db_session, client.id, "Initial summary")
    summary = await SessionRepository.get_summary(db_session, client.id)
    assert summary == "Initial summary"
    
    # Update summary
    await SessionRepository.save_summary(db_session, client.id, "Updated summary")
    summary = await SessionRepository.get_summary(db_session, client.id)
    assert summary == "Updated summary"
