# main.py
from fastapi import FastAPI, HTTPException, Security, Body, Request, Query
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import json, os, hashlib, csv, re
from io import StringIO
from datetime import datetime
from urllib.parse import urljoin, parse_qs

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False
)

security = HTTPBearer(auto_error=False)

# /register はそのまま（あれば使われます）
try:
    from register_router import router as register_router
    app.include_router(register_router)
except Exception as e:
    print(f"[WARN] register_router not loaded: {e}")

DB_FILE   = "db.json"
API_TOKEN = os.getenv("API_TOKEN", "changeme")
LOGO_URL  = os.getenv("LOGO_URL", "")
PLACEHOLDER_IMG = os.getenv("PLACEHOLDER_IMG", "")

# ---------------- DB utils ----------------
def load_db():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

# ---------------- health ----------------
@app.get("/health")
def health():
    return {"ok": True}

# ---------------- parser ----------------
def parse_detail_html(html: str, url: str) -> dict:
    """
    playlogDetail の HTML を雑にテキスト化して抽出。
    ・タグ分割される数値にも強い
    ・画像の相対URLも絶対化
    """
    def find(pat, src, flags=re.I | re.S):
        m = re.search(pat, src, flags)
        return (m.group(1) if m else "").strip()

    # テキスト化（タグ除去）
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text)

    # ---- title（いくつかの手掛かりを順に）----
    title = (
        find(r'name=["\']music_title["\'][^>]*value=["\']([^"\']+)["\']', html)
        or find(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html)
        or find(r'<img[^>]+alt=["\']([^"\']{2,})["\']', html)   # ジャケ alt
    )

    # ---- rate（% も ％ もOK・テキストから）----
    rate = find(r'([0-9]{2,3}\.[0-9]{4})\s*[％%]', text)

    # ---- playedAt（YYYY/MM/DD HH:MM）----
    played = find(r'(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})', text)

    # ---- difficulty & level ----
    difficulty = find(r'\b(Re:?MASTER|MASTER|EXPERT|ADVANCED|BASIC)\b', text)
    level = (find(r'LEVEL[^0-9]*([0-9]{1,2}\+?)', text)
             or find(r'\b([0-9]{1,2}\+?)\b', text))

    # ---- jacket（相対URL→絶対URL）----
    img = (find(r'<img[^>]+src=["\']([^"\']+\.(?:png|jpg|jpeg|webp))["\']', html)
           or find(r'background-image:\s*url\(["\']?([^"\')]+)["\']?\)', html))
    if img:
        img = urljoin(url or "", img)

    return {
        "title": title,
        "rate": rate,                 # "101.0000"
        "playedAt": played,           # "YYYY/MM/DD HH:MM"
        "difficulty": difficulty,     # "MASTER" etc.
        "level": level,               # "13" / "13+"
        "imageUrl": img or "",
        "sourceUrl": url or "",
    }

# ---------------- ingest helper ----------------
def upsert_from_body(body: dict, now: str) -> int:
    db = load_db()
    inserted = 0

    # items 方式
    items = body.get("items") or []
    if isinstance(items, list) and items:
        src = body.get("sourceUrl") or ""
        for item in items:
            key  = f"{item.get('title','')}|{item.get('rate','')}|{item.get('playedAt','')}"
            uniq = hashlib.sha1(key.encode()).hexdigest()
            if not any(r.get("uniq")==uniq for r in db):
                item["uniq"]       = uniq
                item["sourceUrl"]  = item.get("sourceUrl") or src
                item["ingestedAt"] = body.get("ingestedAt") or now
                db.append(item); inserted += 1
        save_db(db)
        return inserted

    # html 方式
    if isinstance(body.get("html"), str):
        url  = body.get("url") or body.get("sourceUrl") or ""
        html = body.get("html") or ""
        item = parse_detail_html(html, url)
        if item.get("rate") or item.get("playedAt") or item.get("title"):
            key  = f"{item.get('title','')}|{item.get('rate','')}|{item.get('playedAt','')}"
            uniq = hashlib.sha1(key.encode()).hexdigest()
            if not any(r.get("uniq")==uniq for r in db):
                item["uniq"]       = uniq
                item["ingestedAt"] = now
                db.append(item); inserted += 1
        save_db(db)
        return inserted

    raise HTTPException(status_code=400,
        detail="Payload must be {items:[...]} or {html:..., url:...}")

# ---------------- ingest (JSON) ----------------
@app.post("/ingest")
async def ingest(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security),
    body: dict = Body(...)
):
    # 認証：Bearer か ?token
    scheme = (credentials.scheme if credentials else "") or ""
    token_h = (credentials.credentials if credentials else "") or ""
    token_q = request.query_params.get("token") or ""
    if not ((scheme.lower()=="bearer" and token_h==API_TOKEN) or (token_q==API_TOKEN)):
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ins = upsert_from_body(body, now)
    return {"status":"ok","inserted":ins,"total":len(load_db())}

