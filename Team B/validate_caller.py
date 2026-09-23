import asyncio
from sqlalchemy import text, delete
from app.db.connection import db_manager
from app.repositories.client_repository import ClientRepository
from app.db.models import Client

async def run_validation():
    test_number = "+919999999999"
    db_manager.init_db()

    async with db_manager.get_session() as session:
        # Step 3: Delete existing test data
        stmt = delete(Client).where(Client.phone_number == test_number)
        await session.execute(stmt)
        await session.commit()

    async with db_manager.get_session() as session:
        # Step 4: Simulate first incoming call
        client_1 = await ClientRepository.get_or_create_client(session, test_number)
        print("FIRST CALL:")
        print(f"UUID: {client_1.id}")
        print(f"Phone Number: {client_1.phone_number}")
        print(f"Created Timestamp: {client_1.created_at}")

        # Step 5: Simulate second incoming call
        client_2 = await ClientRepository.get_or_create_client(session, test_number)
        print("\nSECOND CALL:")
        print(f"UUID: {client_2.id}")
        print(f"Phone Number: {client_2.phone_number}")
        print(f"Updated Timestamp: {client_2.updated_at}")
        
        # Step 6: Query the database
        count_stmt = text(f"SELECT COUNT(*) FROM clients WHERE phone_number = '{test_number}'")
        result = await session.execute(count_stmt)
        count = result.scalar()
        print("\nDATABASE VALIDATION:")
        print(f"Count: {count}")

        assert client_1.id == client_2.id, "UUIDs do not match!"
        assert client_1.phone_number == client_2.phone_number, "Phone numbers do not match!"
        assert count == 1, "Duplicate client records exist!"

if __name__ == "__main__":
    asyncio.run(run_validation())
