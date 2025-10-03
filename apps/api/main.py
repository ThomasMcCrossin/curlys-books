"""
Curly's Books API - FastAPI application entry point
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from apps.api.middleware.auth_cloudflare import CloudflareAccessMiddleware
from apps.api.routers import receipts, banking, reimbursements, reports, shopify_sync
from packages.common.config import get_settings
from packages.common.database import engine, sessionmanager

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager"""
    logger.info("starting_curlys_books_api", 
                environment=settings.environment,
                version="0.1.0")
    
    # Initialize database connection pool
    sessionmanager.init(settings.database_url)
    
    yield
    
    # Cleanup
    logger.info("shutting_down_curlys_books_api")
    await sessionmanager.close()


# Create FastAPI application
app = FastAPI(
    title="Curly's Books API",
    description="Multi-entity accounting system for Curly's Canteen and Curly's Sports & Supplements",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
)


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://receipts.curlys.ca",
        "https://books.curlys.ca",
    ] if settings.environment == "production" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Cloudflare Access authentication (skip in dev if configured)
if not settings.skip_auth_validation:
    app.add_middleware(
        CloudflareAccessMiddleware,
        team_domain=settings.cloudflare_team_domain,
        audience=settings.cloudflare_access_aud,
    )


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with structured logging"""
    logger.warning("validation_error",
                   path=request.url.path,
                   errors=exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.errors(),
            "body": exc.body,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors"""
    logger.error("unhandled_exception",
                 path=request.url.path,
                 error=str(exc),
                 exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "request_id": request.headers.get("x-request-id"),
        },
    )


# Include routers
app.include_router(receipts.router, prefix="/api/v1/receipts", tags=["Receipts"])
app.include_router(banking.router, prefix="/api/v1/banking", tags=["Banking"])
app.include_router(reimbursements.router, prefix="/api/v1/reimbursements", tags=["Reimbursements"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(shopify_sync.router, prefix="/api/v1/shopify", tags=["Shopify"])


# Health check endpoint
@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint for Docker and monitoring"""
    try:
        # Check database connectivity
        async with sessionmanager.session() as session:
            await session.execute("SELECT 1")
        
        return {
            "status": "healthy",
            "environment": settings.environment,
            "version": "0.1.0",
            "services": {
                "database": "connected",
                "redis": "connected",  # TODO: Add Redis health check
            }
        }
    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "error": str(e),
            }
        )


# Metrics endpoint (Prometheus)
@app.get("/metrics", tags=["System"])
async def metrics():
    """Prometheus metrics endpoint"""
    if not settings.metrics_enabled:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Metrics disabled"}
        )
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# Root endpoint
@app.get("/", tags=["System"])
async def root():
    """API root endpoint"""
    return {
        "name": "Curly's Books API",
        "version": "0.1.0",
        "environment": settings.environment,
        "docs": "/docs" if settings.environment != "production" else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )