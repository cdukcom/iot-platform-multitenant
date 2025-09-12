#db.py motor de conexión con la base de datos en Mongo
from motor.motor_asyncio import AsyncIOMotorClient
import os

# Solo carga .env si estás en local (Railway ya provee las variables de entorno)
if os.getenv("RAILWAY_STATIC_URL") is None:
    from dotenv import load_dotenv
    load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")

client = AsyncIOMotorClient(MONGODB_URI)
db = client["PLATAFORMA_IOT"]  # Asegúrate de usar el nombre correcto de la base

# Colecciones accesibles
tenants_collection = db["tenants"]
users_collection = db["users"]
devices_collection = db["devices"]
alerts_collection = db["alerts"]
logs_collection = db["logs"]
devicekeys_collection = db["devicekeys"]
dp_templates_cache_collection = db["dp_templates_cache"]
device_profiles_collection = db["device_profiles"]