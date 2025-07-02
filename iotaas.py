
import asyncio
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from db import tenants_collection
from middleware import FirebaseAuthMiddleware
from fastapi import Body, HTTPException
from crud import create_tenant
from crud import register_device, list_devices_by_tenant, trigger_alert
from models import TenantModel
from models import DeviceModel, AlertModel

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
            "name": doc.get("name", ""),
            "plan": doc.get("plan", "free"),
            "created_at": doc.get("created_at", None)
        })

    return {"tenants": tenants}

@app.post("/devices")
async def register_device_endpoint(data: dict = Body(...), request: Request = None):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        device_data = DeviceModel(**data)
        device_id = await register_device(device_data)
        return {"device_id": device_id}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error interno al registrar el dispositivo")

@app.get("/devices/{tenant_id}")
async def get_devices_for_tenant(tenant_id: str, request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    devices = await list_devices_by_tenant(tenant_id)
    return {
        "devices": [
            {
                "id": str(device["_id"]),
                "dev_eui": device.get("dev_eui", ""),
                "name": device["name"],
                "type": device["type"],
                "status": device["status"],
                "location": device.get("location", "N/A"),
                "created_at": device.get("created_at"),
                "gateway_id": device.get("gateway_id")
            }
            for device in devices
        ]
    }

@app.post("/alerts")
async def create_alert_endpoint(data: dict = Body(...), request: Request = None):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        alert_data = AlertModel(**data)
        from db import alerts_collection
        alert_id = await trigger_alert(alert_data, alerts_collection)
        return {"alert_id": alert_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error al crear alerta")

@app.get("/alerts/{tenant_id}")
async def get_alerts_for_tenant(tenant_id: str, request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        alerts_cursor = alerts_collection.find({"tenant_id": tenant_id})
        alerts = []
        async for alert in alerts_cursor:
            alerts.append({
                "id": str(alert["_id"]),
                "device_id": alert.get("device_id"),
                "timestamp": alert.get("timestamp"),
                "status": alert.get("status"),
                "location": alert.get("location"),
                "message": alert.get("message"),
                "assigned_to": alert.get("assigned_to")
            })
        return {"alerts": alerts}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error al obtener alertas")

@app.put("/alerts/{alert_id}/close")
async def close_alert(alert_id: str, request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        from db import alerts_collection
        result = await alerts_collection.update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {"status": "closed"}}
        )
        if result.modified_count == 1:
            return {"message": "Alerta cerrada exitosamente"}
        else:
            raise HTTPException(status_code=404, detail="Alerta no encontrada o ya cerrada")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al cerrar la alerta: {str(e)}")
