# iotaas/sidecars/dev_sidecar.py
import os, sys, json, argparse
import grpc
from google.protobuf import empty_pb2
from chirpstack_api.api import device_pb2, device_pb2_grpc

# --- Auth interceptor (igual patrón que tus otros sidecars)
class AuthInterceptor(grpc.UnaryUnaryClientInterceptor, grpc.UnaryStreamClientInterceptor):
    def __init__(self, token: str):
        self.md = [('authorization', f'Bearer {token}')] if token else []
    def intercept_unary_unary(self, continuation, call_details, request):
        return continuation(call_details, request, metadata=self.md)
    def intercept_unary_stream(self, continuation, call_details, request):
        return continuation(call_details, request, metadata=self.md)

def make_channel(addr: str, insecure: bool, token: str):
    options = [
        ('grpc.max_receive_message_length', 20 * 1024 * 1024),
        ('grpc.max_send_message_length', 20 * 1024 * 1024),
    ]
    ch = grpc.insecure_channel(addr, options=options) if insecure \
         else grpc.secure_channel(addr, grpc.ssl_channel_credentials(), options=options)
    return grpc.intercept_channel(ch, AuthInterceptor(token)) if token else ch

def ok(payload: dict):
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False)); sys.exit(0)

def fail(msg: str, extra: dict | None = None, code: int = 1):
    out = {"ok": False, "error": msg}; 
    if extra: out.update(extra)
    print(json.dumps(out, ensure_ascii=False)); sys.exit(code)

def catch_grpc(e: grpc.RpcError):
    details = e.details()
    status = e.code().name if hasattr(e, "code") else "UNKNOWN"
    md = {}
    try: md = dict(e.trailing_metadata() or [])
    except Exception: pass
    fail(f"gRPC {status}: {details}", {"metadata": md})

# --- Comandos
def cmd_list(args):
    ch = make_channel(args.addr, args.insecure, args.token)
    stub = device_pb2_grpc.DeviceServiceStub(ch)
    try:
        req = device_pb2.ListDevicesRequest(
            application_id=args.application_id,
            limit=args.limit, offset=args.offset, search=args.search or "",
        )
        resp = stub.List(req)
        items = [{
            "dev_eui": d.dev_eui, "name": d.name,
            "application_id": d.application_id, "device_profile_id": d.device_profile_id,
            "description": d.description, "tags": dict(d.tags),
        } for d in resp.result]
        ok({"total_count": resp.total_count, "items": items})
    except grpc.RpcError as e:
        catch_grpc(e)

def cmd_create(args):
    ch = make_channel(args.addr, args.insecure, args.token)
    dev_stub  = device_pb2_grpc.DeviceServiceStub(ch)
    keys_stub = device_pb2_grpc.DeviceKeysServiceStub(ch)

    device = device_pb2.Device(
        dev_eui=args.dev_eui.upper(),
        name=args.name,
        description=args.description or "",
        application_id=args.application_id,
        device_profile_id=args.device_profile_id,
        tags=dict(kv.split("=",1) for kv in args.tags.split(",") if kv) if args.tags else {},
    )
    try:
        resp = dev_stub.Create(device_pb2.CreateDeviceRequest(device=device))
        if not isinstance(resp, empty_pb2.Empty):
            fail(f"Respuesta inesperada en CreateDevice: {type(resp)}")
    except grpc.RpcError as e:
        catch_grpc(e)

    if not args.no_keys:
        try:
            dk = device_pb2.DeviceKeys(
                dev_eui=args.dev_eui.upper(),
                app_key=(args.app_key or "").upper(),
                nwk_key=((args.nwk_key or args.app_key) or "").upper(),
                join_eui=(args.join_eui or "0000000000000000").upper(),
            )
            _ = keys_stub.Create(device_pb2.CreateDeviceKeysRequest(device_keys=dk))
        except grpc.RpcError as e:
            catch_grpc(e)

    ok({
        "created": True,
        "dev_eui": args.dev_eui.upper(),
        "application_id": args.application_id,
        "device_profile_id": args.device_profile_id,
        "keys": (not args.no_keys),
    })

def main():
    default_addr = os.getenv("CHIRPSTACK_ADDR", "localhost:8080")
    default_token = os.getenv("CHIRPSTACK_TOKEN", "")
    default_insecure = os.getenv("CHIRPSTACK_INSECURE", "1").lower() in ("1","true","yes","y")

    p = argparse.ArgumentParser(prog="dev_sidecar", description="Sidecar Devices (ChirpStack v4)")
    p.add_argument("--addr", default=default_addr, help="host:port gRPC (CHIRPSTACK_ADDR)")
    p.add_argument("--token", default=default_token, help="API key (CHIRPSTACK_TOKEN)")
    p.add_argument("--insecure", action="store_true", default=default_insecure, help="canal plaintext (default por env)")
    p.add_argument("--tls", action="store_true", help="forzar TLS")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_list = sub.add_parser("list", help="Listar devices por application_id")
    sp_list.add_argument("--application-id", required=True)
    sp_list.add_argument("--limit", type=int, default=10)
    sp_list.add_argument("--offset", type=int, default=0)
    sp_list.add_argument("--search", default="")
    sp_list.set_defaults(func=cmd_list)

    sp_create = sub.add_parser("create", help="Crear device (sensor)")
    sp_create.add_argument("--application-id", required=True)
    sp_create.add_argument("--device-profile-id", required=True)
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
    if args.tls: args.insecure = False
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
