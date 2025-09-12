import logging
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from auth import verify_token

# Configurar logger para este módulo
logger = logging.getLogger(__name__)

# ➕ rutas abiertas (sin auth)
OPEN_PATHS = {
    "/", "/ping-db",
    # --- Gateway ---
    "/_gw_smoke", "/_gw_list_sidecar", "/_gw_create_sidecar",
    # --- Device Profile ---
    "/_dp_smoke", "/_dp_list_sidecar", "/_dp_get_sidecar",
    "/_dp_cache_install", "/_dp_cache_get", "/_dp_cache_refresh",
    "/_dp_create_from_cache", 
    # --- Sensores ---
    "/_dev_smoke_create",
    # opcional: docs mientras probamos
    "/docs", "/openapi.json", "/redoc",
    "/favicon.ico",
}

class FirebaseAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Permitir sin autenticación: rutas públicas o método OPTIONS
        if request.method in {"OPTIONS", "HEAD"} or path in OPEN_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")

        # Log dentro del contexto de la petición
        logger.info(f"[AUTH] {request.method} {path} - Authorization present? {bool(auth_header)}")

        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

        token = auth_header.split(" ", 1)[1]
        decoded_token = verify_token(token)
        if not decoded_token:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        request.state.user = decoded_token  # Puedes usar esto en tus endpoints
        return await call_next(request)
