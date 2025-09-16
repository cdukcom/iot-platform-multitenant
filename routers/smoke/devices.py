from fastapi import APIRouter, Body
from bson import ObjectId
from datetime import datetime, timezone
from db import tenants_collection, devices_collection
from chirpstack_grpc import ChirpstackGRPCClient

router = APIRouter()

@router.post("/_dev_smoke_create", include_in_schema=False)
async def _dev_smoke_create(body: dict = Body(...)):
    """
    body = {
      "tenant_id": "<Mongo _id>", "dev_eui": "16 HEX",
      "name": "opc", "profile_name": "dp-se-lbm01", "location": "opc"
    }
    """
    import re
    try:
        tenant_id = body["tenant_id"]
        dev_eui   = (body["dev_eui"] or "").strip().upper()
        name      = (body.get("name") or "smoke-device").strip()
        profile   = (body.get("profile_name") or body.get("type") or "").strip()
    except KeyError as e:
        return {"ok": False, "error": f"missing field: {e.args[0]}"}
    if not re.fullmatch(r"[0-9A-F]{16}", dev_eui):
        return {"ok": False, "error": "dev_eui debe ser 16 hex"}
    if not profile:
        return {"ok": False, "error": "profile_name requerido"}

    try:
        oid = ObjectId(tenant_id)
    except Exception:
        return {"ok": False, "error": "tenant_id inválido"}

    tenant = await tenants_collection.find_one({"_id": oid})
    if not tenant:
        return {"ok": False, "error": "Tenant no encontrado"}

    try:
        cs = ChirpstackGRPCClient()
        tenant_cs_id = tenant.get("chirpstack_tenant_id")
        if not tenant_cs_id:
            return {"ok": False, "error": "Tenant sin chirpstack_tenant_id"}

        app_id = tenant.get("chirpstack_app_id")
        if not app_id:
            composed = tenant.get("chirpstack_tenant_name") or tenant.get("name") or "default-app"
            app_id = cs.ensure_application_same_as_tenant(tenant_cs_id, composed)
            await tenants_collection.update_one({"_id": oid}, {"$set": {"chirpstack_app_id": app_id}})

        profile_id = cs.get_device_profile_id_by_name(profile, tenant_cs_id)

        cs.create_device(
            dev_eui=dev_eui,
            name=name,
            description=body.get("description", ""),
            application_id=app_id,
            device_profile_id=profile_id,
        )

        ins = await devices_collection.insert_one({
            "tenant_id": tenant_id,
            "dev_eui": dev_eui,
            "name": name,
            "type": profile,
            "status": "active",
            "location": body.get("location", ""),
            "created_at": datetime.now(timezone.utc),
            "meta": {
                "smoke": True,
                "chirpstack_tenant_id": tenant_cs_id,
                "chirpstack_app_id": app_id,
                "device_profile_name": profile,
                "device_profile_id": profile_id,
            },
        })
        return {"ok": True, "device_id": str(ins.inserted_id), "dev_eui": dev_eui, "profile_name": profile}
    except Exception as e:
        return {"ok": False, "error": str(e)}
