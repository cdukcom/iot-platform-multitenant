# chirpstack_api.py
import requests
import os

CHIRPSTACK_API_URL = os.getenv("CHIRPSTACK_API_URL", "http://lorawan.duke-villa.com:8080/api")
CHIRPSTACK_API_KEY = os.getenv("CHIRPSTACK_API_KEY")  # Lo pondrás en .env

HEADERS = {
    "Grpc-Metadata-Authorization": f"Bearer {CHIRPSTACK_API_KEY}",
    "Content-Type": "application/json"
}

def get_devices():
    url = f"{CHIRPSTACK_API_URL}/devices"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return response.json().get("result", [])
    else:
        print(f"[ERROR] {response.status_code}: {response.text}")
        return []
