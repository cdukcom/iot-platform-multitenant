from bson import ObjectId
from datetime import datetime

from db import tenants_collection, users_collection, devices_collection, devicekeys_collection
from models import TenantModel, UserModel, DeviceModel, AlertModel, LogModel

# 🔗 Importar API de ChirpStack
from chirpstack_api_com import (
    get_device_profile_by_name,
)

# ────────────────────────────────────────────────
# 🧱 BLOQUE: TENANTS
# ────────────────────────────────────────────────
async def create_tenant(data: TenantModel, owner_uid: str):
    tenant = data.model_dump()
    tenant["owner_uid"] = owner_uid
    result = await tenants_collection.insert_one(tenant)
    return str(result.inserted_id)

# ────────────────────────────────────────────────
# 📦 BLOQUE: DEVICES
# ────────────────────────────────────────────────
async def register_device(data: DeviceModel):
    device = data.model_dump()

    # Convertir gateway_id a ObjectId si está presente
    if "gateway_id" in device and device["gateway_id"]:
        device["gateway_id"] = ObjectId(device["gateway_id"])
    
    # Contar cuántos dispositivos tiene este tenant
    device_count = await devices_collection.count_documents({"tenant_id": device["tenant_id"]})
    
    # Obtener límite según plan
    tenant = await tenants_collection.find_one({"_id": ObjectId(device["tenant_id"])})
    if not tenant:
        raise ValueError("Tenant no encontrado")
    
    max_allowed = tenant.get("max_devices", 5)
    if device_count >= max_allowed:
        raise ValueError("Límite de dispositivos alcanzado para este plan")

    # 1️⃣ Registrar en MongoDB
    result = await devices_collection.insert_one(device)
    device_id = str(result.inserted_id)

    # 2️⃣ Crear en ChirpStack
    try:
        dev_eui = device["dev_eui"]
        name = device["name"]
        device_type = device["type"]

        # a. Obtener Device Profile ID desde ChirpStack según tipo (ej. MG6, LBM01)
        #profile_id = get_device_profile_by_name(device_type)
        tenant_chirpstack_id = tenant.get("chirpstack_tenant_id")
        profile_id = get_device_profile_by_name(device_type, tenant_chirpstack_id)
        if not profile_id:
            raise ValueError(f"Device profile no encontrado en ChirpStack para: {device_type}")

        # b. Buscar o usar ID de aplicación por defecto
        application_id = tenant.get("chirpstack_app_id") or "1"  # Puedes ajustar esta lógica más adelante

        # c. Crear dispositivo en ChirpStack
        chirp_device = create_device(dev_eui, name, application_id, profile_id)
        if not chirp_device:
            raise ValueError("Error al crear el dispositivo en ChirpStack")

        # d. Obtener AppKey desde MongoDB o hardcode
        # (Asumimos que tienes una colección 'devicekeys' en Mongo con campos: type, app_key)
        key_doc = await devicekeys_collection.find_one({"type": device_type})
        app_key = key_doc["app_key"] if key_doc else "00000000000000000000000000000000"

        # e. Asignar claves OTAA
        chirp_keys = set_device_keys(dev_eui, app_key)
        if not chirp_keys:
            raise ValueError("Error al asignar claves OTAA en ChirpStack")

    except Exception as e:
        print("⚠️ Error al sincronizar con ChirpStack:", str(e))
        import traceback
        traceback.print_exc()  # 👈 Esto imprimirá detalles del error exacto
        await devices_collection.delete_one({"_id": ObjectId(device_id)})
        raise ValueError("Fallo la integración con ChirpStack. Dispositivo no creado.")
    return device_id

async def list_devices_by_tenant(tenant_id: str):
    cursor = devices_collection.find({"tenant_id": tenant_id})
    return [doc async for doc in cursor]

# ────────────────────────────────────────────────
# 👤 BLOQUE: USERS
# ────────────────────────────────────────────────
async def create_user(data: UserModel):
    user = data.model_dump()
    result = await users_collection.insert_one(user)
    return str(result.inserted_id)

async def get_user_by_uid(uid: str):
    return await users_collection.find_one({"uid": uid})

# ────────────────────────────────────────────────
# 🚨 BLOQUE: ALERTAS
# ────────────────────────────────────────────────
async def trigger_alert(data: AlertModel, alerts_collection):
    alert = data.model_dump()
    result = await alerts_collection.insert_one(alert)
    return str(result.inserted_id)

# ────────────────────────────────────────────────
# 🪵 BLOQUE: LOGS (para auditoría futura)
# ────────────────────────────────────────────────
async def log_action(data: LogModel, logs_collection):
    log = data.model_dump()
    result = await logs_collection.insert_one(log)
    return str(result.inserted_id)
