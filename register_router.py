from fastapi import APIRouter, HTTPException
import os, secrets

router = APIRouter()

@router.post("/register", tags=["default"])
def register():
    # /ingest と同じ認証トークンを返す
    token = os.getenv("API_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="API_TOKEN is not set")

    # /ingest のURL（相対でOK。フルURLにしたいなら環境変数で上書き）
    api_url = os.getenv("MRC_INGEST_URL", "/ingest")

    user_id = secrets.token_hex(16)
    # mrc.js が期待する形で返す
    return {"ok": True, "token": token, "api_url": api_url, "user_id": user_id}
