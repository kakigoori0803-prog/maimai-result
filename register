# register_router.py  ← 新規ファイル
from fastapi import APIRouter
from pydantic import BaseModel
import os, secrets

router = APIRouter()

class RegisterResponse(BaseModel):
    ingest_url: str
    bearer: str
    user_id: str

@router.post("/register", response_model=RegisterResponse, tags=["default"])
def register():
    # 返す値（Renderの環境変数で上書き可能）
    ingest = os.getenv("MRC_INGEST_URL", "https://maimai-result.onrender.com/ingest")
    # ingest 側で使っている認証トークンと同じ値を MRC_DEFAULT_BEARER に入れておくのが一番簡単
    bearer = os.getenv("MRC_DEFAULT_BEARER", "")
    if not bearer:
        # 予備（未設定でも一応返す）。本番は環境変数で固定を推奨
        bearer = secrets.token_hex(16)
    user_id = secrets.token_hex(16)
    return {"ingest_url": ingest, "bearer": bearer, "user_id": user_id}
