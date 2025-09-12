# 🔄 AVISO: Este archivo usa gRPC como vía principal para ChirpStack.
# Métodos REST solo se usan para funciones aún no migradas a gRPC (ej. AppKey, profiles).

import asyncio, sys, json, re
from datetime import datetime, timezone
from bson import ObjectId
from db import tenants_collection, users_collection, devices_collection, devicekeys_collection, device_profiles_collection, dp_templates_cache_collection
from models import TenantModel, UserModel, DeviceModel, AlertModel, LogModel
from grpc import RpcError

# from chirpstack_gprc import client.get_device_profile_id_by_name
from chirpstack_grpc import ChirpstackGRPCClient, compose_tenant_name

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
        user_doc = await users_collection.find_one({"uid": owner_uid})
        user_email = (user_doc.get("email") if user_doc else "") or owner_uid
        composed_name = compose_tenant_name(user_email, tenant.get("name", ""))
        cs_resp = cs.create_tenant(
            name=composed_name,
            description=tenant.get("description", ""),
            can_have_gateways=tenant.get("can_have_gateways", True),
        )
        chirp_tenant_id = cs_resp.id

        # NUEVO: asegurar/crear la Application con el mismo nombre del tenant
        chirp_app_id = cs.ensure_application_same_as_tenant(chirp_tenant_id, composed_name)

        # 3) Si gRPC OK, persistimos el id de ChirpStack en Mongo
        await tenants_collection.update_one(
            {"_id": inserted_id},
            {"$set": {
                "chirpstack_tenant_id": chirp_tenant_id,
                "chirpstack_tenant_name": composed_name,
                "chirpstack_app_id": chirp_app_id,
            }},
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

async def delete_tenant_by_id(tenant_id: str, purge_devices: bool = True):
    """
    Elimina un tenant por su _id de Mongo.
    - Si existe chirpstack_tenant_id, intenta eliminarlo en ChirpStack vía gRPC.
    - Luego elimina los dispositivos del tenant en Mongo (opcional).
    - Finalmente elimina el documento del tenant en Mongo.
    Lanza ValueError con mensaje claro si algo falla.
    """
    # 1) Buscar tenant en Mongo
    try:
        oid = ObjectId(tenant_id)
    except Exception:
        raise ValueError("tenant_id inválido")

    tenant = await tenants_collection.find_one({"_id": oid})
    if not tenant:
        raise ValueError("Tenant no encontrado")

    chirp_tenant_id = tenant.get("chirpstack_tenant_id")

    # 2) Intentar eliminar en ChirpStack (si hay id)
    chirpstack_deleted = False
    if chirp_tenant_id:
        try:
            cs = ChirpstackGRPCClient()
            # Ajusta el nombre del método si en tu cliente es distinto.
            # Se asume un método delete_tenant(chirp_tenant_id: str) -> None
            cs.delete_tenant(chirp_tenant_id)
            chirpstack_deleted = True
        except RpcError as e:
            # No detiene el borrado en Mongo si decides seguir; si prefieres abortar, lanza el error.
            msg = e.details() or "Error gRPC al eliminar tenant en ChirpStack."
            raise ValueError(msg)
        except AttributeError:
            # Tu cliente no tiene el método esperado
            raise ValueError("El cliente gRPC no implementa delete_tenant(). Revísalo en chirpstack_grpc.py")

    # 3) Borrar dispositivos del tenant en Mongo (opcional)
    mongo_devices_deleted = 0
    if purge_devices:
        res_dev = await devices_collection.delete_many({"tenant_id": tenant_id})
        mongo_devices_deleted = res_dev.deleted_count

    # 4) Borrar tenant en Mongo
    res_tenant = await tenants_collection.delete_one({"_id": oid})
    if res_tenant.deleted_count != 1:
        raise ValueError("No se pudo eliminar el tenant en Mongo")

    return {
        "ok": True,
        "chirpstack_deleted": chirpstack_deleted,
        "mongo_devices_deleted": mongo_devices_deleted,
        "tenant_id": tenant_id,
    }

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

# ────────────────────────────────────────────────
# 📄 BLOQUE: DEVICE PROFILES (DP) – via dp_sidecar
# ────────────────────────────────────────────────

HEX24 = re.compile(r"^[0-9a-fA-F]{24}$")

async def _resolve_cs_tenant_id(tenant_id: str) -> str:
    """
    Acepta:
      - tenant_id de Mongo (ObjectId de 24 hex) → busca chirpstack_tenant_id en la colección tenants
      - tenant_id de ChirpStack directamente → lo retorna tal cual
    """
    if HEX24.match(tenant_id):
        doc = await tenants_collection.find_one({"_id": ObjectId(tenant_id)})
        if not doc or not doc.get("chirpstack_tenant_id"):
            raise ValueError("Tenant Mongo sin chirpstack_tenant_id")
        return doc["chirpstack_tenant_id"]
    return tenant_id

async def _dp_sidecar_get(name: str) -> dict:
    """Ejecuta: python -m dp_sidecar get --name <template>"""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "dp_sidecar", "get", "--name", name,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        return {"ok": False, "error": (err.decode() or out.decode() or "dp_sidecar get error")}
    try:
        return json.loads(out or b"{}")
    except Exception:
        return {"ok": False, "error": "dp_sidecar get: bad JSON"}

async def _dp_sidecar_create_from_template(cs_tenant_id: str, profile_name: str, template: dict) -> dict:
    """Ejecuta: python -m dp_sidecar create-from-template --tenant-id ... --profile-name ... --template-json ..."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "dp_sidecar", "create-from-template",
        "--tenant-id", cs_tenant_id,
        "--profile-name", profile_name,
        "--template-json", json.dumps(template),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        return {"ok": False, "error": (err.decode() or out.decode() or "dp_sidecar create error")}
    try:
        return json.loads(out or b"{}")
    except Exception:
        return {"ok": False, "error": "dp_sidecar create: bad JSON"}

async def upsert_device_profile_from_template_name(
    tenant_id: str,            # MongoId o tenant_id de ChirpStack
    model: str,                # p.ej. "SE-LBM01"
    template_name: str,        # p.ej. "LBM01"
    profile_name: str,         # p.ej. "dp-se-lbm01"
) -> dict:
    """
    Idempotente por índice único (tenant_id, model).
    Flujo:
      1) Si existe en Mongo → reuse.
      2) Lee template de caché; si no, llama dp_sidecar get.
      3) Crea Device Profile en ChirpStack (dp_sidecar create-from-template).
      4) Guarda snapshot en Mongo.
    Requiere ENV: CHIRPSTACK_API_KEY y CHIRPSTACK_GRPC_ADDRESS.
    """
    model = (model or "").strip().upper()
    if not (tenant_id and model and template_name and profile_name):
        return {"ok": False, "code": "bad_request", "error": "tenant_id, model, template_name, profile_name son obligatorios"}

    # 1) idempotencia
    existing = await device_profiles_collection.find_one({"tenant_id": tenant_id, "model": model})
    if existing:
        return {
            "ok": True, "action": "reused",
            "tenant_id": tenant_id, "model": model,
            "profile_name": existing.get("profile_name"),
            "device_profile_id": existing.get("device_profile_id"),
        }

    # 2) tenant de ChirpStack
    cs_tenant_id = await _resolve_cs_tenant_id(tenant_id)

    # 3) template (cache → sidecar)
    cache_doc = await dp_templates_cache_collection.find_one({"name": template_name})
    if cache_doc:
        template = cache_doc["template"]
    else:
        tpl = await _dp_sidecar_get(template_name)
        if not tpl.get("ok"):
            return {"ok": False, "code": "template_not_found", "error": tpl.get("error")}
        template = tpl["template"]
        now_iso = datetime.now(timezone.utc).isoformat()
        await dp_templates_cache_collection.update_one(
            {"name": template_name},
            {"$set": {"name": template_name, "template": template, "updated_at": now_iso}},
            upsert=True,
        )

    # 4) crear DP en ChirpStack
    created = await _dp_sidecar_create_from_template(cs_tenant_id, profile_name, template)
    if not created.get("ok"):
        return {"ok": False, "code": "chirpstack_error", "error": created.get("error")}
    dp_id = created.get("device_profile_id")

    # 5) persistir snapshot en Mongo
    now = datetime.now(timezone.utc)
    doc = {
        "tenant_id": tenant_id,
        "chirpstack_tenant_id": cs_tenant_id,
        "model": model,
        "template_name": template_name,
        "profile_name": profile_name,
        "device_profile_id": dp_id,
        "created_at": now,
        "updated_at": now,
        "source": "chirpstack",
    }
    try:
        await device_profiles_collection.insert_one(doc)
    except Exception:
        # carrera por índice → ya existe
        existing = await device_profiles_collection.find_one({"tenant_id": tenant_id, "model": model})
        if existing:
            return {
                "ok": True, "action": "reused",
                "tenant_id": tenant_id, "model": model,
                "profile_name": existing.get("profile_name"),
                "device_profile_id": existing.get("device_profile_id"),
            }
        raise

    return {
        "ok": True, "action": "created",
        "tenant_id": tenant_id, "model": model,
        "profile_name": profile_name, "device_profile_id": dp_id,
    }