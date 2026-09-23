import asyncio
import uuid
import sys
from loguru import logger
from sqlalchemy import text

# Add the project root to sys.path so we can import from app
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.connection import db_manager
from app.repositories.client_repository import ClientRepository

async def test_connection():
    try:
        logger.info("Connecting to Neon PostgreSQL...")
        
        async with db_manager.get_session() as session:
            # 1. Test basic connectivity (execute a simple raw SQL query)
            result = await session.execute(text("SELECT version();"))
            version = result.scalar()
            logger.success(f"Successfully connected! Database Version: {version}")
            
            # 2. Test ORM functionality
            test_phone = f"+1234567890_{uuid.uuid4().hex[:6]}"
            logger.info(f"Testing ClientRepository by creating a mock client: {test_phone}")
            
            # Create
            client = await ClientRepository.get_or_create_client(session, test_phone)
            logger.success(f"Created Client with ID: {client.id}")
            
            # Retrieve
            fetched = await ClientRepository.get_by_phone_number(session, test_phone)
            if fetched and fetched.id == client.id:
                logger.success("ORM read/write test passed successfully!")
            else:
                logger.error("Failed to retrieve the created client.")
                sys.exit(1)
                
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        sys.exit(1)
    finally:
        await db_manager.close()
        
if __name__ == "__main__":
    asyncio.run(test_connection())
