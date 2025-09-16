# routers/smoke/__init__.py
from fastapi import APIRouter

router = APIRouter()

# importa solo lo que ya creaste
from .devices import router as dev_router
router.include_router(dev_router)

# Cuando tengas más smokes, los agregas aquí:
# from .gateways import router as gw_router
# router.include_router(gw_router)
# from .device_profiles import router as dp_router
# router.include_router(dp_router)
