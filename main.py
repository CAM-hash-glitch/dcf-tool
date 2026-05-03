"""
FastAPI server for the DCF tool — production-ready.

Production additions over the local dev version:
  - Reads PORT from env (Render/Railway/Fly all set this)
  - Per-IP rate limiting (in-memory token bucket)
  - Ticker validation (regex, length cap)
  - Query params for WACC, terminal growth, projection years
  - Health check endpoint at /healthz
  - Cache stats endpoint at /api/stats
  - Tightened CORS (still permissive for now since this is a public read-only API)
  - Generic error handler so Python tracebacks don't leak

Run locally:  uvicorn main:app --reload
On Render:    uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import os
import re
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from dcf import get_intrinsic_value, cache_stats


# ------------------------------------------------------------------
# App config
# ------------------------------------------------------------------
app = FastAPI(
    title="DCF Calculator",
    description="Automatic intrinsic value via DCF, public Yahoo Finance data.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# CORS: allow the public site to be embedded / called from anywhere.
# It's a read-only API with no auth, so this is acceptable.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Rate limiting: 30 requests per IP per minute.
# Sliding window with a deque of timestamps. Simple, no Redis needed.
# ------------------------------------------------------------------
RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 60
_rate_buckets: dict[str, deque] = defaultdict(deque)
_rate_lock = Lock()


def _check_rate_limit(ip: str):
    now = time.time()
    cutoff = now - RATE_WINDOW_SECONDS
    with _rate_lock:
        bucket = _rate_buckets[ip]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            retry = int(bucket[0] + RATE_WINDOW_SECONDS - now) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({RATE_LIMIT}/min). Try again in {retry}s.",
            )
        bucket.append(now)


def _client_ip(request: Request) -> str:
    # Render/Fly/most PaaS sit behind a proxy; respect X-Forwarded-For
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------------
# Ticker validation
# ------------------------------------------------------------------
# Allow up to 6 letters/dots/dashes. Covers BRK.B, RY-T, etc.
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")


def _validate_ticker(ticker: str) -> str:
    t = ticker.upper().strip()
    if not TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker format.")
    return t


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    """Health check for the platform's uptime monitor."""
    return {"ok": True, "cache": cache_stats()}


@app.get("/api/stats")
def stats():
    return {"cache": cache_stats(), "rate_limit_per_min": RATE_LIMIT}


