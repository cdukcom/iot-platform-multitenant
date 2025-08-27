
import asyncio
import os, grpc
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Body, Query, Depends, HTTPException, APIRouter, Path
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from pymongo import MongoClient
from crud import delete_tenant_by_id
from grpc_auth_interceptor import ApiKeyAuthInterceptor

# 📦 Módulos locales
from db import tenants_collection, devicekeys_collection, users_collection
from middleware import FirebaseAuthMiddleware
from crud import create_tenant, register_device, list_devices_by_tenant, trigger_alert
from models import TenantModel, DeviceModel, AlertModel, UserRegisterModel
from chirpstack_grpc import ChirpstackGRPCClient

#debug encontrar error silencioso
print("[DEBUG] Iniciando iotaas.py")

# 🔧 Cargar configuración
load_dotenv()

# 📝 Logging (desactivado por defecto, activar cuando se necesite)
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
# logger.info("🌐 Iniciando servicio iotaas.py...")

# 🌀 Lifespan: equivalente a @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep-alive dummy task for Railway
    async def dummy_keepalive():
        while True:
            await asyncio.sleep(60)
    asyncio.create_task(dummy_keepalive())
    yield  # Aquí continúa el ciclo de vida normal de FastAPI

#debug error silencioso railway
print("[DEBUG] yield ejecutado en lifespan")

# 🚀 Inicializar la aplicación
app = FastAPI(lifespan=lifespan)

#debug detección error silencioso.
print("[DEBUG] FastAPI inicializada")

# 🌐 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://app.duke-villa.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔐 Middleware de autenticación
app.add_middleware(FirebaseAuthMiddleware)

#detección error silencio con debug
print("[DEBUG] Middleware cargado")

# 🧪 Rutas públicas de prueba
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
    
@app.get("/_gw_smoke", include_in_schema=False)
async def gw_smoke():
    try:
        # imports perezosos: solo para esta ruta
        from chirpstack_api.api import gateway_pb2 as gw_pb2
        from chirpstack_api.api import gateway_pb2_grpc as gw_pb2_grpc

        addr = os.getenv("CHIRPSTACK_GRPC_ADDRESS", "localhost:8080")
        apikey = os.getenv("CHIRPSTACK_API_KEY")
        if not apikey:
            return {"ok": False, "error": "CHIRPSTACK_API_KEY missing"}

        channel = grpc.intercept_channel(
            grpc.insecure_channel(addr),
            ApiKeyAuthInterceptor(apikey),
        )
        stub = gw_pb2_grpc.GatewayServiceStub(channel)
        resp = stub.List(gw_pb2.ListGatewaysRequest(limit=1))
        return {"ok": True, "total_count": getattr(resp, "total_count", None)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# 🔒 Rutas protegidas (Autenticadas)
@app.get("/private")
async def private(request: Request):
    user = request.state.user
    if user:
        return JSONResponse(content={"message": "Authenticated", "uid": user.get("uid")})
    return HTTPException(status_code=401, content={"error": "Unauthorized"})

@app.post("/usuarios")
async def register_user(request: Request, body: dict = Body(...)):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Correo no verificado")

    uid = user["uid"]
    email = user["email"]

    # Verifica si ya está en Mongo
    existing = await users_collection.find_one({"uid": uid})
    if existing:
        return {"message": "Usuario ya registrado en MongoDB"}

    user_data = UserRegisterModel(
        uid=uid,
        email=email,
        role=body.get("role", "user"),
        plan=body.get("plan", "trial"),
        phone=body.get("phone"),
        full_name=body.get("full_name")
    )

    await users_collection.insert_one(user_data.model_dump())
    return {"message": "Usuario registrado exitosamente", "uid": uid}

# 🧱 Gestión de Tenants
@app.post("/tenants")
async def create_tenant_endpoint(data: dict = Body(...), request: Request = None):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
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

@app.delete("/tenants/{tenant_id}")
async def delete_tenant_endpoint(
    tenant_id: str = Path(...),
    request: Request = None,
    purge_devices: bool = True,
):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 1) Validar ID y propiedad antes de borrar
    try:
        oid = ObjectId(tenant_id)
    except Exception:
        raise HTTPException(status_code=400, detail="tenant_id inválido")

    tenant = await tenants_collection.find_one({"_id": oid, "owner_uid": user["uid"]})
    if not tenant:
        # No existe o no pertenece al usuario autenticado
        raise HTTPException(status_code=404, detail="Comunidad no encontrada o no autorizada.")

    # 2) Ejecutar borrado centralizado (Mongo + ChirpStack)
    try:
        result = await delete_tenant_by_id(tenant_id, purge_devices=purge_devices)
        # result es un dict: {"ok": True, "chirpstack_deleted": bool, "mongo_devices_deleted": int, "tenant_id": str}
        return result
    except ValueError as e:
        # Errores esperables (ids inválidos, fallo gRPC, etc.)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Error interno al eliminar tenant")


