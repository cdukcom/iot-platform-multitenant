# gw_sidecar.py
import os, json, argparse, grpc
from grpc_auth_interceptor import ApiKeyAuthInterceptor

# Usamos el paquete oficial SOLO aquí
from chirpstack_api.api import gateway_pb2 as gw_pb2
from chirpstack_api.api import gateway_pb2_grpc as gw_pb2_grpc

def _channel():
    addr = os.getenv("CHIRPSTACK_GRPC_ADDRESS", "localhost:8080")
    apikey = os.getenv("CHIRPSTACK_API_KEY")
    if not apikey:
        raise RuntimeError("CHIRPSTACK_API_KEY missing")
    return grpc.intercept_channel(
        grpc.insecure_channel(addr),
        ApiKeyAuthInterceptor(apikey),
    )

def list_gateways(limit=1, tenant_id=""):
    ch = _channel()
    stub = gw_pb2_grpc.GatewayServiceStub(ch)
    req = gw_pb2.ListGatewaysRequest(limit=limit)
    if tenant_id:
        req.tenant_id = tenant_id
    resp = stub.List(req)
    return {"ok": True, "total_count": getattr(resp, "total_count", None)}

def _parse_tags(tags_str: str | None) -> dict:
    if not tags_str:
        return {}
    out = {}
    for pair in tags_str.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def create_gateway(gateway_id: str, name: str, tenant_id: str, description: str = "", tags_str: str | None = None):
    # validación mínima de EUI64 (16 hex)
    import re
    if not re.fullmatch(r"[0-9A-Fa-f]{16}", gateway_id or ""):
        return {"ok": False, "error": "gateway_id debe ser 16 hex (EUI64)"}
    if not tenant_id:
        return {"ok": False, "error": "tenant_id es obligatorio"}
    if not name:
        return {"ok": False, "error": "name es obligatorio"}

    ch = _channel()
    stub = gw_pb2_grpc.GatewayServiceStub(ch)
    tags = _parse_tags(tags_str)

    req = gw_pb2.CreateGatewayRequest(
        gateway=gw_pb2.Gateway(
            gateway_id=gateway_id.upper(),
            name=name,
            description=description or "",
            tenant_id=tenant_id,
            tags=tags,
        )
    )
    stub.Create(req)
    return {"ok": True, "gateway_id": gateway_id.upper(), "tenant_id": tenant_id}

def delete_gateway(gateway_id: str):
    import re
    gateway_id = (gateway_id or "").strip().upper()
    if not re.fullmatch(r"[0-9A-Fa-f]{16}", gateway_id or ""):
        return {"ok": False, "error": "gateway_id debe ser 16 hex (EUI64)"}

    ch = _channel()
    stub = gw_pb2_grpc.GatewayServiceStub(ch)
    req = gw_pb2.DeleteGatewayRequest(gateway_id=gateway_id)
    
    try:
        stub.Delete(req, timeout=5)
        return {"ok": True, "gateway_id": gateway_id}
    except grpc.RpcError as e:
        # Mapea errores típicos a mensajes útiles
        code = e.code().name
        detail = e.details()
        if code == "NOT_FOUND":
            detail = f"Gateway {gateway_id} no existe"
        elif code == "DEADLINE_EXCEEDED":
            detail = "Timeout al contactar ChirpStack"
        return {"ok": False, "error": f"gRPC {code}: {detail}"}

def main():
    p = argparse.ArgumentParser(prog="gw_sidecar", description="Gateway sidecar (safe cmds)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=1)
    p_list.add_argument("--tenant-id", default="")

    p_create = sub.add_parser("create")
    p_create.add_argument("--gateway-id", required=True)
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--tenant-id", required=True)
    p_create.add_argument("--description", default="")
    p_create.add_argument("--tags", default="", help="k1=v1,k2=v2")
    
    p_delete = sub.add_parser("delete")
    p_delete.add_argument("--gateway-id", required=True)

    args = p.parse_args()

    try:
        if args.cmd == "list":
            out = list_gateways(limit=args.limit, tenant_id=args.tenant_id)
        elif args.cmd == "create":
            out = create_gateway(
                gateway_id=args.gateway_id,
                name=args.name,
                tenant_id=args.tenant_id,
                description=args.description,
                tags_str=args.tags,
            )
        elif args.cmd == "delete":
            out = delete_gateway(gateway_id=args.gateway_id)
        else:
            out = {"ok": False, "error": f"unknown cmd {args.cmd}"}
    
    except grpc.RpcError as e:
        # Mensaje de error gRPC más claro
        out = {"ok": False, "error": f"gRPC {e.code().name}: {e.details()}"}

    except Exception as e:
        out = {"ok": False, "error": str(e)}

    print(json.dumps(out))

if __name__ == "__main__":
    main()