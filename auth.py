import firebase_admin
from firebase_admin import credentials, auth
import os
import json

if not firebase_admin._apps:
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        raise Exception("GOOGLE_APPLICATION_CREDENTIALS not set")

    cred = credentials.Certificate(credentials_path)
    firebase_admin.initialize_app(cred)

def verify_token(id_token: str):
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        return None
