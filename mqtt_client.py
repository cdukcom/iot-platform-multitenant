# mqtt_client.py
import asyncio
from aiomqtt import Client
from dotenv import load_dotenv
import os

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "maglev.proxy.rlwy.net")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "#")

async def mqtt_handler():
    async with Client(MQTT_HOST, port=MQTT_PORT) as client:
        await client.subscribe(MQTT_TOPIC)
        print(f"Suscrito a: {MQTT_TOPIC}")
        async for message in client.messages:
            print(f"[{message.topic}] {message.payload.decode()}")

if __name__ == "__main__":
    asyncio.run(mqtt_handler())