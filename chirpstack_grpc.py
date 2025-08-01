import os
import grpc
from grpc_auth_interceptor import ApiKeyAuthInterceptor
from chirpstack_proto.api.device import device_pb2, device_pb2_grpc
from chirpstack_proto.api.device_profile import device_profile_pb2, device_profile_pb2_grpc

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