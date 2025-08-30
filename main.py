from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
import json, os, hashlib
from io import StringIO
import csv

app = FastAPI()

DB_FILE = "db.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ingest")
async def ingest(request: Request):
    body = await request.json()
    items = body.get("items", [])
    data = load_db()
    inserted = 0
    for item in items:
        key = json.dumps(item, sort_keys=True)
        uniq = hashlib.sha1(key.encode()).hexdigest()
        if not any(r.get("uniq") == uniq for r in data):
            item["uniq"] = uniq
            item["sourceUrl"] = body.get("sourceUrl")
            item["ingestedAt"] = body.get("ingestedAt")
            data.append(item)
            inserted += 1
    save_db(data)
    return {"status": "ok", "inserted": inserted, "total": len(data)}

@app.get("/data")
def data():
    return load_db()

# 👇 追加した見やすいエンドポイントたち

@app.get("/data/pretty", response_class=PlainTextResponse)
def data_pretty():
    return PlainTextResponse(
        json.dumps(load_db(), ensure_ascii=False, indent=2),
        media_type="application/json"
    )

@app.get("/data.csv", response_class=PlainTextResponse)
def data_csv():
    buf = StringIO()
    fieldnames = ["playedAt", "title", "rate", "ingestedAt", "sourceUrl"]
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in load_db():
        w.writerow({k: r.get(k, "") for k in fieldnames})
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")

@app.get("/view", response_class=HTMLResponse)
def view():
    data = sorted(load_db(), key=lambda x: x.get("ingestedAt",""), reverse=True)
    def esc(s):
        return (str(s or "")
                .replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"))
    rows = "".join(
        f"<tr><td>{esc(r.get('playedAt'))}</td>"
        f"<td>{esc(r.get('title'))}</td>"
        f"<td style='text-align:right'>{r.get('rate','')}</td></tr>"
        for r in data
    )
    html = f"""
<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>maimai-result</title>
<style>
 body{{font-family:-apple-system,system-ui,Segoe UI,Roboto; margin:12px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #e5e7eb;padding:8px}}
 th{{background:#f9fafb;position:sticky;top:0}}
 h1{{font-size:18px;margin:0 0 8px}}
 .toolbar a{{margin-right:12px}}
</style>
<h1>maimai-result</h1>
<div class="toolbar">
  <a href="/data/pretty">JSON</a>
  <a href="/data.csv">CSV</a>
  <a href="/health">health</a>
</div>
<table>
  <thead><tr><th>Played</th><th>Title</th><th style="text-align:right">Rate</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""
    return HTMLResponse(html)
