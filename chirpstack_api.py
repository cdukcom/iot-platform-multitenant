# chirpstack_api.py

import requests
import os

# Cargar las variables de entorno necesarias
CHIRPSTACK_API_URL = os.getenv("CHIRPSTACK_API_URL", "http://lorawan.duke-villa.com:8090")
CHIRPSTACK_API_KEY = os.getenv("CHIRPSTACK_API_KEY")  # Se usa desde variables de entorno Railway

# Validación temprana
if not CHIRPSTACK_API_KEY:
    raise RuntimeError("CHIRPSTACK_API_KEY no está definida en las variables de entorno.")

HEADERS = {
    "Grpc-Metadata-Authorization": f"Bearer {CHIRPSTACK_API_KEY}",
    "Content-Type": "application/json"
}

# ------------------------- BLOQUE DISPOSITIVOS -------------------------
def get_devices(tenant_id):
    url = f"{CHIRPSTACK_API_URL}/devices?limit=1000&tenant_id={tenant_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json().get("result", [])
    except requests.RequestException as e:
        print(f"[ERROR] al obtener dispositivos: {e}")
        return []

# ------------------------- BLOQUE PROFILES -------------------------
def get_device_profiles(tenant_id):
    if not tenant_id:
        raise ValueError("tenant_id es obligatorio para obtener device_profiles")
    url = f"{CHIRPSTACK_API_URL}/device-profiles?limit=1000&tenant_id={tenant_id}"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json().get("result", [])
    except requests.RequestException as e:
        print(f"[ERROR] al obtener perfiles de dispositivo: {e}")
        return []

def get_device_profile_by_name(name, tenant_id):
    profiles = get_device_profiles(tenant_id)
    for profile in profiles:
        if profile.get("name") == name:
            return profile
    print(f"[INFO] No se encontró el perfil con nombre: {name}")
    return None

# ------------------------- BLOQUE APLICACIONES -------------------------
def create_application(app_name, tenant_id):
    if not tenant_id:
        raise ValueError("tenant_id es obligatorio para crear una aplicación")

    url = f"{CHIRPSTACK_API_URL}/applications"
    payload = {
        "application": {
            "name": app_name,
            "tenant_id": tenant_id,
            "description": f"Aplicación generada para {app_name}",
        }
    }

    try:
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"[ERROR] al crear aplicación '{app_name}': {e}")
        return None