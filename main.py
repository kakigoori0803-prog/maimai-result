from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os, json, hashlib
from datetime import datetime

app = FastAPI()
API_TOKEN = os.getenv("API_TOKEN", "changeme")  # Renderで環境変数から上書き
DB_FILE = "plays.json"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/ingest")
async def ingest(req: Request):
    auth = req.headers.get("Authorization", "")
    if auth != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await req.json()
    items = payload.get("items", [])
    src = payload.get("sourceUrl", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db = load_db()
    inserted = 0
    for it in items:
        title = (it.get("title") or "").strip()
        rate = it.get("rate")
        played_at = (it.get("playedAt") or "").strip()
        uniq_src = f"{title}|{rate}|{played_at}"
        uniq = hashlib.sha1(uniq_src.encode()).hexdigest()
        if not any(x.get("uniq") == uniq for x in db):
            it["uniq"] = uniq
            it["sourceUrl"] = src
            it["ingestedAt"] = now
            db.append(it)
            inserted += 1

    save_db(db)
    return JSONResponse({"status": "ok", "inserted": inserted, "total": len(db)})

@app.get("/data")
def data():
    return load_db()
