from pydantic import BaseModel, Field, EmailStr
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
    dev_eui: str  # ➕ Este es el identificador único que usas desde el QR
    name: Optional[str] = "Sin nombre"  # puedes asignar uno más adelante
    type: Literal["gateway", "panic_button"] = "gateway"
    status: Literal["active", "inactive"] = "active"
    location: Optional[str]
    created_at: datetime = Field(default_factory=datetime.utcnow)


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
