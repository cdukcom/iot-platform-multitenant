
import asyncio
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from db import tenants_collection
from middleware import FirebaseAuthMiddleware

app = FastAPI()
app.add_middleware(FirebaseAuthMiddleware)

@app.get("/")
def read_root():
    return {"message": "IoTaaS multitenant backend is running"}

@app.get("/ping-db")
async def ping_db():
    try:
        count = await tenants_collection.count_documents({})
        return {"status": "ok", "tenants_count": count}
    except Exception as e:
        return {"status": "error", "details": str(e)}

@app.on_event("startup")
async def startup_event():
    # Keep-alive dummy task for Railway
    async def dummy_keepalive():
        while True:
            await asyncio.sleep(60)

    asyncio.create_task(dummy_keepalive())

@app.get("/private")
async def private(request: Request):
    user = request.state.user
    if user:
        return JSONResponse(content={"message": "Authenticated", "uid": user.get("uid")})
    return JSONResponse(status_code=401, content={"error": "Unauthorized"})

