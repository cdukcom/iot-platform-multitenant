from fastapi import APIRouter, Body, Query
from bson import ObjectId
from datetime import datetime, timezone
import subprocess, sys, json, re, os

from db import tenants_collection, devices_collection
from chirpstack_grpc import ChirpstackGRPCClient

def _sidecar_env():
    env = os.environ.copy()
    # Asegura que el intérprete del subproceso resuelva paquetes desde el root del proyecto
    # (en Railway normalmente el working dir ya es /app; "." funciona también localmente)
    env.setdefault("PYTHONPATH", ".")
    # Si quieres más traza gRPC en caso de error, descomenta:
    # env["GRPC_VERBOSITY"] = "DEBUG"
    # env["GRPC_TRACE"] = "http,call_error,op_failure"
    return env

router = APIRouter()

@router.get("/_dev_list_sidecar", include_in_schema=False)
async def _dev_list_sidecar(
    application_id: str = Query(...),
    limit: int = Query(5, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query("")
):
    """
    Lista devices de una Application en ChirpStack vía sidecar.
    """
    try:
        args = [sys.executable, "-m", "sidecars.dev_sidecar", "list",
                "--application-id", application_id,
                "--limit", str(limit), "--offset", str(offset), "--search", search]
        proc = subprocess.run(
            args, capture_output=True, text=True, check=True, env=_sidecar_env()
        )
        return json.loads(proc.stdout or "{}")
    except subprocess.CalledProcessError as e:
        # ← aquí añadimos el comando real para depurar
        raw = (e.stdout or e.stderr or "").strip()
        try:
            out = json.loads(raw or "{}")
        except Exception:
            out = {"ok": False, "error": raw or "sidecar failed"}
        out["cmd"] = args
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/_dev_smoke_create", include_in_schema=False)
async def _dev_smoke_create(body: dict = Body(...)):
    """
    Crea un Device (sensor) en ChirpStack vía SIDEcar y, si es OK, lo registra en Mongo.

    body esperado:
    {
      "tenant_id": "<Mongo _id>",
      "dev_eui": "16 HEX",
      "name": "lbm01-01",
      "profile_name": "dp-se-lbm01",
      "location": "opc",                 (opcional)
      "description": "texto",            (opcional)
      "tags": {"k":"v"},                 (opcional)
      "no_keys": true,                   (opcional, si no se mandan keys)
      "app_key": "32 HEX",               (requerido si no usas no_keys)
      "nwk_key": "32 HEX",               (opcional)
      "join_eui": "16 HEX"               (opcional)
    }
    """
    # -------- Validaciones mínimas --------
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

    # -------- Tenant + App + Profile (lecturas) --------
    tenant = await tenants_collection.find_one({"_id": oid})
    if not tenant:
        return {"ok": False, "error": "Tenant no encontrado"}

    cs = ChirpstackGRPCClient()  # SOLO lecturas/ensure; la creación va por sidecar

    tenant_cs_id = tenant.get("chirpstack_tenant_id")
    if not tenant_cs_id:
        return {"ok": False, "error": "Tenant sin chirpstack_tenant_id"}

    app_id = tenant.get("chirpstack_app_id")
    if not app_id:
        composed = tenant.get("chirpstack_tenant_name") or tenant.get("name") or "default-app"
        # crea/asegura app en ChirpStack (método ya probado en tu client)
        app_id = cs.ensure_application_same_as_tenant(tenant_cs_id, composed)
        await tenants_collection.update_one({"_id": oid}, {"$set": {"chirpstack_app_id": app_id}})

    # Busca ID del Device Profile por nombre (método ya probado)
    profile_id = cs.get_device_profile_id_by_name(profile, tenant_cs_id)

    # -------- Build args para sidecar CREATE --------
    args = [sys.executable, "-m", "sidecars.dev_sidecar", "create",
            "--application-id", app_id,
            "--device-profile-id", profile_id,
            "--dev-eui", dev_eui,
            "--name", name]

    if body.get("description"):
        args += ["--description", body["description"]]

    # tags dict -> "k=v,k2=v2"
    if isinstance(body.get("tags"), dict) and body["tags"]:
        tag_str = ",".join(f"{k}={v}" for k, v in body["tags"].items())
        args += ["--tags", tag_str]

    no_keys = bool(body.get("no_keys"))
    if no_keys:
        args += ["--no-keys"]
    else:
        app_key = (body.get("app_key") or "").strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{32}", app_key):
            return {"ok": False, "error": "app_key requerido (32 hex) si no usas no_keys"}
        args += ["--app-key", app_key]
        nwk_key = (body.get("nwk_key") or "").strip()
        if nwk_key:
            if not re.fullmatch(r"[0-9A-Fa-f]{32}", nwk_key):
                return {"ok": False, "error": "nwk_key inválido (32 hex)"}
            args += ["--nwk-key", nwk_key]
        join_eui = (body.get("join_eui") or "").strip()
        if join_eui:
            if not re.fullmatch(r"[0-9A-Fa-f]{16}", join_eui):
                return {"ok": False, "error": "join_eui inválido (16 hex)"}
            args += ["--join-eui", join_eui]

    # -------- Invocar sidecar --------
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=True, env=_sidecar_env())
        out = json.loads(proc.stdout or "{}")
    except subprocess.CalledProcessError as e:
        raw = (e.stdout or e.stderr or "").strip()
        try:
            out = json.loads(raw or "{}")
        except Exception:
            out = {"ok": False, "error": raw or "sidecar failed"}
        out["cmd"] = args            # ← añade el comando ejecutado
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # -------- Persistir en Mongo si Create fue OK --------
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
            "sidecar_result": out,  # guardamos eco mínimo del sidecar (útil para auditoría)
        },
    })

    return {
        "ok": True,
        "device_id": str(ins.inserted_id),
        "dev_eui": dev_eui,
        "profile_name": profile,
        "application_id": app_id,
    }