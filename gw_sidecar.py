# gw_sidecar.py
import os, json, argparse, grpc, sys
from grpc_auth_interceptor import ApiKeyAuthInterceptor

# Usamos el paquete oficial SOLO aquí
from chirpstack_api.api import gateway_pb2 as gw_pb2
from chirpstack_api.api import gateway_pb2_grpc as gw_pb2_grpc

def make_stub():
    addr = os.getenv("CHIRPSTACK_GRPC_ADDRESS", "localhost:8080")
    api_key = os.getenv("CHIRPSTACK_API_KEY")
    if not api_key:
        print(json.dumps({"ok": False, "error": "CHIRPSTACK_API_KEY missing"}))
        sys.exit(1)
    channel = grpc.intercept_channel(grpc.insecure_channel(addr), ApiKeyAuthInterceptor(api_key))
    return gw_pb2_grpc.GatewayServiceStub(channel)

def cmd_list(limit: int, tenant_id: str):
    stub = make_stub()
    resp = stub.List(gw_pb2.ListGatewaysRequest(limit=limit, tenant_id=tenant_id or ""))
    print(json.dumps({"ok": True, "total_count": getattr(resp, "total_count", None)}))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=1)
    p_list.add_argument("--tenant-id", default="")

    args = p.parse_args()
    try:
        if args.cmd == "list":
            cmd_list(args.limit, args.tenant_id)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(2)
