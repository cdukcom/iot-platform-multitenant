import os
import grpc
import re
from grpc_auth_interceptor import ApiKeyAuthInterceptor
from chirpstack_proto.api.device import device_pb2, device_pb2_grpc
from chirpstack_proto.api.device_profile import device_profile_pb2, device_profile_pb2_grpc
from chirpstack_proto.api.tenant import tenant_pb2, tenant_pb2_grpc

# --- Helpers para nombre compuesto de tenant ---
def _slug(s: str) -> str:
    s = (s or "").strip()
    s = "".join(ch.lower() if ch.isalnum() else "_" for ch in s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:64]  # límite de seguridad

def compose_tenant_name(user_email: str, community: str) -> str:
    user_prefix = (user_email or "").split("@", 1)[0]
    return f"{_slug(user_prefix)}_{_slug(community)}"

# Obtener la API Key y el host desde variables de entorno
CHIRPSTACK_API_KEY = os.getenv("CHIRPSTACK_API_KEY")
CHIRPSTACK_GRPC_ADDRESS = os.getenv("CHIRPSTACK_GRPC_ADDRESS", "localhost:8080")

# Crear interceptor de autenticación
auth_interceptor = ApiKeyAuthInterceptor(CHIRPSTACK_API_KEY)

# Crear canal seguro si usas TLS (aquí va con canal inseguro para simplificar)
channel = grpc.intercept_channel(
    grpc.insecure_channel(CHIRPSTACK_GRPC_ADDRESS),
    auth_interceptor
)

class ChirpstackGRPCClient:
    def __init__(self):
        self.channel = channel
        
        # Inicializar stubs
        self.device_stub = device_pb2_grpc.DeviceServiceStub(self.channel)
        self.device_profile_stub = device_profile_pb2_grpc.DeviceProfileServiceStub(self.channel)
        self.tenant_stub = tenant_pb2_grpc.TenantServiceStub(self.channel)
    
    # --- DEVICE ---
    def get_device(self, dev_eui: str):
        request = device_pb2.GetDeviceRequest(dev_eui=dev_eui)
        return self.device_stub.Get(request)

    def create_device(self, dev_eui, name, description, application_id, device_profile_id):
        request = device_pb2.CreateDeviceRequest(
            device=device_pb2.Device(
                dev_eui=dev_eui,
                name=name,
                description=description,
                application_id=application_id,
                device_profile_id=device_profile_id,
            )
        )
        return self.device_stub.Create(request)

    def delete_device(self, dev_eui: str):
        request = device_pb2.DeleteDeviceRequest(dev_eui=dev_eui)
        return self.device_stub.Delete(request)
    
    def get_device_profile_id_by_name(self, profile_name: str, tenant_id: str) -> str:
        request = device_profile_pb2.ListDeviceProfilesRequest(limit=50, tenant_id=tenant_id)
        response = self.device_profile_stub.List(request)
        
        for profile in response.result:
            if profile.name == profile_name:
                return profile.id
        
        raise ValueError(f"Perfil de dispositivo '{profile_name}' no encontrado para tenant {tenant_id}")
    
    # --- TENANT ---
    def get_tenant(self, tenant_id: str):
        """Obtiene un tenant por ID (levanta excepción gRPC si falla)."""
        req = tenant_pb2.GetTenantRequest(id=tenant_id)
        return self.tenant_stub.Get(req)

    def list_tenants(self, limit: int = 50, offset: int = 0, search: str = ""):
        """Lista tenants (paginado simple)."""
        req = tenant_pb2.ListTenantsRequest(limit=limit, offset=offset, search=search)
        return self.tenant_stub.List(req)

    def create_tenant_composed(self, user_email: str, community_name: str,
                           description: str = "", can_have_gateways: bool = True):
       """
       Conveniencia: compone el nombre como userprefix_comunidad y crea el tenant.
       No altera create_tenant existente.
       """
       name = compose_tenant_name(user_email, community_name)
       return self.create_tenant(name=name,
                                 description=description,
                                 can_have_gateways=can_have_gateways)

    def create_tenant(self, name: str, description: str = "", can_have_gateways: bool = True):
        """Crea un tenant en ChirpStack (levanta excepción gRPC si falla)."""
        req = tenant_pb2.CreateTenantRequest(
            tenant=tenant_pb2.Tenant(
               name=name,
               description=description,
               can_have_gateways=can_have_gateways,
            )
        )
        return self.tenant_stub.Create(req)
    
    def delete_tenant(self, tenant_id: str):
        """Elimina un tenant por ID en ChirpStack (levanta excepción gRPC si falla)."""
        req = tenant_pb2.DeleteTenantRequest(id=tenant_id)
        return self.tenant_stub.Delete(req)