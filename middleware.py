from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from auth import verify_token

class FirebaseAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ["/", "/ping-db"]:
            # Permitimos estas rutas sin autenticación
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

        token = auth_header.split(" ")[1]
        decoded_token = verify_token(token)
        if not decoded_token:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        request.state.user = decoded_token  # Puedes usar esto en tus endpoints
        return await call_next(request)
