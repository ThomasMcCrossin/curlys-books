"""
Database session management for SQLAlchemy with async support
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class DatabaseSessionManager:
    """Manage database connections and sessions"""
    
    def __init__(self):
        self._engine = None
        self._sessionmaker = None
    
    def init(self, database_url: str):
        """Initialize database engine and session maker"""
        # Convert postgresql:// to postgresql+asyncpg://
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        self._engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        
        self._sessionmaker = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    
    async def close(self):
        """Close database connections"""
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager for database sessions"""
        if self._sessionmaker is None:
            raise RuntimeError("DatabaseSessionManager not initialized")
        
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# Global session manager instance
sessionmanager = DatabaseSessionManager()


# Dependency for FastAPI
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency to get database session"""
    async with sessionmanager.session() as session:
        yield session


# Synchronous engine for Alembic migrations
from sqlalchemy import create_engine

engine = None


def get_sync_engine(database_url: str):
    """Get synchronous engine for migrations"""
    global engine
    if engine is None:
        engine = create_engine(
            database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return engine