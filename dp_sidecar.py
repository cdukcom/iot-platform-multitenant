# dp_sidecar.py
import os, json, argparse, grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from grpc_auth_interceptor import ApiKeyAuthInterceptor

# Paquete oficial solo aquí (como hiciste con gateways)
from chirpstack_api.api import device_profile_template_pb2 as dpt_pb2
from chirpstack_api.api import device_profile_template_pb2_grpc as dpt_grpc
from chirpstack_api.api import device_profile_pb2 as dp_pb2
from chirpstack_api.api import device_profile_pb2_grpc as dp_grpc

def _channel():
    addr = os.getenv("CHIRPSTACK_GRPC_ADDRESS", "localhost:8080")
    apikey = os.getenv("CHIRPSTACK_API_KEY")
    if not apikey:
        raise RuntimeError("CHIRPSTACK_API_KEY missing")
    return grpc.intercept_channel(
        grpc.insecure_channel(addr),
        ApiKeyAuthInterceptor(apikey),
    )

def list_templates(limit=50, search=""):
    ch = _channel()
    stub = dpt_grpc.DeviceProfileTemplateServiceStub(ch)
    try:
        items, fetched, offset = [], 0, 0
        page_size = min(max(1, limit), 200)

        while fetched < limit:
            # 4.13.0 NO tiene 'search' en el request
            req = dpt_pb2.ListDeviceProfileTemplatesRequest(limit=page_size, offset=offset)
            resp = stub.List(req)

            batch = 0
            for it in resp.result:
                tpl = getattr(it, "device_profile_template", it)
                name = getattr(tpl, "name", None)
                tid  = getattr(tpl, "id", None)
                if not name or not tid:
                    continue
                items.append({"id": tid, "name": name})
                batch += 1

            fetched += batch
            offset  += batch

            total = getattr(resp, "total_count", None)
            if batch == 0 or (total is not None and offset >= total):
                break

        # filtro cliente (case-insensitive)
        if search:
            s = search.lower()
            items = [x for x in items if s in (x["name"] or "").lower()]

        return {"ok": True, "total_count": len(items), "items": items[:limit]}
    except grpc.RpcError as e:
        return {"ok": False, "error": f"gRPC {e.code().name}: {e.details()}"}

def get_template(name: str):
    ch = _channel()
    stub = dpt_grpc.DeviceProfileTemplateServiceStub(ch)

    offset, page_size = 0, 100
    try:
        while True:
            req = dpt_pb2.ListDeviceProfileTemplatesRequest(limit=page_size, offset=offset)
            resp = stub.List(req)

            match_id = None
            match_name = None
            for it in resp.result:
                # En 4.13.0 viene como 'device_profile_template' o directo
                tpl_meta = getattr(it, "device_profile_template", it)
                tpl_name = getattr(tpl_meta, "name", "")
                if tpl_name == name:
                    match_id = getattr(tpl_meta, "id", None)
                    match_name = tpl_name
                    break

            if match_id:
                got = stub.Get(dpt_pb2.GetDeviceProfileTemplateRequest(id=match_id))
                tpl = got.device_profile_template

                # ⚠️ Extrae el DeviceProfile anidado si existe; si no, usa el propio template
                src_dp = getattr(tpl, "device_profile", None) or tpl

                # Convierte el mensaje protobuf a dict JSON usando nombres de campo proto
                dp_dict = MessageToDict(src_dp, preserving_proto_field_name=True)

                # Devolvemos el DP "plano" como template, y metadatos del template
                return {
                    "ok": True,
                    "template": dp_dict,
                    "template_id": getattr(tpl, "id", None),
                    "template_name": match_name or getattr(tpl, "name", None),
                }

            batch = len(resp.result)
            offset += batch
            total = getattr(resp, "total_count", None)
            if batch == 0 or (total is not None and offset >= total):
                break

        return {"ok": False, "error": f"Template '{name}' no encontrado"}
    except grpc.RpcError as e:
        return {"ok": False, "error": f"gRPC {e.code().name}: {e.details()}"}
    except Exception as e:
        # Atrapa AttributeError tipo 'rx1_delay' y similares
        return {"ok": False, "error": str(e)}

def create_dp_from_template(tenant_id: str, profile_name: str, template: dict):
    ch = _channel()
    stub = dp_grpc.DeviceProfileServiceStub(ch)

    # Reconstruye un DeviceProfile desde el dict (solo campos válidos serán seteados)
    dp = dp_pb2.DeviceProfile()
    ParseDict(template, dp)

    # Sobrescribe campos obligatorios
    dp.name = profile_name
    dp.tenant_id = tenant_id

    try:
        resp = stub.Create(dp_pb2.CreateDeviceProfileRequest(device_profile=dp))
        return {"ok": True, "device_profile_id": resp.id}
    except grpc.RpcError as e:
        return {"ok": False, "error": f"gRPC {e.code().name}: {e.details()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def main():
    p = argparse.ArgumentParser(prog="dp_sidecar", description="Device Profile Template sidecar")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--search", default="")

    p_get = sub.add_parser("get")
    p_get.add_argument("--name", required=True)

    p_create = sub.add_parser("create-from-template")
    p_create.add_argument("--tenant-id", required=True)
    p_create.add_argument("--profile-name", required=True)
    p_create.add_argument("--template-json", required=True, help="JSON del template (usar caché)")

    args = p.parse_args()
    try:
        if args.cmd == "list":
            out = list_templates(limit=args.limit, search=args.search)
        elif args.cmd == "get":
            out = get_template(args.name)
        elif args.cmd == "create-from-template":
            tpl = json.loads(args.template_json)
            out = create_dp_from_template(args.tenant_id, args.profile_name, tpl)
        else:
            out = {"ok": False, "error": f"unknown cmd {args.cmd}"}
    except Exception as e:
        out = {"ok": False, "error": str(e)}

    print(json.dumps(out))

if __name__ == "__main__":
    main()
