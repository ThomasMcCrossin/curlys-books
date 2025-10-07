from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class CloudflareAccessMiddleware(BaseHTTPMiddleware):
    """
    Cloudflare Access authentication middleware.
    For Phase 1 development, this is a stub that allows all requests.
    TODO: Implement proper JWT validation when deploying to production.
    """
    
    async def dispatch(self, request: Request, call_next):
        # For development: allow all requests
        # TODO: Validate CF_Authorization JWT in production
        response = await call_next(request)
        return response