"""tadawul-web — منصة تداول الذكية (FastAPI). Run: uvicorn app.main:app --port 8080"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]


def _load_env():
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from . import chat, engine_bridge as eb, paper, scanner, tv, yahoo  # noqa: E402
from .markets import MARKETS, POPULAR, UNIVERSE, market_of, valid_symbol  # noqa: E402

TOKEN = os.environ.get("TOKEN") or os.environ.get("ACCESS_TOKEN", "")
COOKIE = "tw_k"
app = FastAPI(title="tadawul-web", docs_url=None, redoc_url=None, openapi_url=None)


def _ok(tok: str | None) -> bool:
    return bool(TOKEN) and bool(tok) and hmac.compare_digest(tok, TOKEN)


DENIED = """<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>منصة تداول</title><body style="background:#0b0f17;color:#e6edf3;font-family:system-ui;display:grid;place-items:center;height:100vh">
<div style="text-align:center"><h2>🔒 منصة خاصة</h2><p>افتح الرابط الكامل الذي يحتوي على مفتاح الدخول.</p></div></body></html>"""


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    if path == "/healthz":
        return await call_next(request)
    if path == "/tv/webhook":  # TradingView cannot send cookies/headers → token in query
        if not _ok(request.query_params.get("k")):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
    qk = request.query_params.get("k")
    if _ok(qk):
        q = [(k, v) for k, v in request.query_params.multi_items() if k != "k"]
        from urllib.parse import urlencode
        target = path + (("?" + urlencode(q)) if q else "")
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(COOKIE, TOKEN, max_age=60 * 60 * 24 * 60, httponly=True, secure=True, samesite="lax")
        return resp
    if not _ok(request.cookies.get(COOKIE)):
        if path.startswith("/api/"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return HTMLResponse(DENIED, status_code=401)
    resp = await call_next(request)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@app.on_event("startup")
async def _start():
    if os.environ.get("DISABLE_SCANNER") != "1":
        app.state.stop = scanner.start()


def _sym(s: str) -> str:
    s = (s or "").strip().upper()
    if s.isdigit() and len(s) == 4:
        s += ".SR"
    if not valid_symbol(s):
        raise HTTPException(400, "رمز غير صالح")
    return s


async def _thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"markets": [{"id": k, **v, "universe_size": len(UNIVERSE.get(k) or [])} for k, v in MARKETS.items()],
            "popular": POPULAR, "forward_available": bool(os.environ.get("GROKBOT_WEBHOOK_URL")),
            "scanner": scanner.status, "n_agents": len(eb.SPECS)}


@app.get("/api/search")
async def search(q: str):
    try:
        return {"results": await _thread(yahoo.search, q[:60])}
    except Exception as exc:
        return {"results": [], "error": str(exc)[:200]}


@app.get("/api/quote")
async def quote(symbol: str):
    s = _sym(symbol)
    try:
        return await _thread(yahoo.quote, s)
    except Exception as exc:
        raise HTTPException(404, str(exc)[:200])


@app.get("/api/chart")
async def chart_(symbol: str, tf: str = "1Y"):
    s = _sym(symbol)
    try:
        return await _thread(yahoo.chart, s, tf.upper())
    except Exception as exc:
        raise HTTPException(404, str(exc)[:200])


@app.get("/api/analyze")
async def analyze(symbol: str, force: int = 0):
    s = _sym(symbol)
    try:
        p = await _thread(eb.analyse, s, bool(force))
    except Exception as exc:
        raise HTTPException(404, f"NOT FOUND — {str(exc)[:250]}")
    await _thread(paper.add_signal, p, "تحليل يدوي من المنصة")
    return p


@app.get("/api/pine")
async def pine(symbol: str):
    s = _sym(symbol)
    p = eb.cached(s) or await _thread(eb.analyse, s)
    return PlainTextResponse(tv.pine(p))


@app.get("/api/home")
def home(market: str = "SA"):
    m = market.upper()
    if m not in MARKETS:
        raise HTTPException(400, "سوق غير معروف")
    scan = scanner.load(m)
    for r in (scan or {}).get("rows", []):
        r["verdict_en"] = (r.get("verdict_en") or "HOLD").upper()
    cands = [r for r in (scan or {}).get("rows", []) if (r.get("verdict_en") or "").upper() == "BUY"]
    near = [r for r in (scan or {}).get("rows", []) if (r.get("verdict_en") or "").upper() != "BUY"][:8]
    return {"market": m, "info": MARKETS[m], "scan": None if not scan else {
                "scanned_at": scan["scanned_at"], "duration_s": scan["duration_s"], "n": len(scan["rows"]),
                "errors": scan["errors"], "universe_size": len(scan["universe"]), "every_h": scan.get("every_h")},
            "candidates": cands, "top_ranked": near, "paper": paper.summary(m), "scanner": scanner.status,
            "universe": UNIVERSE.get(m) or POPULAR.get(m) or []}


@app.get("/api/paper")
def paper_all():
    return paper.summary(None)


@app.get("/api/backtest")
def backtest():
    f = eb.BRAIN / "knowledge" / "candlesticks" / "backtest.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    rows = []
    for k, v in d["patterns"].items():
        best = []
        for lbl, n, h in (("بلا شروط", v["n"], v["hit10"]), ("عند مستوى + حجم", v.get("ctx_n"), v.get("ctx_hit10")),
                          ("مع شمعة تأكيد", v.get("conf_n"), v.get("conf_hit10")), ("سلّم الأدلة ≥4", v.get("full_n"), v.get("full_hit10"))):
            if n and n >= 20 and h is not None:
                best.append({"setup": lbl, "n": n, "hit10": round(h * 100), "edge": round((h - v["base10_dir"]) * 100)})
        good = [b for b in best if b["edge"] >= 5]
        if good:
            rows.append({"pattern": k, "name_ar": v["name_ar"], "dir": v["dir"], "base10": round(v["base10_dir"] * 100),
                         "setups": sorted(good, key=lambda b: -b["edge"])})
    rows.sort(key=lambda r: -r["setups"][0]["edge"])
    return {"generated_at": d.get("generated_at"), "period": d.get("period"), "span": d.get("span"),
            "n_tickers": len(d.get("tickers") or []), "rows": rows,
            "source": "tadawul-brain/knowledge/candlesticks/backtest.json (اختبار خلفي على قائمة المراقبة السعودية)"}


@app.post("/api/chat")
async def chat_(request: Request):
    body = await request.json()
    msg = str(body.get("message") or "")[:1000]
    sym = body.get("symbol")
    p = q = None
    if sym:
        s = _sym(sym)
        p = eb.cached(s)
        intent = chat.intent(msg)
        if p is None and intent not in ("help", "price"):
            try:
                p = await _thread(eb.analyse, s)
            except Exception:
                p = None
        try:
            q = await _thread(yahoo.quote, s)
        except Exception:
            q = None
    reply = chat.answer(msg, p, q)
    fwd = None
    if body.get("forward"):
        fwd = await _thread(tv.forward, f"سؤال من منصة تداول عن {sym or '-'}: {msg}", {"ticker": sym, "kind": "chat"})
    return {"reply": reply, "forwarded": fwd}


@app.get("/api/tvhelp")
def tvhelp(request: Request):
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:8080"
    scheme = "https" if "trycloudflare" in host or request.headers.get("x-forwarded-proto") == "https" else request.url.scheme
    return {"webhook_url": f"{scheme}://{host}/tv/webhook?k={TOKEN}",
            "template": '{"ticker":"{{ticker}}","exchange":"{{exchange}}","price":{{close}},"interval":"{{interval}}","message":"{{strategy.order.action}} {{ticker}}"}',
            "template_simple": '{"ticker":"{{ticker}}","exchange":"{{exchange}}","price":{{close}},"message":"تنبيه سعر"}'}


@app.get("/api/alerts")
def alerts():
    return {"alerts": list(reversed(tv.load_alerts()))[:50]}


@app.post("/tv/webhook")
async def tv_webhook(request: Request):
    raw = (await request.body()).decode("utf-8", errors="replace")[:5000]
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            payload = {"message": raw}
    except Exception:
        payload = {"message": raw}
        for tok in raw.replace(",", " ").split():
            if ":" in tok and tok.split(":")[0].isupper():
                payload["ticker"] = tok
                break
    item = tv.receive(payload, raw)
    return {"ok": item.get("status") != "error", "id": item["id"], "yahoo": item.get("yahoo"), "status": item["status"]}


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})
