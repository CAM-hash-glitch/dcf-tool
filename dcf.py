"""
DCF valuation engine — production version.

Adds a simple in-memory TTL cache so we don't hammer Yahoo on repeat lookups.
Yahoo will rate-limit aggressively when this is public; cache is essential.
"""

import time
import yfinance as yf
import numpy as np
import pandas as pd
from threading import Lock


OCF_LABELS = [
    "Operating Cash Flow",
    "Total Cash From Operating Activities",
    "Cash Flow From Continuing Operating Activities",
]
CAPEX_LABELS = [
    "Capital Expenditure",
    "Capital Expenditures",
    "Purchase Of PPE",
]
REVENUE_LABELS = [
    "Total Revenue",
    "Revenue",
    "Operating Revenue",
]


# Thread-safe TTL cache. Keyed by (ticker, wacc, tg, years).
_CACHE: dict = {}
_CACHE_LOCK = Lock()
CACHE_TTL_SECONDS = 60 * 60  # 1 hour
CACHE_MAX_ENTRIES = 1000


def _cache_get(key):
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        return value


def _cache_set(key, value):
    with _CACHE_LOCK:
        if len(_CACHE) >= CACHE_MAX_ENTRIES:
            oldest_key = min(_CACHE, key=lambda k: _CACHE[k][0])
            _CACHE.pop(oldest_key, None)
        _CACHE[key] = (time.time(), value)


def cache_stats():
    with _CACHE_LOCK:
        return {"entries": len(_CACHE), "max": CACHE_MAX_ENTRIES, "ttl_seconds": CACHE_TTL_SECONDS}


def _first_available(df: pd.DataFrame, labels: list[str]):
    if df is None or df.empty:
        return None
    for label in labels:
        if label in df.index:
            return df.loc[label]
    return None


def _historical_cagr(revenue_series: pd.Series) -> float | None:
    if revenue_series is None:
        return None
    clean = revenue_series.dropna()
    if len(clean) < 2:
        return None
    newest, oldest = clean.iloc[0], clean.iloc[-1]
    n_years = len(clean) - 1
    if oldest <= 0 or newest <= 0:
        return None
    cagr = (newest / oldest) ** (1 / n_years) - 1
    return float(np.clip(cagr, -0.10, 0.25))


def get_intrinsic_value(
    ticker: str,
    wacc: float = 0.09,
    terminal_growth: float = 0.025,
    years: int = 5,
):
    ticker = ticker.upper().strip()
    cache_key = (ticker, round(wacc, 4), round(terminal_growth, 4), years)
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "_cached": True}

    try:
        stock = yf.Ticker(ticker)
        cashflow = stock.cashflow
        financials = stock.financials
        info = stock.info
    except Exception:
        return {"error": f"Could not fetch data for {ticker}. Yahoo may be rate-limiting."}

    ocf_row = _first_available(cashflow, OCF_LABELS)
    capex_row = _first_available(cashflow, CAPEX_LABELS)
    if ocf_row is None or capex_row is None:
        return {"error": f"Missing cash flow data for {ticker} on Yahoo."}

    try:
        ocf = float(ocf_row.iloc[0])
        capex = float(capex_row.iloc[0])
    except Exception:
        return {"error": "Could not parse cash flow values."}

    base_fcf = ocf + capex
    if base_fcf <= 0:
        return {
            "error": f"{ticker} has non-positive base FCF ({base_fcf:,.0f}). "
                     "DCF isn't meaningful for this company."
        }

    revenue_row = _first_available(financials, REVENUE_LABELS)
    growth_rate = _historical_cagr(revenue_row)
    growth_source = "historical revenue CAGR"
    if growth_rate is None:
        growth_rate = 0.05
        growth_source = "fallback (no usable revenue history)"

    projected_fcfs = []
    fcf = base_fcf
    for _ in range(years):
        fcf = fcf * (1 + growth_rate)
        projected_fcfs.append(fcf)

    discounted_fcfs = [
        cf / ((1 + wacc) ** (i + 1)) for i, cf in enumerate(projected_fcfs)
    ]

    if wacc <= terminal_growth:
        return {"error": "WACC must exceed terminal growth."}

    terminal_value = (projected_fcfs[-1] * (1 + terminal_growth)) / (wacc - terminal_growth)
    discounted_terminal = terminal_value / ((1 + wacc) ** years)

    enterprise_value = sum(discounted_fcfs) + discounted_terminal

    total_debt = info.get("totalDebt") or 0
    total_cash = info.get("totalCash") or 0
    net_debt = total_debt - total_cash
    equity_value = enterprise_value - net_debt

    shares = info.get("sharesOutstanding")
    if not shares:
        return {"error": f"Missing shares outstanding for {ticker}."}

    intrinsic_per_share = equity_value / shares
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    margin_of_safety = None
    if current_price:
        margin_of_safety = (intrinsic_per_share - current_price) / current_price

    wacc_grid = [wacc - 0.02, wacc - 0.01, wacc, wacc + 0.01, wacc + 0.02]
    tg_grid = [terminal_growth - 0.01, terminal_growth - 0.005,
               terminal_growth, terminal_growth + 0.005, terminal_growth + 0.01]
    sensitivity = []
    for w in wacc_grid:
        row = []
        for g in tg_grid:
            if w <= g:
                row.append(None)
                continue
            proj = [base_fcf * (1 + growth_rate) ** (i + 1) for i in range(years)]
            disc = sum(cf / ((1 + w) ** (i + 1)) for i, cf in enumerate(proj))
            tv = (proj[-1] * (1 + g)) / (w - g)
            disc_tv = tv / ((1 + w) ** years)
            ev = disc + disc_tv
            eqv = ev - net_debt
            row.append(round(eqv / shares, 2))
        sensitivity.append(row)

    result = {
        "ticker": ticker,
        "company": info.get("longName") or info.get("shortName") or ticker,
        "current_price": round(current_price, 2) if current_price else None,
        "intrinsic_value_per_share": round(intrinsic_per_share, 2),
        "margin_of_safety_pct": round(margin_of_safety * 100, 1) if margin_of_safety is not None else None,
        "assumptions": {
            "growth_rate_pct": round(growth_rate * 100, 2),
            "growth_source": growth_source,
            "wacc_pct": round(wacc * 100, 2),
            "terminal_growth_pct": round(terminal_growth * 100, 2),
            "projection_years": years,
        },
        "model": {
            "base_fcf": round(base_fcf, 0),
            "projected_fcfs": [round(x, 0) for x in projected_fcfs],
            "discounted_fcfs": [round(x, 0) for x in discounted_fcfs],
            "terminal_value": round(terminal_value, 0),
            "discounted_terminal": round(discounted_terminal, 0),
            "enterprise_value": round(enterprise_value, 0),
            "net_debt": round(net_debt, 0),
            "equity_value": round(equity_value, 0),
            "shares_outstanding": int(shares),
        },
        "sensitivity": {
            "wacc_axis": [round(w * 100, 2) for w in wacc_grid],
            "tg_axis": [round(g * 100, 2) for g in tg_grid],
            "grid": sensitivity,
        },
        "_cached": False,
    }

    _cache_set(cache_key, result)
    return result
