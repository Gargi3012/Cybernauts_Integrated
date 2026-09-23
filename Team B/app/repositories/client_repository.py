from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client


class ClientRepository:
    """Handles database operations for the Client model."""
    
    @staticmethod
    async def get_by_phone_number(session: AsyncSession, phone_number: str) -> Optional[Client]:
        """Fetch a client by their unique phone number."""
        stmt = select(Client).where(Client.phone_number == phone_number)
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def create_client(session: AsyncSession, phone_number: str) -> Client:
        """Create a new client with the given phone number."""
        client = Client(phone_number=phone_number)
        session.add(client)
        await session.flush()
        return client

    @staticmethod
    async def get_or_create_client(session: AsyncSession, phone_number: str) -> Client:
        """Fetch a client by phone number or create one if it does not exist."""
        client = await ClientRepository.get_by_phone_number(session, phone_number)
        if not client:
            client = await ClientRepository.create_client(session, phone_number)
        return client
