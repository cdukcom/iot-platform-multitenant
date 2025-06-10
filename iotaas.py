from fastapi import FastAPI
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Conexión a MongoDB Atlas
client = MongoClient(os.getenv("MONGODB_URI"))
db = client["iot-platform"]  # Puedes cambiar el nombre de la base

@app.get("/")
def read_root():
    return {"message": "IoTaaS multitenant backend is running"}
