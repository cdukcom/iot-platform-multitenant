# iotaas/sidecars/dev_sidecar.py
import os, sys, json, argparse, grpc
from google.protobuf import empty_pb2
from grpc_auth_interceptor import ApiKeyAuthInterceptor

# Stubs de internet (PyPI: chirpstack-api)
from chirpstack_api.api import device_pb2 as dev_pb2
from chirpstack_api.api import device_pb2_grpc as dev_grpc
from chirpstack_api.api import device_profile_pb2 as dp_pb2
from chirpstack_api.api import device_profile_pb2_grpc as dp_grpc

# --- Canal gRPC ---
def _channel():
    addr = os.getenv("CHIRPSTACK_GRPC_ADDRESS", "localhost:8080")
    apikey = os.getenv("CHIRPSTACK_API_KEY")
    if not apikey:
        raise RuntimeError("CHIRPSTACK_API_KEY missing")
    return grpc.intercept_channel(
        grpc.insecure_channel(addr),
        ApiKeyAuthInterceptor(apikey),
    )

def ok(payload: dict):
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False)); sys.exit(0)

def fail(msg: str, extra: dict | None = None, code: int = 1):
    out = {"ok": False, "error": msg}
    if extra: out.update(extra)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)

def catch_grpc(e: grpc.RpcError):
    details = e.details()
    status = e.code().name if hasattr(e, "code") else "UNKNOWN"
    fail(f"gRPC {status}: {details}")

def _parse_tags(tags_str: str | None) -> dict:
    if not tags_str:
        return {}
    out = {}
    for pair in tags_str.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def _resolve_profile_id(ch, tenant_id: str, profile_name: str) -> str | None:
    stub = dp_grpc.DeviceProfileServiceStub(ch)
    limit, offset = 200, 0
    while True:
        resp = stub.List(dp_pb2.ListDeviceProfilesRequest(
            tenant_id=tenant_id, limit=limit, offset=offset
        ))
        batch = 0
        for it in resp.result:
            src = getattr(it, "device_profile", it)
            if getattr(src, "name", None) == profile_name:
                return getattr(src, "id", None)
            batch += 1
        if batch == 0: break
        total = getattr(resp, "total_count", None)
        offset += batch
        if total is not None and offset >= total: break
    return None

# --- Comandos
def cmd_list(args):
    ch = _channel()
    stub = dev_grpc.DeviceServiceStub(ch)
    try:
        req = dev_pb2.ListDevicesRequest(
            application_id=args.application_id,
            limit=args.limit, offset=args.offset, search=args.search or "",
        )
        resp = stub.List(req)
        items = [{
            "dev_eui": d.dev_eui, "name": d.name,
            "application_id": d.application_id, "device_profile_id": d.device_profile_id,
            "description": d.description, "tags": dict(d.tags),
        } for d in resp.result]
        ok({"total_count": getattr(resp, "total_count", None), "items": items})
    except grpc.RpcError as e:
        catch_grpc(e)


def cmd_create(args):
    import re
    # Validaciones mínimas de entrada
    if not re.fullmatch(r"[0-9A-Fa-f]{16}", args.dev_eui or ""):
        fail("dev_eui debe ser 16 hex (EUI64)")
    if not args.application_id:
        fail("application_id requerido")
    if not args.device_profile_id:
        fail("device_profile_id requerido")
    if not args.name:
        fail("name requerido")

    ch = _channel()

    # Resolver device_profile_id si no viene explícito
    profile_id = args.device_profile_id
    if not profile_id:
        if not args.tenant_id or not args.profile_name:
            fail("Falta device_profile_id o (tenant-id + profile-name)")
        profile_id = _resolve_profile_id(ch, args.tenant_id, args.profile_name)
        if not profile_id:
            fail(f"Device Profile '{args.profile_name}' no existe en tenant {args.tenant_id}")
   
    dev_stub  = dev_grpc.DeviceServiceStub(ch)
    keys_stub = dev_grpc.DeviceKeysServiceStub(ch)

    device = dev_pb2.Device(
        dev_eui=args.dev_eui.upper(),
        name=args.name,
        description=args.description or "",
        application_id=args.application_id,
        device_profile_id=args.device_profile_id,
        tags=_parse_tags(args.tags),
    )
    
    # Crear Device
    try:
        resp = dev_stub.Create(dev_pb2.CreateDeviceRequest(device=device))
        if not isinstance(resp, empty_pb2.Empty):
            fail(f"Respuesta inesperada en CreateDevice: {type(resp)}")
    except grpc.RpcError as e:
        catch_grpc(e)

    # Crear DeviceKeys (si no se pasa --no-keys)
    if not args.no_keys:
        try:
            dk = dev_pb2.DeviceKeys(
                dev_eui=args.dev_eui.upper(),
                app_key=(args.app_key or "").upper(),
                nwk_key=((args.nwk_key or args.app_key) or "").upper(),
                join_eui=(args.join_eui or "0000000000000000").upper(),
            )
            _ = keys_stub.Create(dev_pb2.CreateDeviceKeysRequest(device_keys=dk))
        except grpc.RpcError as e:
            catch_grpc(e)

    ok({
        "created": True,
        "dev_eui": args.dev_eui.upper(),
        "application_id": args.application_id,
        "device_profile_id": profile_id,
        "keys": (not args.no_keys),
    })

def main():
    p = argparse.ArgumentParser(prog="dev_sidecar", description="Sidecar Devices (ChirpStack v4, stubs de internet)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_list = sub.add_parser("list", help="Listar devices por application_id")
    sp_list.add_argument("--application-id", required=True)
    sp_list.add_argument("--limit", type=int, default=10)
    sp_list.add_argument("--offset", type=int, default=0)
    sp_list.add_argument("--search", default="")
    sp_list.set_defaults(func=cmd_list)

    sp_create = sub.add_parser("create", help="Crear device (sensor)")
    sp_create.add_argument("--application-id", required=True)
    # Perfil: o pasas el ID directo, o el combo tenant+nombre
    sp_create.add_argument("--device-profile-id", help="ID del Device Profile")
    sp_create.add_argument("--tenant-id", help="Tenant ID de ChirpStack (para resolver profile por nombre)")
    sp_create.add_argument("--profile-name", help="Nombre del Device Profile (si no pasas --device-profile-id)")
    sp_create.add_argument("--dev-eui", required=True)
    sp_create.add_argument("--name", required=True)
    sp_create.add_argument("--description", default="")
    sp_create.add_argument("--tags", default="", help="k=v,k2=v2")
    sp_create.add_argument("--no-keys", action="store_true", help="no crear DeviceKeys (OTAA)")
    sp_create.add_argument("--app-key", default="", help="AppKey 32 hex (si no usas --no-keys)")
    sp_create.add_argument("--nwk-key", default="", help="NwkKey 32 hex (si vacío, espeja app-key)")
    sp_create.add_argument("--join-eui", default="", help="JoinEUI 16 hex (default 0000000000000000)")
    sp_create.set_defaults(func=cmd_create)

    args = p.parse_args()

    if args.cmd == "create" and not args.no_keys:
        if not args.app_key or len(args.app_key.strip()) != 32:
            fail("app_key requerido (32 hex) o usa --no-keys")

    try:
        args.func(args)
    except grpc.RpcError as e:
        catch_grpc(e)
    except Exception as e:
        fail(str(e))


if __name__ == "__main__":
    main()
