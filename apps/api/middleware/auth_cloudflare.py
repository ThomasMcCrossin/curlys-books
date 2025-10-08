"""
Cloudflare Access authentication middleware.
For Phase 1 development, this is a stub that allows all requests.
TODO: Implement proper JWT validation when deploying to production.
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class CloudflareAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, team_domain: str, audience: str):
        super().__init__(app)
        self.team_domain = team_domain
        self.audience = audience
    
    async def dispatch(self, request: Request, call_next):
        # For development: allow all requests
        # TODO: Validate CF_Authorization JWT in production
        # Should verify:
        # 1. JWT signature using Cloudflare's public keys
        # 2. audience matches self.audience
        # 3. issuer matches f"https://{self.team_domain}.cloudflareaccess.com"
        response = await call_next(request)
        return response
