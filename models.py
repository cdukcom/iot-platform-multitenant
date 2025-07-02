from pydantic import BaseModel, Field, EmailStr, root_validator
from typing import Optional, Literal, Dict
from datetime import datetime

# ---------- Tenant (una comunidad o conjunto) ----------
class TenantModel(BaseModel):
    name: str
    plan: Literal["free", "pro", "enterprise"] = "free"
    max_devices: Optional[int] = 5
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------- Usuario (autenticado por Firebase, asociado a un tenant) ----------
class UserModel(BaseModel):
    uid: str  # Firebase UID
    tenant_id: str  # referencia a Tenant._id
    email: EmailStr
    role: Literal["admin", "user"] = "user"


# ---------- Dispositivo (MG6 o LBM01, registrados por QR o manual) ----------
class DeviceModel(BaseModel):
    tenant_id: str
    dev_eui: str
    name: Optional[str] = "Sin nombre"
    type: Literal["gateway", "panic_button"] = "gateway"
    status: Literal["active", "inactive"] = "active"
    location: Optional[str]
    gateway_id: Optional[str] = None  # ➕ ID del gateway asociado (solo para botones)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @root_validator(pre=True)
    def check_gateway_requirement(cls, values):
        if values.get("type") == "panic_button" and not values.get("gateway_id"):
            raise ValueError("Los botones de pánico deben estar asociados a un gateway (gateway_id).")
        return values


# ---------- Alerta generada por botón de pánico ----------
class AlertModel(BaseModel):
    device_id: str
    tenant_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: Literal["open", "closed"] = "open"
    location: Optional[Dict[str, float]]  # ej. {"lat": 4.65, "lng": -74.1}
    message: Optional[str]  # texto enviado por WhatsApp
    assigned_to: Optional[str]  # uid del usuario notificado


# ---------- Registro de eventos para trazabilidad ----------
class LogModel(BaseModel):
    alert_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action: Literal["created", "closed", "notified", "commented"]
    performed_by: Optional[str]  # uid del usuario
    note: Optional[str]  # observación tipo bitácora
