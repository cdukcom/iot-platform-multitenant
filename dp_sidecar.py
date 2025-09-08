# dp_sidecar.py
import os, json, argparse, grpc
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
            for it in resp.result:
                tpl_meta = getattr(it, "device_profile_template", it)
                if getattr(tpl_meta, "name", "") == name:
                    match_id = getattr(tpl_meta, "id", None)
                    break

            if match_id:
                got = stub.Get(dpt_pb2.GetDeviceProfileTemplateRequest(id=match_id))
                tpl = got.device_profile_template
                data = {
                    "id": tpl.id,
                    "name": tpl.name,
                    "region": int(tpl.region),
                    "mac_version": int(tpl.mac_version),
                    "reg_params_revision": int(tpl.reg_params_revision),
                    "supports_otaa": bool(tpl.supports_otaa),
                    "supports_class_b": bool(tpl.supports_class_b),
                    "supports_class_c": bool(tpl.supports_class_c),
                    "rx1_delay": int(tpl.rx1_delay),
                    "rx2_dr": int(tpl.rx2_dr),
                    "rx2_frequency": int(tpl.rx2_frequency),
                    "factory_preset_freqs": list(tpl.factory_preset_freqs),
                    "max_eirp": int(tpl.max_eirp),
                    "payload_codec_runtime": int(tpl.payload_codec_runtime),
                    "payload_codec_script": tpl.payload_codec_script or "",
                }
                return {"ok": True, "template": data}

            batch = len(resp.result)
            offset += batch
            total = getattr(resp, "total_count", None)
            if batch == 0 or (total is not None and offset >= total):
                break

        return {"ok": False, "error": f"Template '{name}' no encontrado"}
    except grpc.RpcError as e:
        return {"ok": False, "error": f"gRPC {e.code().name}: {e.details()}"}

def create_dp_from_template(tenant_id: str, profile_name: str, template: dict):
    ch = _channel()
    stub = dp_grpc.DeviceProfileServiceStub(ch)
    dp = dp_pb2.DeviceProfile(
        name=profile_name,
        tenant_id=tenant_id,
        region=template["region"],
        mac_version=template["mac_version"],
        reg_params_revision=template["reg_params_revision"],
        supports_otaa=template["supports_otaa"],
        supports_class_b=template["supports_class_b"],
        supports_class_c=template["supports_class_c"],
        rx1_delay=template["rx1_delay"],
        rx2_dr=template["rx2_dr"],
        rx2_frequency=template["rx2_frequency"],
        factory_preset_freqs=template["factory_preset_freqs"],
        max_eirp=template["max_eirp"],
        payload_codec_runtime=template["payload_codec_runtime"],
        payload_codec_script=template["payload_codec_script"],
    )
    try:
        resp = stub.Create(dp_pb2.CreateDeviceProfileRequest(device_profile=dp))
        return {"ok": True, "device_profile_id": resp.id}
    except grpc.RpcError as e:
        return {"ok": False, "error": f"gRPC {e.code().name}: {e.details()}"}

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
