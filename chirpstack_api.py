# chirpstack_api.py

import requests
import os

# 🌐 Configuración de la API de ChirpStack
CHIRPSTACK_API_URL = os.getenv("CHIRPSTACK_API_URL", "http://lorawan.duke-villa.com:8090")
CHIRPSTACK_API_KEY = os.getenv("CHIRPSTACK_API_KEY")  # Se usa desde variables de entorno Railway

HEADERS = {
    "Grpc-Metadata-Authorization": f"Bearer {CHIRPSTACK_API_KEY}",
    "Content-Type": "application/json"
}

# 🔍 Obtener lista de dispositivos registrados en ChirpStack (global)
def get_devices():
    url = f"{CHIRPSTACK_API_URL}/devices"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return response.json().get("result", [])
    else:
        print(f"[ERROR] {response.status_code}: {response.text}")
        return []

# 🔍 Obtener lista de device-profiles de un tenant específico
def get_device_profiles(tenant_id):
    url = f"{CHIRPSTACK_API_URL}/device-profiles?tenant_id={tenant_id}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return response.json().get("result", [])
    print(f"[ERROR get_device_profiles] {response.status_code}: {response.text}")
    return []

# 📎 Obtener un device-profile por nombre y tenant
def get_device_profile_by_name(name, tenant_id):
    profiles = get_device_profiles(tenant_id)
    for profile in profiles:
        if profile.get("name") == name:
            return profile.get("id")
    print(f"[WARN] No se encontró device-profile con nombre: {name} en tenant: {tenant_id}")
    return None


# 📦 Crear una nueva aplicación en ChirpStack
def create_application(app_name, tenant_id="00000000-0000-0000-0000-000000000000"):
    url = f"{CHIRPSTACK_API_URL}/applications"
    payload = {
        "application": {
            "name": app_name,
            "tenant_id": tenant_id,  # Puede ser fijo o dinámico si usas multitenancy en ChirpStack
            "description": f"App generada por IoTaaS para {app_name}"
        }
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        return response.json().get("id")
    print(f"[ERROR create_application] {response.status_code}: {response.text}")
    return None

# 📡 Crear un nuevo dispositivo OTAA en ChirpStack
def create_device(dev_eui, name, application_id, device_profile_id):
    url = f"{CHIRPSTACK_API_URL}/devices"
    payload = {
        "device": {
            "application_id": application_id,
            "dev_eui": dev_eui,
            "name": name,
            "description": f"Dispositivo creado desde IoTaaS",
            "device_profile_id": device_profile_id,
            "skip_fcnt_check": True,
            "is_disabled": False
        }
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        return response.json()
    print(f"[ERROR create_device] {response.status_code}: {response.text}")
    return None

# 🔑 Establecer las claves OTAA del dispositivo (AppKey)
def set_device_keys(dev_eui, app_key):
    url = f"{CHIRPSTACK_API_URL}/devices/{dev_eui}/keys"
    payload = {
        "device_keys": {
            "dev_eui": dev_eui,
            "nwk_key": app_key,
            "app_key": app_key
        }
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        return response.json()
    print(f"[ERROR set_device_keys] {response.status_code}: {response.text}")
    return None