# Generated manually: device_profile_pb2_grpc.py
import grpc
from chirpstack_proto.device_profile import device_profile_pb2 as device_profile__pb2
from chirpstack_proto.common import common_pb2 as common__pb2


class DeviceProfileServiceStub(object):
    """Stub for DeviceProfileService."""

    def __init__(self, channel):
        self.Get = channel.unary_unary(
            "/device_profile.DeviceProfileService/Get",
            request_serializer=common__pb2.KeyValue.SerializeToString,
            response_deserializer=device_profile__pb2.DeviceProfile.FromString,
        )


class DeviceProfileServiceServicer(object):
    """The server API for DeviceProfileService."""

    def Get(self, request, context):
        raise NotImplementedError("Method not implemented!")


def add_DeviceProfileServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
        "Get": grpc.unary_unary_rpc_method_handler(
            servicer.Get,
            request_deserializer=common__pb2.KeyValue.FromString,
            response_serializer=device_profile__pb2.DeviceProfile.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "device_profile.DeviceProfileService", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))