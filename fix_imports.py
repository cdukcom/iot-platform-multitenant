import os

proto_dir = "chirpstack_proto/api"
backend_dirs = ["."]  # Raíz del proyecto
log_proto = []
log_backend = []

def patch_proto_line(line):
    if line.startswith("from ") and " import " in line:
        parts = line.split()
        pkg = parts[1]
        # Corrige import incorrecto de google.protobuf
        if pkg.startswith("chirpstack_proto.api.google.protobuf"):
            return line.replace("chirpstack_proto.api.google.protobuf", "google.protobuf"), True
        # Corrige imports internos sin el prefijo chirpstack_proto.api
        elif not pkg.startswith("chirpstack_proto.api.") and not pkg.startswith("google.protobuf"):
            return line.replace(f"from {pkg} import", f"from chirpstack_proto.api.{pkg} import"), True
    return line, False

def patch_backend_line(line):
    if "from chirpstack_proto." in line and "api" not in line:
        return line.replace("from chirpstack_proto.", "from chirpstack_proto.api."), True
    return line, False

# Parchear archivos del proto
for root, _, files in os.walk(proto_dir):
    for file in files:
        if file.endswith("_pb2.py") or file.endswith("_pb2_grpc.py"):
            full_path = os.path.join(root, file)
            modified = False
            with open(full_path, "r") as f:
                lines = f.readlines()
            with open(full_path, "w") as f:
                for line in lines:
                    new_line, changed = patch_proto_line(line)
                    if changed:
                        modified = True
                    f.write(new_line)
            if modified:
                log_proto.append(f"✔️ Patched proto: {full_path}")

# Parchear archivos del backend (excepto los del proto)
for backend_dir in backend_dirs:
    for root, _, files in os.walk(backend_dir):
        # Saltar carpeta chirpstack_proto
        if "chirpstack_proto" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                full_path = os.path.join(root, file)
                modified = False
                with open(full_path, "r") as f:
                    lines = f.readlines()
                with open(full_path, "w") as f:
                    for line in lines:
                        new_line, changed = patch_backend_line(line)
                        if changed:
                            modified = True
                        f.write(new_line)
                if modified:
                    log_backend.append(f"✔️ Patched backend: {full_path}")

# Log final
if log_proto or log_backend:
    print("\n[Resumen de imports corregidos]:")
    for entry in log_proto + log_backend:
        print(entry)
else:
    print("✅ No se detectaron imports incorrectos. Nada que modificar.")