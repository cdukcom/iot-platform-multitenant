
import asyncio
from fastapi import FastAPI
from db import tenants_collection

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

@app.on_event("startup")
async def startup_event():
    # Keep-alive dummy task for Railway
    async def dummy_keepalive():
        while True:
            await asyncio.sleep(60)

    asyncio.create_task(dummy_keepalive())
