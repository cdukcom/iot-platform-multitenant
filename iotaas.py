from fastapi import FastAPI
from db import tenants_collection  # Importa desde tu archivo db.py

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "IoTaaS multitenant backend is running"}

@app.get("/ping-db")
async def ping_db():
    try:
        count = await tenants_collection.count_documents({})
        return {"status": "ok", "tenants_count": count}
    except Exception as e:
        return {"status": "error", "details": str(e)}
