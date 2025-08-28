
import asyncio
import os, grpc
import subprocess, sys, json
import logging
import httpx
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Body, Query, Depends, HTTPException, APIRouter, Path
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from pymongo import MongoClient
from crud import delete_tenant_by_id
from grpc_auth_interceptor import ApiKeyAuthInterceptor
from datetime import datetime, timezone

# 📦 Módulos locales
from db import tenants_collection, devicekeys_collection, users_collection, devices_collection
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
    
# 🧪 Smoke gRPC (sin chirpstack_api para evitar conflictos de proto)
@app.get("/_gw_smoke", include_in_schema=False)
async def gw_smoke():
    try:
        c = ChirpstackGRPCClient()  # usa tus stubs locales
        resp = c.list_tenants(limit=1)
        return {
            "ok": True,
            "checked": "tenant_list",
            "total_count": getattr(resp, "total_count", None),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    
@app.get("/_gw_list_sidecar", include_in_schema=False)
async def gw_list_sidecar():
    try:
        proc = subprocess.run(
            [sys.executable, "gw_sidecar.py", "list", "--limit", "1"],
            capture_output=True, text=True, check=True
        )
        return json.loads(proc.stdout or "{}")
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": e.stderr or str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    
@app.post("/_gw_create_sidecar", include_in_schema=False)
async def _gw_create_sidecar(body: dict):
    # body: { tenant_id, gateway_id, name, description?, tags? (dict) }
    try:
        tenant_id = body["tenant_id"]
        gateway_id = body["gateway_id"]
        name = body["name"]
    except KeyError as e:
        return {"ok": False, "error": f"missing field: {e.args[0]}"}

    args = [sys.executable, "-m", "gw_sidecar", "create",
            "--tenant-id", tenant_id,
            "--gateway-id", gateway_id,
            "--name", name]

    if body.get("description"):
        args += ["--description", body["description"]]

    # convertir tags dict -> "k=v,k2=v2"
    if isinstance(body.get("tags"), dict) and body["tags"]:
        tag_str = ",".join(f"{k}={v}" for k, v in body["tags"].items())
        args += ["--tags", tag_str]

    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr or proc.stdout}

    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"ok": False, "error": f"bad sidecar json: {proc.stdout}"}

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


# 📡 Gestión de Gateways
@app.post("/gateways")
async def create_gateway_api(data: dict = Body(...), request: Request = None):
    # auth
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # payload
    tenant_mongo_id = data.get("tenant_id")
    gw_eui = (data.get("gateway_id") or "").strip().upper()
    name = (data.get("name") or "").strip()
    description = data.get("description") or ""
    tags = data.get("tags") or {}

    # validaciones mínimas
    if not tenant_mongo_id or not gw_eui or not name:
        raise HTTPException(status_code=400, detail="tenant_id, gateway_id y name son obligatorios")
    if len(gw_eui) != 16:
        raise HTTPException(status_code=400, detail="gateway_id debe tener 16 hex")

    # tenant dueño?
    try:
        oid = ObjectId(tenant_mongo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="tenant_id inválido")

    tenant = await tenants_collection.find_one({"_id": oid, "owner_uid": user["uid"]})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado o no autorizado")

    chirp_tenant_id = tenant.get("chirpstack_tenant_id")
    if not chirp_tenant_id:
        raise HTTPException(status_code=400, detail="Tenant sin chirpstack_tenant_id")

    # evitar duplicado en Mongo
    exists = await devices_collection.find_one({
        "tenant_id": tenant_mongo_id,
        "type": "gateway",
        "dev_eui": gw_eui,
    })
    if exists:
        raise HTTPException(status_code=409, detail="Gateway ya existe en Mongo para este tenant")

    # crear en ChirpStack vía sidecar (import isolation)
    try:
        js = await _gw_create_sidecar({
            "tenant_id": chirp_tenant_id,
            "gateway_id": gw_eui,
            "name": name,
            "description": description,
            "tags": tags,
        })
        if not js.get("ok"):
           # deja pasar el error funcional con 400
           detail = js.get("error") or "Error al crear gateway en ChirpStack (sidecar)"
           raise HTTPException(status_code=400, detail=f"ChirpStack error: {detail}")
    except HTTPException:
        # respeta los 400/401/... que tú mismo generes
        raise
    except Exception as e:
        # errores de transporte/inesperados → 502
        raise HTTPException(status_code=502, detail=f"Sidecar error: {e}")

    # reflejar en Mongo (colección devices, como ya usa tu FE)
    doc = {
        "tenant_id": tenant_mongo_id,
        "dev_eui": gw_eui,
        "name": name,
        "type": "gateway",
        "status": "active",
        "location": data.get("location") or "",
        "created_at": datetime.now(timezone.utc),
        "meta": {
            "chirpstack_tenant_id": chirp_tenant_id,
            "description": description,
            "tags": tags,
        },
    }
    ins = await devices_collection.insert_one(doc)

    return {
        "ok": True,
        "id": str(ins.inserted_id),
        "gateway_id": gw_eui,
        "tenant_id": tenant_mongo_id,
    }

