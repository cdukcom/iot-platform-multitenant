import grpc

class ApiKeyAuthInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def intercept_unary_unary(self, continuation, client_call_details, request):
        metadata = []
        if client_call_details.metadata is not None:
            metadata = list(client_call_details.metadata)
        metadata.append(("authorization", f"Bearer {self.api_key}"))

        client_call_details = client_call_details._replace(metadata=metadata)
        return continuation(client_call_details, request)