# ---------------- ingest (form / raw JSON) ----------------
@app.post("/ingest_form")
async def ingest_form(
    request: Request,
    token: str = Query("")
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized (token)")

    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty body")

    ctype = request.headers.get("Content-Type", "")
    # x-www-form-urlencoded のときは payload=... を取り出す
    if "application/x-www-form-urlencoded" in ctype:
        q = parse_qs(raw.decode("utf-8"))
        payload = (q.get("payload") or [""])[0]
        if not payload:
            raise HTTPException(status_code=400, detail="Missing 'payload'")
        try:
            body = json.loads(payload)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in payload: {e}")
    else:
        # 素の JSON
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ins = upsert_from_body(body, now)
    return {"status":"ok","inserted":ins,"total":len(load_db())}

# ---------------- data out ----------------
@app.get("/data")
def data():
    return load_db()

@app.get("/data/pretty", response_class=PlainTextResponse)
def data_pretty():
    return PlainTextResponse(
        json.dumps(load_db(), ensure_ascii=False, indent=2),
        media_type="application/json",
    )

@app.get("/data.csv", response_class=PlainTextResponse)
def data_csv():
    buf = StringIO()
    fieldnames = ["playedAt","title","difficulty","level","rate","imageUrl","ingestedAt","sourceUrl"]
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in load_db():
        w.writerow({k: r.get(k, "") for k in fieldnames})
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")

# ---------------- view ----------------
def esc(s: str) -> str:
    return str(s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def date_of(played_at: str) -> str:
    return (played_at or "").split()[0] if played_at else ""

def human_rate(v):
    try: return f"{float(v):.4f}%"
    except: return esc(v)

def diff_badge(d, level=None):
    d_raw = (d or "").strip()
    d_l = d_raw.lower()
    color = "#64748b"; label = d_raw or "-"
    if "basic" in d_l:   color, label = "#22c55e","BASIC"
    elif "advanced" in d_l or d_l == "adv": color, label = "#eab308","ADVANCED"
    elif "expert" in d_l:  color, label = "#ef4444","EXPERT"
    elif "master" in d_l and "re" not in d_l: color, label = "#a855f7","MASTER"
    elif "re:master" in d_l or "remaster" in d_l or "re" == d_l:
        badge = "<span class='badge remaster'>Re:MASTER</span>"
        if level: badge += f"<span class='lvl'>{esc(level)}</span>"
        return badge
    badge = f"<span class='badge' style='background:{color}'>{label}</span>"
    if level: badge += f"<span class='lvl'>{esc(level)}</span>"
    return badge

def rank_class(rate):
    try: r = float(rate)
    except: return "rk-none"
    if r >= 100.5: return "rk-sssplus"
    if r >= 100.0: return "rk-sss"
    if r >= 99.5:  return "rk-ssplus"
    if r >= 99.0:  return "rk-ss"
    if r >= 98.0:  return "rk-splus"
    if r >= 97.0:  return "rk-s"
    return "rk-none"

@app.get("/view", response_class=HTMLResponse)
def view():
    data = load_db()
    data.sort(key=lambda r: r.get("ingestedAt", ""), reverse=True)

    groups = {}
    for r in data:
        groups.setdefault(date_of(r.get("playedAt","")), []).append(r)

    cutoff_ts = datetime.now().timestamp() - 24*3600
    logo_html = (f"<img src='{esc(LOGO_URL)}' alt='logo' class='logo'>" if LOGO_URL
                 else "<div class='logo-text'>maimai result</div>")

    cards = []
    for d, rows in sorted(groups.items(), key=lambda x: x[0], reverse=True):
        rows_html = []
        for r in rows:
            is_new = False
            try:
                ts = datetime.strptime(r.get("ingestedAt",""), "%Y-%m-%d %H:%M:%S").timestamp()
                is_new = ts >= cutoff_ts
            except: pass

            title = esc(r.get("title",""))
            difficulty = r.get("difficulty") or ""
            level = r.get("level")
            rate  = r.get("rate","")
            rate_txt = human_rate(rate)
            rate_cls = rank_class(rate)
            played_at = esc(r.get("playedAt",""))
            new_tag = "<span class='new'>NEW</span>" if is_new else ""

            img = r.get("imageUrl") or PLACEHOLDER_IMG or ""
            img_html = (f"<img class='jacket' src='{esc(img)}' alt=' ' loading='lazy' referrerpolicy='no-referrer'>"
                        if img else "<div class='jacket ph'></div>")

            rows_html.append(f"""
<li class='row'>
  <div class='left'>
    {img_html}
    <div class='txt'>
      <div class='title'>{title or '-'} {diff_badge(difficulty, level)} {new_tag}</div>
      <div class='meta'>{played_at}</div>
    </div>
  </div>
  <div class='right {rate_cls}'>{rate_txt}</div>
</li>""")
        cards.append(f"""
<section class='card'>
  <h2>{esc(d) or '未日付'}</h2>
  <ul class='list'>
    {''.join(rows_html)}
  </ul>
</section>""")

    html = f"""<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>maimai result</title>
<style>
  :root {{
    --bg: #0f172a; --card: #111827; --text: #e5e7eb; --muted: #94a3b8;
    --accent: linear-gradient(135deg,#06b6d4,#8b5cf6);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin:0; font-family:-apple-system,system-ui,Segoe UI,Roboto,'Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif;
    background: var(--bg); color: var(--text);
    background-image: radial-gradient(ellipse at top, rgba(99,102,241,.15), transparent 40%),
                      radial-gradient(ellipse at bottom, rgba(20,184,166,.15), transparent 40%);
  }}
  header {{
    display:flex; align-items:center; justify-content:space-between;
    padding:18px 14px; position:sticky; top:0; z-index:10; backdrop-filter: blur(10px);
    background: linear-gradient(180deg, rgba(15,23,42,.85), rgba(15,23,42,.55));
    border-bottom: 1px solid rgba(255,255,255,.06);
  }}
  .logo {{ height:28px; }}
  .logo-text {{ font-weight:800; font-size:20px; background: var(--accent);
               -webkit-background-clip:text; background-clip:text; color:transparent; }}
  .toolbar a {{ color:var(--muted); text-decoration:none; margin-left:14px; font-size:13px; }}
  main {{ padding: 14px; }}
  .card {{ background: var(--card); border:1px solid rgba(255,255,255,.06);
          border-radius:14px; padding: 8px 10px; margin:10px 0 14px;
          box-shadow: 0 6px 20px rgba(0,0,0,.25); }}
  h2 {{ margin:8px 6px 4px; font-size:14px; color:var(--muted); font-weight:600; }}
  .list {{ list-style:none; padding:0; margin:0; }}
  .row {{ display:flex; align-items:center; justify-content:space-between;
          padding:10px 8px; border-top:1px solid rgba(255,255,255,.06); gap:10px; }}
  .row:first-child {{ border-top:none; }}
  .left {{ display:flex; gap:10px; align-items:center; min-width:0; }}
  .txt {{ min-width:0; }}
  .left .title {{ font-size:15px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:62vw; }}
  .left .meta  {{ font-size:12px; color:var(--muted); margin-top:2px; }}
  .right {{ font-variant-numeric: tabular-nums; font-size:16px; font-weight:700; text-align:right; min-width:88px; }}
  .jacket {{ width:44px; height:44px; border-radius:8px; flex:0 0 auto; object-fit:cover;
             border:1px solid rgba(255,255,255,.08); background:#0b1220; }}
  .jacket.ph {{ display:inline-block; background:repeating-linear-gradient(45deg, #0b1220 0 8px, #0e1627 8px 16px); }}
  .badge {{ display:inline-block; padding:2px 6px; border-radius:999px; color:#fff; font-size:11px; margin-left:6px; }}
  .badge.remaster {{ background:#fff; color:#a855f7; border:2px solid #a855f7; padding:1px 6px; }}
  .lvl {{ margin-left:6px; font-size:11px; color:#e5e7eb; opacity:.9; border:1px dashed rgba(255,255,255,.25); border-radius:999px; padding:1px 6px; }}
  .new {{ margin-left:8px; font-size:10px; color:#22c55e; font-weight:700; border:1px solid #22c55e; padding:1px 4px; border-radius:6px; }}
  .rk-sssplus {{ color:#f97316; background:linear-gradient(90deg,#f59e0b,#f43f5e); -webkit-background-clip:text; color:transparent; }}
  .rk-sss     {{ color:#f97316; }}
  .rk-ssplus  {{ color:#eab308; }}
  .rk-ss      {{ color:#facc15; }}
  .rk-splus   {{ color:#06b6d4; }}
  .rk-s       {{ color:#3b82f6; }}
  .rk-none    {{ color:#e5e7eb; }}
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
  {''.join(cards) if cards else '<div class="empty" style="text-align:center;color:#94a3b8;padding:40px 8px;">データがありません。ショートカットから同期してね。</div>'}
</main>"""
    return HTMLResponse(html)

# 便利API（任意）
def parse_played_at(s: str):
    try: return datetime.strptime(s, "%Y/%m/%d %H:%M")
    except: return None

@app.get("/latest")
def latest(source: str = ""):
    data = load_db()
    latest_dt = None; latest_str = ""
    for r in data:
        if source and r.get("sourceUrl") != source: continue
        pa = parse_played_at(r.get("playedAt",""))
        if pa and (latest_dt is None or pa > latest_dt):
            latest_dt = pa; latest_str = r.get("playedAt","")
    return {"latestPlayedAt": latest_str}