@app.get("/api/dcf/{ticker}")
def dcf_endpoint(
    ticker: str,
    request: Request,
    wacc: float = Query(0.09, ge=0.03, le=0.25, description="Weighted avg cost of capital (decimal)"),
    tg: float = Query(0.025, ge=0.0, le=0.05, description="Terminal growth rate (decimal)"),
    years: int = Query(5, ge=3, le=10, description="Projection horizon"),
):
    _check_rate_limit(_client_ip(request))
    t = _validate_ticker(ticker)

    if wacc <= tg:
        raise HTTPException(status_code=400, detail="WACC must exceed terminal growth.")

    result = get_intrinsic_value(t, wacc=wacc, terminal_growth=tg, years=years)
    if "error" in result:
        return JSONResponse(status_code=400, content=result)
    return result


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Catch-all so Python tracebacks never reach the user."""
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error. Please try again."},
    )


# ------------------------------------------------------------------
# UI (single-page, no separate frontend)
# ------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_PAGE


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="description" content="Automatic DCF intrinsic value calculator. Enter a ticker, get an estimated fair value." />
<title>DCF Calculator</title>
<style>
  :root {
    --bg: #0b0d12;
    --panel: #14171f;
    --panel-2: #1a1e28;
    --border: #232836;
    --text: #e6e8ee;
    --muted: #8a92a6;
    --accent: #4f8cff;
    --green: #2ecc71;
    --red: #e74c3c;
    --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    line-height: 1.5;
  }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 32px 24px 80px; }
  header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 28px; flex-wrap: wrap; gap: 8px; }
  h1 { font-size: 22px; margin: 0; font-weight: 600; letter-spacing: -0.01em; }
  .tag { color: var(--muted); font-size: 12px; font-family: var(--mono); }

  .search {
    display: flex; gap: 10px; margin-bottom: 18px;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 10px;
  }
  .search input {
    flex: 1; background: transparent; border: none; color: var(--text);
    font-size: 16px; padding: 10px 12px; outline: none; font-family: var(--mono);
    text-transform: uppercase; min-width: 0;
  }
  .search input::placeholder { text-transform: none; font-family: inherit; color: var(--muted); }
  .search button {
    background: var(--accent); color: white; border: none;
    padding: 10px 22px; border-radius: 8px; font-weight: 600; font-size: 14px;
    cursor: pointer; transition: filter 0.15s;
  }
  .search button:hover { filter: brightness(1.1); }
  .search button:disabled { opacity: 0.5; cursor: wait; }

  .controls { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; align-items: center; font-size: 13px; color: var(--muted); }
  .controls label { display: flex; align-items: center; gap: 8px; }
  .controls input[type="number"] {
    background: var(--panel); border: 1px solid var(--border); color: var(--text);
    padding: 6px 8px; border-radius: 6px; width: 70px; font-family: var(--mono); font-size: 13px;
  }
  .controls .reset { background: none; border: 1px solid var(--border); color: var(--muted); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }

  .quick { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 24px; }
  .quick button {
    background: var(--panel); color: var(--muted); border: 1px solid var(--border);
    padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer;
    font-family: var(--mono);
  }
  .quick button:hover { color: var(--text); border-color: var(--accent); }

  .error {
    background: rgba(231, 76, 60, 0.1); border: 1px solid rgba(231, 76, 60, 0.3);
    color: #ff8a7a; padding: 14px 18px; border-radius: 8px; margin-bottom: 20px; font-size: 14px;
  }

  .hero {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 28px; margin-bottom: 20px;
  }
  .hero .ticker { font-family: var(--mono); color: var(--muted); font-size: 13px; margin-bottom: 4px; }
  .hero .company { font-size: 20px; font-weight: 500; margin-bottom: 20px; }
  .hero .row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
  .hero .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
  .hero .value { font-size: 28px; font-weight: 600; font-family: var(--mono); }
  .hero .value.up { color: var(--green); }
  .hero .value.down { color: var(--red); }

  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 800px) { .grid2 { grid-template-columns: 1fr; } .hero .row { grid-template-columns: 1fr; gap: 14px; } }

  .panel {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 22px;
  }
  .panel h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em;
              color: var(--muted); margin: 0 0 16px 0; font-weight: 600; }

  table { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 13px; }
  table td, table th { padding: 8px 6px; text-align: right; border-bottom: 1px solid var(--border); }
  table th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; }
  table td:first-child, table th:first-child { text-align: left; color: var(--muted); }

  .sens td { text-align: center; }
  .sens td.heat { font-weight: 600; }

  .footnote { color: var(--muted); font-size: 12px; margin-top: 28px; line-height: 1.6; }
  .footnote a { color: var(--accent); text-decoration: none; }
  .cached-badge { display: inline-block; margin-left: 8px; padding: 2px 6px; background: rgba(79,140,255,0.15); color: var(--accent); border-radius: 4px; font-size: 10px; font-family: var(--mono); }

  .skeleton { color: var(--muted); text-align: center; padding: 60px 0; font-size: 14px; }
  .spinner {
    display: inline-block; width: 14px; height: 14px;
    border: 2px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.7s linear infinite;
    vertical-align: middle; margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>DCF Calculator</h1>
    <span class="tag">automatic intrinsic value · yahoo finance</span>
  </header>

  <div class="search">
    <input id="ticker" placeholder="Enter ticker (e.g. AAPL, EQT, TSM)" autocomplete="off" maxlength="6" />
    <button id="go">Calculate</button>
  </div>

  <div class="controls">
    <label>WACC <input type="number" id="wacc" value="9" min="3" max="25" step="0.5" />%</label>
    <label>Terminal growth <input type="number" id="tg" value="2.5" min="0" max="5" step="0.25" />%</label>
    <label>Years <input type="number" id="years" value="5" min="3" max="10" step="1" /></label>
    <button class="reset" id="reset">Reset to defaults</button>
  </div>

  <div class="quick" id="quick"></div>

  <div id="output"></div>

  <div class="footnote">
    <strong>Method:</strong> 5-year FCF projection using historical revenue CAGR for growth (clamped −10%/+25%),
    9% WACC, 2.5% terminal growth (Gordon model). Equity value = enterprise value − net debt.
    Data: Yahoo Finance via yfinance, cached 1 hour.
    <br><br>
    <strong>Caveats:</strong> Flat WACC assumption, no segment build, no margin modeling.
    Useful as a directional sanity check, not a substitute for a real model.
    <br><br>
    <a href="/docs">API docs</a> · Built with FastAPI
  </div>
</div>

<script>
const QUICK_TICKERS = ["AAPL","MSFT","GOOGL","NVDA","TSM","EQT","INTC","KRC","SEI"];
const quickEl = document.getElementById("quick");
QUICK_TICKERS.forEach(t => {
  const b = document.createElement("button");
  b.textContent = t;
  b.onclick = () => { document.getElementById("ticker").value = t; run(); };
  quickEl.appendChild(b);
});

const fmt = (n) => {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return (n/1e12).toFixed(2) + "T";
  if (abs >= 1e9)  return (n/1e9).toFixed(2) + "B";
  if (abs >= 1e6)  return (n/1e6).toFixed(2) + "M";
  if (abs >= 1e3)  return (n/1e3).toFixed(2) + "K";
  return n.toFixed(2);
};
const fmtPrice = (n) => n === null || n === undefined ? "—" : "$" + n.toFixed(2);
const fmtPct = (n) => n === null || n === undefined ? "—" : (n > 0 ? "+" : "") + n.toFixed(1) + "%";

document.getElementById("go").onclick = run;
document.getElementById("ticker").addEventListener("keydown", e => {
  if (e.key === "Enter") run();
});
document.getElementById("reset").onclick = () => {
  document.getElementById("wacc").value = 9;
  document.getElementById("tg").value = 2.5;
  document.getElementById("years").value = 5;
};

async function run() {
  const ticker = document.getElementById("ticker").value.trim().toUpperCase();
  if (!ticker) return;
  const wacc = parseFloat(document.getElementById("wacc").value) / 100;
  const tg = parseFloat(document.getElementById("tg").value) / 100;
  const years = parseInt(document.getElementById("years").value, 10);

  const out = document.getElementById("output");
  const btn = document.getElementById("go");
  btn.disabled = true;
  out.innerHTML = '<div class="skeleton"><span class="spinner"></span>Fetching ' + ticker + '…</div>';

  try {
    const url = `/api/dcf/${ticker}?wacc=${wacc}&tg=${tg}&years=${years}`;
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok || data.error) {
      out.innerHTML = '<div class="error">' + (data.error || data.detail || "Something went wrong.") + '</div>';
      return;
    }
    render(data);
    // Update URL for shareability
    history.replaceState(null, "", `?t=${ticker}&wacc=${wacc}&tg=${tg}&years=${years}`);
  } catch (e) {
    out.innerHTML = '<div class="error">Network error: ' + e.message + '</div>';
  } finally {
    btn.disabled = false;
  }
}

function render(d) {
  const mos = d.margin_of_safety_pct;
  const mosClass = mos === null ? "" : (mos > 0 ? "up" : "down");
  const a = d.assumptions, m = d.model, s = d.sensitivity;

  const flat = s.grid.flat().filter(x => x !== null);
  const min = Math.min(...flat), max = Math.max(...flat);
  const heatColor = (v) => {
    if (v === null) return "transparent";
    const t = (v - min) / (max - min || 1);
    const r = Math.round(231 - t * 180);
    const g = Math.round(76 + t * 130);
    const b = Math.round(60 + t * 50);
    return `rgba(${r},${g},${b},0.18)`;
  };

  const cachedBadge = d._cached ? '<span class="cached-badge">cached</span>' : '';

  document.getElementById("output").innerHTML = `
    <div class="hero">
      <div class="ticker">${d.ticker}${cachedBadge}</div>
      <div class="company">${d.company}</div>
      <div class="row">
        <div>
          <div class="label">Intrinsic Value</div>
          <div class="value">${fmtPrice(d.intrinsic_value_per_share)}</div>
        </div>
        <div>
          <div class="label">Current Price</div>
          <div class="value">${fmtPrice(d.current_price)}</div>
        </div>
        <div>
          <div class="label">Margin of Safety</div>
          <div class="value ${mosClass}">${fmtPct(mos)}</div>
        </div>
      </div>
    </div>

    <div class="grid2">
      <div class="panel">
        <h3>Assumptions</h3>
        <table>
          <tr><td>Growth rate</td><td>${a.growth_rate_pct}%</td></tr>
          <tr><td>Growth source</td><td style="font-size:11px">${a.growth_source}</td></tr>
          <tr><td>WACC</td><td>${a.wacc_pct}%</td></tr>
          <tr><td>Terminal growth</td><td>${a.terminal_growth_pct}%</td></tr>
          <tr><td>Projection years</td><td>${a.projection_years}</td></tr>
        </table>
      </div>
      <div class="panel">
        <h3>Equity Bridge</h3>
        <table>
          <tr><td>Base FCF</td><td>$${fmt(m.base_fcf)}</td></tr>
          <tr><td>Sum of discounted FCFs</td><td>$${fmt(m.discounted_fcfs.reduce((a,b)=>a+b,0))}</td></tr>
          <tr><td>Discounted terminal value</td><td>$${fmt(m.discounted_terminal)}</td></tr>
          <tr><td>Enterprise value</td><td>$${fmt(m.enterprise_value)}</td></tr>
          <tr><td>Net debt</td><td>$${fmt(m.net_debt)}</td></tr>
          <tr><td>Equity value</td><td>$${fmt(m.equity_value)}</td></tr>
          <tr><td>Shares outstanding</td><td>${fmt(m.shares_outstanding)}</td></tr>
        </table>
      </div>
    </div>

    <div class="panel" style="margin-top:20px">
      <h3>FCF Projection</h3>
      <table>
        <tr><th>Year</th>${m.projected_fcfs.map((_,i) => `<th>Y${i+1}</th>`).join("")}</tr>
        <tr><td>Projected FCF</td>${m.projected_fcfs.map(v => `<td>$${fmt(v)}</td>`).join("")}</tr>
        <tr><td>Discounted FCF</td>${m.discounted_fcfs.map(v => `<td>$${fmt(v)}</td>`).join("")}</tr>
      </table>
    </div>

    <div class="panel" style="margin-top:20px">
      <h3>Sensitivity: Intrinsic Value per Share</h3>
      <table class="sens">
        <tr><th>WACC ↓ / TG →</th>${s.tg_axis.map(g => `<th>${g}%</th>`).join("")}</tr>
        ${s.grid.map((row, i) => `
          <tr>
            <td>${s.wacc_axis[i]}%</td>
            ${row.map(v => `<td class="heat" style="background:${heatColor(v)}">${v === null ? "—" : "$" + v.toFixed(2)}</td>`).join("")}
          </tr>
        `).join("")}
      </table>
    </div>
  `;
}

// On page load, if URL has ?t=TICKER, auto-run
(function loadFromURL() {
  const params = new URLSearchParams(location.search);
  const t = params.get("t");
  if (t) {
    document.getElementById("ticker").value = t.toUpperCase();
    if (params.get("wacc")) document.getElementById("wacc").value = (parseFloat(params.get("wacc")) * 100).toFixed(1);
    if (params.get("tg")) document.getElementById("tg").value = (parseFloat(params.get("tg")) * 100).toFixed(2);
    if (params.get("years")) document.getElementById("years").value = params.get("years");
    run();
  }
})();
</script>
</body>
</html>
"""
