from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import json, os, hashlib, csv
from io import StringIO
from datetime import datetime

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False
)

# ====== 設定 ======
DB_FILE   = "db.json"
API_TOKEN = os.getenv("API_TOKEN", "changeme")
LOGO_URL  = os.getenv("LOGO_URL", "")  # ここに自分のロゴURLを入れると画像表示、空ならテキストロゴ

# ====== DB utils ======
def load_db():
    if not os.path.exists(DB_FILE): return []
    with open(DB_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

# ====== API ======
@app.get("/health")
def health(): return {"ok": True}

@app.post("/ingest")
async def ingest(request: Request):
    # 認証（ショートカットから Authorization: Bearer <API_TOKEN> を送る）
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    body   = await request.json()
    items  = body.get("items", [])
    src    = body.get("sourceUrl") or ""
    now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db = load_db()
    inserted = 0
    for item in items:
        # 受け取りフォーマット（例）:
        # { title, rate, playedAt, difficulty(optional), level(optional) }
        # 一意キーは title + rate + playedAt
        key = f"{item.get('title','')}|{item.get('rate','')}|{item.get('playedAt','')}"
        uniq = hashlib.sha1(key.encode()).hexdigest()
        if not any(r.get("uniq")==uniq for r in db):
            item["uniq"] = uniq
            item["sourceUrl"]  = src
            item["ingestedAt"] = body.get("ingestedAt") or now  # 無ければ今
            db.append(item)
            inserted += 1

    save_db(db)
    return JSONResponse({"status":"ok", "inserted": inserted, "total": len(db)})

@app.get("/data")
def data(): return load_db()

@app.get("/data/pretty", response_class=PlainTextResponse)
def data_pretty():
    return PlainTextResponse(json.dumps(load_db(), ensure_ascii=False, indent=2),
                             media_type="application/json")

@app.get("/data.csv", response_class=PlainTextResponse)
def data_csv():
    buf = StringIO()
    fieldnames = ["playedAt","title","difficulty","level","rate","ingestedAt","sourceUrl"]
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in load_db():
        w.writerow({k: r.get(k,"") for k in fieldnames})
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")

# ====== View (見やすい画面) ======
def esc(s:str)->str:
    return str(s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def date_of(played_at:str)->str:
    # "2025/08/30 12:34" → "2025/08/30"
    if not played_at: return ""
    return played_at.split()[0]

def human_rate(v):
    try:
        return f"{float(v):.4f}%"
    except:  # 数値じゃなければそのまま
        return esc(v)

def diff_badge(d):
    d = (d or "").lower()
    color = "#64748b"  # default slate
    name = d.upper() if d else "-"
    if "basic" in d:   color, name = "#22c55e","BASIC"
    if "advanced" in d or "adv"==d: color, name = "#f59e0b","ADVANCED"
    if "expert" in d:  color, name = "#ef4444","EXPERT"
    if "master" in d:  color, name = "#8b5cf6","MASTER"
    if "remaster" in d or "re:master" in d: color, name = "#06b6d4","Re:MASTER"
    return f"<span class='badge' style='background:{color}'>{name}</span>"

@app.get("/view", response_class=HTMLResponse)
def view():
    data = load_db()
    # 最新取り込み順
    data.sort(key=lambda r: r.get("ingestedAt",""), reverse=True)

    # 日付ごとにグルーピング
    groups = {}
    for r in data:
        d = date_of(r.get("playedAt",""))
        groups.setdefault(d, []).append(r)

    # 24時間以内なら「NEW」表示
    try:
        cutoff = datetime.now().timestamp() - 24*3600
    except: 
        cutoff = 0

    # ロゴ
    logo_html = (f"<img src='{esc(LOGO_URL)}' alt='logo' class='logo'>"
                 if LOGO_URL else "<div class='logo-text'>maimai result</div>")

    # 行生成
    cards = []
    for d, rows in sorted(groups.items(), key=lambda x:x[0], reverse=True):
        rows_html = []
        for r in rows:
            is_new = False
            try:
                ts = datetime.strptime(r.get("ingestedAt",""), "%Y-%m-%d %H:%M:%S").timestamp()
                is_new = ts >= cutoff
            except:
                pass
            title = esc(r.get("title",""))
            diff  = diff_badge(r.get("difficulty") or r.get("level"))
            rate  = human_rate(r.get("rate",""))
            played_at = esc(r.get("playedAt",""))
            new_tag = "<span class='new'>NEW</span>" if is_new else ""
            rows_html.append(f"""
<li class='row'>
  <div class='left'>
    <div class='title'>{title} {diff} {new_tag}</div>
    <div class='meta'>{played_at}</div>
  </div>
  <div class='right'>{rate}</div>
</li>
""")
        cards.append(f"""
<section class='card'>
  <h2>{esc(d) or '未日付'}</h2>
  <ul class='list'>
    {''.join(rows_html)}
  </ul>
</section>
""")

    html = f"""<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>maimai result</title>
<style>
  :root {{
    --bg: #0f172a;       /* 背景色（好みで変えてOK） */
    --card: #111827;
    --text: #e5e7eb;
    --muted: #94a3b8;
    --accent: linear-gradient(135deg,#06b6d4,#8b5cf6);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: -apple-system, system-ui, Segoe UI, Roboto, 'Hiragino Kaku Gothic ProN', 'Noto Sans JP', sans-serif;
    background: var(--bg); color: var(--text);
    background-image: radial-gradient(ellipse at top, rgba(99,102,241,.15), transparent 40%),
                      radial-gradient(ellipse at bottom, rgba(20,184,166,.15), transparent 40%);
  }}
  header {{
    display:flex; align-items:center; justify-content:space-between;
    padding: 18px 14px; position: sticky; top: 0; z-index: 10;
    backdrop-filter: blur(10px);
    background: linear-gradient(180deg, rgba(15,23,42,.85), rgba(15,23,42,.55));
    border-bottom: 1px solid rgba(255,255,255,.06);
  }}
  .logo {{ height:28px; }}
  .logo-text {{
    font-weight:800; font-size:20px;
    background: var(--accent); -webkit-background-clip:text; background-clip:text; color:transparent;
  }}
  .toolbar a {{
    color:var(--muted); text-decoration:none; margin-left:14px; font-size:13px;
  }}
  main {{ padding: 14px; }}
  .card {{
    background: var(--card); border:1px solid rgba(255,255,255,.06);
    border-radius: 14px; padding: 8px 10px; margin: 10px 0 14px;
    box-shadow: 0 6px 20px rgba(0,0,0,.25);
  }}
  h2 {{ margin:8px 6px 4px; font-size:14px; color:var(--muted); font-weight:600; }}
  .list {{ list-style:none; padding:0; margin:0; }}
  .row {{
    display:flex; align-items:center; justify-content:space-between;
    padding:10px 8px; border-top:1px solid rgba(255,255,255,.06);
  }}
  .row:first-child {{ border-top:none; }}
  .left .title {{ font-size:15px; font-weight:600; }}
  .left .meta {{ font-size:12px; color:var(--muted); margin-top:2px; }}
  .right {{ font-variant-numeric: tabular-nums; font-size:16px; font-weight:700; }}
  .badge {{
    display:inline-block; padding:2px 6px; border-radius:999px; color:#fff; font-size:11px; margin-left:6px;
  }}
  .new {{
    margin-left:8px; font-size:10px; color:#22c55e; font-weight:700; border:1px solid #22c55e;
    padding:1px 4px; border-radius:6px;
  }}
  .empty {{
    text-align:center; color:var(--muted); padding:40px 8px;
  }}
</style>
<header>
  {logo_html}
  <nav class="toolbar">
    <a href="/data/pretty">JSON</a>
    <a href="/data.csv">CSV</a>
    <a href="/health">health</a>
  </nav>
</header>
<main>
  {''.join(cards) if cards else '<div class="empty">データがありません。ショートカットから同期してね。</div>'}
</main>
"""
    return HTMLResponse(html)
