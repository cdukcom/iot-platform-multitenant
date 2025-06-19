
import asyncio
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from db import tenants_collection
from middleware import FirebaseAuthMiddleware
from fastapi import Body, HTTPException
from crud import create_tenant
from models import TenantModel

app = FastAPI()

# 👇 Añade este bloque para permitir conexión desde localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Permite el frontend en desarrollo
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.post("/tenants")
async def create_tenant_endpoint(data: dict = Body(...), request: Request = None):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # ✅ Agrega el UID correctamente
    tenant_data = TenantModel(name=data["name"])
    tenant_id = await create_tenant(tenant_data, owner_uid=user["uid"])
    return {"tenant_id": tenant_id}


@app.get("/tenants")
async def list_tenants(request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    cursor = tenants_collection.find({"owner_uid": user["uid"]})
    tenants = []
    async for doc in cursor:
        tenants.append({
            "id": str(doc["_id"]),
            "name": doc["name"],
        })

    return {"tenants": tenants}
