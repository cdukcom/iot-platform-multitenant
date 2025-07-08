import firebase_admin
from firebase_admin import credentials, auth
import os
import json

if not firebase_admin._apps:
    json_cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not json_cred:
        raise Exception("GOOGLE_APPLICATION_CREDENTIALS_JSON not set")

    cred_dict = json.loads(json_cred)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    
def verify_token(id_token: str):
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        return None
