from fastapi import APIRouter, HTTPException, Body, Depends
from auth import verify_token as verify_firebase_token
from crud import upsert_device_profile_from_template_name

router = APIRouter(prefix="/device-profiles", tags=["device-profiles"])

@router.post("/ensure")
async def ensure_device_profile(body: dict = Body(...), uid=Depends(verify_firebase_token)):
    try:
        tenant_id = body["tenant_id"]
        model = body["model"].strip().upper()
        template_name = body["template_name"].strip()
        profile_name = body.get("profile_name") or f"dp-{model.lower()}"
    except Exception:
        raise HTTPException(400, "Campos requeridos: tenant_id, model, template_name")

    result = await upsert_device_profile_from_template_name(
        tenant_id=tenant_id, model=model,
        template_name=template_name, profile_name=profile_name
    )
    if not result.get("ok"):
        code = result.get("code")
        raise HTTPException(404 if code == "template_not_found" else 502, detail=result)
    return result
