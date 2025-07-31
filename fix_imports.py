import os

base_dir = "chirpstack_proto/api"
log = []

def patch_line(line):
    if line.startswith("from ") and " import " in line:
        parts = line.split()
        pkg = parts[1]
        # Corrige import incorrecto de google.protobuf
        if pkg.startswith("chirpstack_proto.api.google.protobuf"):
            return line.replace("chirpstack_proto.api.google.protobuf", "google.protobuf"), True
        # Corrige imports internos que no empiezan con chirpstack_proto.api.
        elif not pkg.startswith("chirpstack_proto.api.") and not pkg.startswith("google.protobuf"):
            return line.replace(f"from {pkg} import", f"from chirpstack_proto.api.{pkg} import"), True
    return line, False

for root, _, files in os.walk(base_dir):
    for file in files:
        if file.endswith("_pb2.py") or file.endswith("_pb2_grpc.py"):
            full_path = os.path.join(root, file)
            modified = False
            with open(full_path, "r") as f:
                lines = f.readlines()
            with open(full_path, "w") as f:
                for line in lines:
                    new_line, changed = patch_line(line)
                    if changed:
                        modified = True
                    f.write(new_line)
            if modified:
                log.append(f"✔️ Patched: {full_path}")

# Mostrar log al final
if log:
    print("\n[Resumen de archivos modificados]:")
    for entry in log:
        print(entry)
else:
    print("✅ No se detectaron imports incorrectos. Nada que modificar.")