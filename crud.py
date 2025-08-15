# 🔄 AVISO: Este archivo usa gRPC como vía principal para ChirpStack.
# Métodos REST solo se usan para funciones aún no migradas a gRPC (ej. AppKey, profiles).from bson import ObjectId

from datetime import datetime
from bson import ObjectId
from db import tenants_collection, users_collection, devices_collection, devicekeys_collection
from models import TenantModel, UserModel, DeviceModel, AlertModel, LogModel
from grpc import RpcError

# from chirpstack_gprc import client.get_device_profile_id_by_name
from chirpstack_grpc import ChirpstackGRPCClient


# ────────────────────────────────────────────────
# 🧱 BLOQUE: TENANTS
# ────────────────────────────────────────────────
async def create_tenant(data: TenantModel, owner_uid: str):
    """
    Crea primero el documento en Mongo (para mantener tu flujo actual),
    luego intenta crear el tenant en ChirpStack.
    Si gRPC falla, hace rollback en Mongo y lanza error para el frontend.
    """
    tenant = data.model_dump()
    tenant["owner_uid"] = owner_uid

    # 1) Insertar en Mongo
    result = await tenants_collection.insert_one(tenant)
    inserted_id = result.inserted_id

    # 2) Intentar en ChirpStack (gRPC)
    try:
        cs = ChirpstackGRPCClient()
        cs_resp = cs.create_tenant(
            name=tenant.get("name", ""),
            description=tenant.get("description", ""),
            can_have_gateways=tenant.get("can_have_gateways", True),
        )
        chirp_tenant_id = cs_resp.id

        # 3) Si gRPC OK, persistimos el id de ChirpStack en Mongo
        await tenants_collection.update_one(
            {"_id": inserted_id},
            {"$set": {"chirpstack_tenant_id": chirp_tenant_id}},
        )

        return str(inserted_id)

    except RpcError as e:
        # Rollback en Mongo si falla gRPC
        await tenants_collection.delete_one({"_id": inserted_id})
        # Mensaje claro hacia el frontend
        msg = e.details() or "Error gRPC al crear tenant en ChirpStack."
        raise ValueError(msg)

    except Exception as e:
        # Cualquier otro error inesperado: también rollback
        await tenants_collection.delete_one({"_id": inserted_id})
        raise ValueError(f"Error al crear tenant: {str(e)}")

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
    
    # 2️⃣ Intentar sincronización con ChirpStack vía gRPC
    try:
        dev_eui = device["dev_eui"]
        name = device["name"]
        description = device.get("description", "")
        device_type = device["type"]

        application_id = tenant.get("chirpstack_app_id") or "1"
        tenant_chirpstack_id = tenant.get("chirpstack_tenant_id")

        # a. Crear cliente gRPC
        client = ChirpstackGRPCClient()

        # b. Obtener Device Profile ID (por gRPC)
        profile_id = client.get_device_profile_id_by_name(device_type, tenant_chirpstack_id)

        # c. Crear dispositivo vía gRPC
        client = ChirpstackGRPCClient()
        client.create_device(
            dev_eui=dev_eui,
            name=name,
            description=description,
            application_id=application_id,
            device_profile_id=profile_id,
        )

        # d. Obtener AppKey desde Mongo
        key_doc = await devicekeys_collection.find_one({"type": device_type})
        app_key = key_doc["app_key"] if key_doc else "00000000000000000000000000000000"

        # e. Asignar claves OTAA (solo posible vía REST de momento)
        #from chirpstack_api_com import set_device_keys
        #set_device_keys(dev_eui, app_key)

    except Exception as e:
        print("⚠️ Error al sincronizar con ChirpStack:", str(e))
        import traceback
        traceback.print_exc()
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
