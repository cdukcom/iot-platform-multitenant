from bson import ObjectId
from db import tenants_collection, users_collection, devices_collection
from models import TenantModel, UserModel, DeviceModel, AlertModel, LogModel
from datetime import datetime

# ---------- Tenants ----------
async def create_tenant(data: TenantModel, owner_uid: str):
    tenant = data.dict()
    tenant["owner_uid"] = owner_uid  # ✅ Agregar UID del usuario autenticado
    result = await tenants_collection.insert_one(tenant)
    return str(result.inserted_id)

async def list_devices_by_tenant(tenant_id: str):
    cursor = devices_collection.find({"tenant_id": tenant_id})
    return [doc async for doc in cursor]

# ---------- Users ----------
async def create_user(data: UserModel):
    user = data.dict()
    result = await users_collection.insert_one(user)
    return str(result.inserted_id)

async def get_user_by_uid(uid: str):
    return await users_collection.find_one({"uid": uid})

# ---------- Devices ----------
async def register_device(data: DeviceModel):
    device = data.dict()
    
    # Contar cuántos dispositivos tiene este tenant
    device_count = await devices_collection.count_documents({"tenant_id": device["tenant_id"]})
    
    # Obtener límite según plan
    tenant = await tenants_collection.find_one({"_id": ObjectId(device["tenant_id"])})
    if not tenant:
        raise ValueError("Tenant no encontrado")
    
    max_allowed = tenant.get("max_devices", 5)
    if device_count >= max_allowed:
        raise ValueError("Límite de dispositivos alcanzado para este plan")

    result = await devices_collection.insert_one(device)
    return str(result.inserted_id)

# ---------- Alertas ----------
async def trigger_alert(data: AlertModel, alerts_collection):
    alert = data.dict()
    result = await alerts_collection.insert_one(alert)
    return str(result.inserted_id)

# ---------- Logs ----------
async def log_action(data: LogModel, logs_collection):
    log = data.dict()
    result = await logs_collection.insert_one(log)
    return str(result.inserted_id)
