import grpc
import os
from chirpstack_proto.chirpstack_api import (
    device_pb2,
    device_pb2_grpc,
    device_profile_pb2,
    device_profile_pb2_grpc,
)

CHIRPSTACK_GRPC_ADDRESS = os.getenv("CHIRPSTACK_GRPC_ADDRESS", "localhost:8080")
CHIRPSTACK_API_TOKEN = os.getenv("CHIRPSTACK_API_TOKEN", "")

class ChirpstackGRPCClient:
    def __init__(self):
        self.channel = grpc.insecure_channel(CHIRPSTACK_GRPC_ADDRESS)
        
        # Inicializar stubs
        self.device_stub = device_pb2_grpc.DeviceServiceStub(self.channel)
        self.device_profile_stub = device_profile_pb2_grpc.DeviceProfileServiceStub(self.channel)
        
        # Token de autorización
        self.metadata = [("authorization", f"Bearer {CHIRPSTACK_API_TOKEN}")]

    def get_device(self, dev_eui: str):
        request = device_pb2.GetDeviceRequest(dev_eui=dev_eui)
        return self.device_stub.Get(request, metadata=self.metadata)

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
        return self.device_stub.Create(request, metadata=self.metadata)

    def delete_device(self, dev_eui: str):
        request = device_pb2.DeleteDeviceRequest(dev_eui=dev_eui)
        return self.device_stub.Delete(request, metadata=self.metadata)
    
    def get_device_profile_id_by_name(self, profile_name: str, tenant_id: str) -> str:
        request = device_profile_pb2.ListDeviceProfilesRequest(limit=50, tenant_id=tenant_id)
        response = self.device_profile_stub.List(request, metadata=self.metadata)
        
        for profile in response.result:
            if profile.name == profile_name:
                return profile.id
        
        raise ValueError(f"Perfil de dispositivo '{profile_name}' no encontrado para tenant {tenant_id}")