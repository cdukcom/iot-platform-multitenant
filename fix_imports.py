import os

base_dir = "chirpstack_proto"
log = []

for root, _, files in os.walk(base_dir):
    for file in files:
        if file.endswith("_pb2.py"):
            full_path = os.path.join(root, file)
            modified = False
            with open(full_path, "r") as f:
                lines = f.readlines()
            with open(full_path, "w") as f:
                for line in lines:
                    if line.startswith("from ") and " import " in line:
                        parts = line.split()
                        pkg = parts[1]
                        if not pkg.startswith("chirpstack_proto."):
                            new_line = line.replace(f"from {pkg} import", f"from chirpstack_proto.{pkg} import")
                            f.write(new_line)
                            modified = True
                        else:
                            f.write(line)
                    else:
                        f.write(line)
            if modified:
                log.append(f"✔️ Patched: {full_path}")

# Mostrar log al final
if log:
    print("\n[Resumen de archivos modificados]:")
    for entry in log:
        print(entry)
else:
    print("✅ No se detectaron imports incorrectos. Nada que modificar.")
