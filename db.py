from motor.motor_asyncio import AsyncIOMotorClient
import os

MONGODB_URI = os.getenv("MONGODB_URI")

client = AsyncIOMotorClient(MONGODB_URI)
db = client["iot_platform"]  # nombre de tu base

# Colecciones accesibles
tenants_collection = db["tenants"]
users_collection = db["users"]
devices_collection = db["devices"]