# 📡 Gestión de Dispositivos
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
        print("❌ ValueError:", str(ve))
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        print("❌ Error general:", str(e))
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
                "_id": str(device["_id"]),
                "id": str(device["_id"]),
                "dev_eui": device.get("dev_eui", ""),
                "name": device["name"],
                "type": device["type"],
                "status": device["status"],
                "location": device.get("location", "N/A"),
                "created_at": device.get("created_at"),
                "gateway_id": str(device.get("gateway_id")) if device.get("gateway_id") else None
            }
            for device in devices
        ]
    }

@app.delete("/devices/{device_id}")
async def delete_device(device_id: str, confirm: bool = Query(False), request: Request = None):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not confirm:
        raise HTTPException(status_code=400, detail="Falta confirmación para eliminar el dispositivo.")
    from db import devices_collection
    result = await devices_collection.delete_one({"_id": ObjectId(device_id)})
    if result.deleted_count == 1:
        return {"message": "Dispositivo eliminado correctamente"}
    raise HTTPException(status_code=404, detail="Dispositivo no encontrado")

@app.get("/devices/{dev_eui}/data")
def get_device_data(dev_eui: str):
    db = MongoClient(os.getenv("MONGODB_URI"))["PLATAFORMA_IOT"]
    data = list(db["mqtt_data"].find({"device_eui": dev_eui}))
    if not data:
        raise HTTPException(status_code=404, detail="No se encontraron datos para este dispositivo.")
    for d in data:
        d["_id"] = str(d["_id"])
        if "timestamp" in d:
            d["timestamp"] = str(d["timestamp"])
    return {"device_eui": dev_eui, "data": data}

@app.post("/device-keys")
async def save_device_key(data: dict = Body(...), request: Request = None):
    """
    Permite guardar una AppKey para un tipo de dispositivo (por ejemplo, MG6 o LBM01).
    Esta clave luego se usará automáticamente al registrar un dispositivo de ese tipo.
    """
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    device_type = data.get("type")
    app_key = data.get("app_key")

    if not device_type or not app_key:
        raise HTTPException(status_code=400, detail="Faltan campos obligatorios")

    result = await devicekeys_collection.update_one(
        {"type": device_type},
        {"$set": {"app_key": app_key}},
        upsert=True
    )

    return {"message": "Clave OTAA guardada correctamente", "matched": result.matched_count}

@app.get("/grpc/device/{dev_eui}")
async def grpc_get_device(dev_eui: str):
    try:
        client = ChirpstackGRPCClient()
        device = client.get_device(dev_eui)
        return {
            "dev_eui": device.dev_eui,
            "name": device.name,
            "description": device.description,
            "application_id": device.application_id,
            "device_profile_id": device.device_profile_id,
        }
    except grpc.RpcError as e:
        raise HTTPException(status_code=400, detail=f"gRPC Error: {e.details()}")

@app.post("/grpc/device/")
async def grpc_create_device(payload: dict):
    try:
        client = ChirpstackGRPCClient()
        client.create_device(
            dev_eui=payload["dev_eui"],
            name=payload["name"],
            description=payload.get("description", ""),
            application_id=payload["application_id"],
            device_profile_id=payload["device_profile_id"],
        )
        return {"message": "Device created via gRPC"}
    except grpc.RpcError as e:
        raise HTTPException(status_code=400, detail=f"gRPC Error: {e.details()}")

@app.delete("/grpc/device/{dev_eui}")
async def grpc_delete_device(dev_eui: str):
    try:
        client = ChirpstackGRPCClient()
        client.delete_device(dev_eui)
        return {"message": "Device deleted via gRPC"}
    except grpc.RpcError as e:
        raise HTTPException(status_code=400, detail=f"gRPC Error: {e.details()}")


# 🚨 Gestión de Alertas
@app.post("/alerts")
async def create_alert_endpoint(data: dict = Body(...), request: Request = None):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    alert_data = AlertModel(**data)
    from db import alerts_collection
    alert_id = await trigger_alert(alert_data, alerts_collection)
    return {"alert_id": alert_id}

@app.get("/alerts/{tenant_id}")
async def get_alerts_for_tenant(tenant_id: str, request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    from db import alerts_collection
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

@app.put("/alerts/{alert_id}/close")
async def close_alert(alert_id: str, request: Request):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    from db import alerts_collection
    result = await alerts_collection.update_one(
        {"_id": ObjectId(alert_id)},
        {"$set": {"status": "closed"}}
    )
    if result.modified_count == 1:
        return {"message": "Alerta cerrada exitosamente"}
    raise HTTPException(status_code=404, detail="Alerta no encontrada o ya cerrada")

#debug problema silencioso railway
print("[DEBUG] Fin de iotaas.py - app debería estar corriendo")

import sys
import traceback

try:
    print("[DEBUG] iotaas.py listo para levantar FastAPI")
except Exception as e:
    print("[ERROR] Excepción atrapada antes de levantar app:", str(e))
    traceback.print_exc(file=sys.stdout)