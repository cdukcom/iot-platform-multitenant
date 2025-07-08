# mqtt_client.py
import asyncio
from aiomqtt import Client
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timezone
import json
import os

# Carga variables de entorno
load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "maglev.proxy.rlwy.net")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "#")
MONGODB_URI = os.getenv("MONGODB_URI")

# Conexión a MongoDB
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client["PLATAFORMA_IOT"]
collection = db["mqtt_data"]

async def mqtt_handler():
    async with Client(MQTT_HOST, port=MQTT_PORT) as client:
            await client.subscribe(MQTT_TOPIC)
            print(f"🟢 Suscrito a: {MQTT_TOPIC}")

            async for message in client.messages:
                print(f"[{message.topic}] {message.payload.decode()}")
            
                try:
                    payload = json.loads(message.payload.decode())

                    if "timestamp" not in payload:
                        payload["timestamp"] = datetime.now(timezone.utc).isoformat()

                    payload["topic"] = str(message.topic)
                    collection.insert_one(payload)
                    print("🟢 Mensaje guardado en MongoDB.")

                except Exception as e:
                    print(f"🔴 Error al procesar mensaje: {e}")
            
if __name__ == "__main__":
    asyncio.run(mqtt_handler())