@app.post("/_gw_delete_sidecar", include_in_schema=False)
async def _gw_delete_sidecar(body: dict):
    # body: { gateway_id }
    try:
        gateway_id = body["gateway_id"]
    except KeyError as e:
        return {"ok": False, "error": f"missing field: {e.args[0]}"}

    args = [sys.executable, "-m", "gw_sidecar", "delete",
            "--gateway-id", gateway_id]

    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        # sidecar puede imprimir JSON de error o solo texto
        try:
            return json.loads(proc.stdout or proc.stderr or "{}")
        except Exception:
            return {"ok": False, "error": proc.stderr or proc.stdout or "unknown delete error"}

    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"ok": False, "error": f"bad sidecar json: {proc.stdout}"}

@app.delete("/gateways/{gateway_id}")
async def delete_gateway_api(
    gateway_id: str,
    tenant_id: str = Query(..., description="tenant_id (Mongo) dueño del gateway"),
    confirm: bool = Query(False, description="Debe ser true para confirmar el borrado"),
    request: Request = None
):
    # Auth
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not confirm:
        raise HTTPException(status_code=400, detail="Falta confirmación (?confirm=true)")

    # Validaciones
    gw_eui = (gateway_id or "").strip().upper()
    if len(gw_eui) != 16 or any(c not in "0123456789ABCDEF" for c in gw_eui):
        raise HTTPException(status_code=400, detail="gateway_id debe ser 16 hex (0-9, A-F)")

    try:
        oid = ObjectId(tenant_id)
    except Exception:
        raise HTTPException(status_code=400, detail="tenant_id inválido")

    # Tenant dueño
    tenant = await tenants_collection.find_one({"_id": oid, "owner_uid": user["uid"]})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado o no autorizado")

    # Buscar gateway en Mongo (colección devices con type=gateway)
    doc = await devices_collection.find_one({
        "tenant_id": tenant_id,
        "type": "gateway",
        "dev_eui": gw_eui
    })

    # 1) Borrar en ChirpStack (vía sidecar) — idempotente
    try:
        js = await _gw_delete_sidecar({"gateway_id": gw_eui})
        if not js.get("ok"):
            # Si el GW no existe en ChirpStack, seguimos (idempotente)
            # Ajusta el mensaje según lo que devuelva el sidecar
            msg = (js.get("error") or "").lower()
            if "not found" not in msg and "does not exist" not in msg:
                raise HTTPException(status_code=502, detail=f"ChirpStack delete error: {js.get('error')}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sidecar delete error: {e}")

    # 2) Borrar en Mongo (idempotente)
    if doc:
        res = await devices_collection.delete_one({"_id": doc["_id"]})
        deleted = res.deleted_count
    else:
        deleted = 0  # ya no estaba en Mongo

    return {
        "ok": True,
        "gateway_id": gw_eui,
        "tenant_id": tenant_id,
        "mongo_deleted": deleted
    }

@app.get("/gateways")
async def list_gateways_api(tenant_id: str = Query(...), request: Request = None):
    user = request.state.user
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        oid = ObjectId(tenant_id)
    except Exception:
        raise HTTPException(status_code=400, detail="tenant_id inválido")

    tenant = await tenants_collection.find_one({"_id": oid, "owner_uid": user["uid"]})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado o no autorizado")

    cursor = devices_collection.find({"tenant_id": tenant_id, "type": "gateway"})
    out = []
    async for d in cursor:
        out.append({
            "id": str(d["_id"]),
            "dev_eui": d.get("dev_eui"),
            "name": d.get("name"),
            "status": d.get("status", "active"),
            "location": d.get("location", ""),
        })
    return {"gateways": out}

@app.get("/_gw_list_sidecar", include_in_schema=False)
async def gw_list_sidecar():
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "gw_sidecar", "list", "--limit", "1"],
            capture_output=True, text=True, check=True
        )
        return json.loads(proc.stdout or "{}")
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": e.stderr or str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# 📡 Gestión de Dispositivos
# en startup (si tienes acceso al motor/colección aquí):
# await devices_collection.create_index(
#     [("tenant_id", 1), ("type", 1), ("dev_eui", 1)],
#     unique=True,
#     name="uniq_tenant_type_dev_eui"
# )

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
    db = MongoClient(os.getenv("MONGO_URI"))["PLATAFORMA_IOT"]
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