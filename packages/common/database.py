"""
Database session management for SQLAlchemy with async support

Supports both FastAPI (explicit init) and standalone scripts (lazy init).
"""
import os
import asyncio
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
        self._init_lock = asyncio.Lock()

    @property
    def initialized(self) -> bool:
        """Check if session manager is initialized"""
        return self._sessionmaker is not None

    async def init(self, database_url: str, **engine_kwargs):
        """Initialize database engine and session maker"""
        if self.initialized:
            return

        async with self._init_lock:  # Double-checked locking
            if self.initialized:
                return

            # Convert postgresql:// to postgresql+asyncpg://
            if database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            # Default engine settings
            default_kwargs = {
                "echo": engine_kwargs.get("echo", False),
                "pool_size": 20,
                "max_overflow": 10,
                "pool_pre_ping": True,
                "pool_recycle": 3600,
            }
            default_kwargs.update(engine_kwargs)

            self._engine = create_async_engine(database_url, **default_kwargs)

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
        if not self.initialized:
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


# ---- Lazy auto-init for standalone scripts ----------------------------------------------

_lazy_lock = asyncio.Lock()


async def _ensure_initialized():
    """
    Ensure database session manager is initialized.

    This allows scripts to work without explicit init() call by reading
    DATABASE_URL from environment. Can be disabled in production with
    DB_LAZY_INIT=0 for stricter control.
    """
    if sessionmanager.initialized:
        return

    # Optional feature flag to disable lazy init in production
    if os.getenv("DB_LAZY_INIT", "1") not in {"1", "true", "True"}:
        raise RuntimeError(
            "Database lazy init disabled and session manager not initialized. "
            "Call sessionmanager.init(DATABASE_URL) explicitly in startup."
        )

    # Get DATABASE_URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable not set for lazy database initialization"
        )

    # Check for SQL echo flag
    echo = os.getenv("SQL_ECHO", "0") in {"1", "true", "True"}

    # Initialize with lock to prevent race conditions
    async with _lazy_lock:
        if not sessionmanager.initialized:
            await sessionmanager.init(database_url, echo=echo)


# Dependency for FastAPI and standalone scripts
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session (works in FastAPI and standalone scripts).

    In FastAPI: Expects sessionmanager.init() called during startup.
    In scripts: Auto-initializes from DATABASE_URL if not already initialized.
    """
    await _ensure_initialized()
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