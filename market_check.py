#!/usr/bin/env python3
"""Check the price of gold and how the US dollar is doing worldwide.

Uses only the Python standard library and free, key-less data sources:

* Gold     - Yahoo Finance COMEX gold futures (GC=F), falling back to gold-api.com spot
* DXY      - Yahoo Finance US Dollar Index (DX-Y.NYB)
* FX rates - Frankfurter (European Central Bank reference rates), falling back
             to open.er-api.com for the latest rates only

Usage:
    python3 market_check.py
    python3 market_check.py --currencies EUR,JPY,GBP,CNY --days 7
    python3 market_check.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

USER_AGENT = "Mozilla/5.0 (market-check script)"
TIMEOUT = 15

DEFAULT_CURRENCIES = [
    "EUR", "JPY", "GBP", "CNY", "CHF", "CAD", "AUD",
    "INR", "MXN", "BRL", "KRW", "ZAR", "TRY", "SEK",
]

TROY_OUNCE_GRAMS = 31.1034768


def fetch_json(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or not old:
        return None
    return (new - old) / old * 100


# --------------------------------------------------------------------------- #
# Data sources
# --------------------------------------------------------------------------- #

def yahoo_quote(symbol: str, days: int) -> dict:
    """Latest price plus daily and period change for a Yahoo Finance symbol."""
    data = fetch_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}",
        {"range": "3mo", "interval": "1d"},
    )
    result = data["chart"]["result"][0]
    meta = result["meta"]
    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    history = [
        (datetime.fromtimestamp(t, timezone.utc).date(), c)
        for t, c in zip(stamps, closes)
        if c is not None
    ]

    price = meta["regularMarketPrice"]
    prev_close = meta.get("chartPreviousClose")
    if len(history) >= 2:
        prev_close = history[-2][1]

    cutoff = date.today() - timedelta(days=days)
    period_base = next((c for d, c in reversed(history) if d <= cutoff), None)

    return {
        "symbol": symbol,
        "price": price,
        "currency": meta.get("currency"),
        "as_of": datetime.fromtimestamp(meta["regularMarketTime"], timezone.utc).isoformat(),
        "change_1d_pct": pct_change(price, prev_close),
        "change_period_pct": pct_change(price, period_base),
    }


def gold_price(days: int) -> dict:
    try:
        quote = yahoo_quote("GC=F", days)
        quote["source"] = "Yahoo Finance (COMEX gold futures, GC=F)"
        return quote
    except Exception as exc:  # fall back to spot price without history
        print(f"warning: Yahoo gold lookup failed ({exc}); trying gold-api.com", file=sys.stderr)
    data = fetch_json("https://api.gold-api.com/price/XAU")
    return {
        "symbol": "XAU",
        "price": data["price"],
        "currency": data.get("currency", "USD"),
        "as_of": data.get("updatedAt"),
        "change_1d_pct": None,
        "change_period_pct": None,
        "source": "gold-api.com (spot)",
    }


def dollar_index(days: int) -> dict | None:
    try:
        quote = yahoo_quote("DX-Y.NYB", days)
        quote["source"] = "Yahoo Finance (ICE US Dollar Index, DX-Y.NYB)"
        return quote
    except Exception as exc:
        print(f"warning: dollar index lookup failed ({exc})", file=sys.stderr)
        return None


def fx_rates(currencies: list[str], days: int) -> dict:
    """USD exchange rates now, one business day ago, and `days` ago."""
    symbols = ",".join(currencies)
    start = (date.today() - timedelta(days=days + 7)).isoformat()
    try:
        data = fetch_json(
            f"https://api.frankfurter.dev/v1/{start}..",
            {"base": "USD", "symbols": symbols},
        )
        series = sorted(data["rates"].items())
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        latest_day, latest = series[-1]
        _, prev = series[-2] if len(series) >= 2 else series[-1]
        _, base = next(((d, r) for d, r in reversed(series) if d <= cutoff), series[0])
        return {
            "source": "Frankfurter (European Central Bank reference rates)",
            "as_of": latest_day,
            "latest": latest,
            "prev": prev,
            "period_base": base,
        }
    except Exception as exc:
        print(f"warning: Frankfurter lookup failed ({exc}); trying open.er-api.com", file=sys.stderr)
    data = fetch_json("https://open.er-api.com/v6/latest/USD")
    latest = {c: data["rates"][c] for c in currencies if c in data["rates"]}
    return {
        "source": "open.er-api.com (latest only, no history)",
        "as_of": data.get("time_last_update_utc"),
        "latest": latest,
        "prev": {},
        "period_base": {},
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def build_report(currencies: list[str], days: int) -> dict:
    gold = gold_price(days)
    dxy = dollar_index(days)
    fx = fx_rates(currencies, days)

    pairs = []
    for cur in currencies:
        rate = fx["latest"].get(cur)
        if rate is None:
            continue
        pairs.append({
            "currency": cur,
            "units_per_usd": rate,
            # Positive = the dollar buys more of this currency (USD stronger).
            "usd_change_1d_pct": pct_change(rate, fx["prev"].get(cur)),
            "usd_change_period_pct": pct_change(rate, fx["period_base"].get(cur)),
            "gold_per_oz": gold["price"] * rate,
        })

    period_moves = [p["usd_change_period_pct"] for p in pairs if p["usd_change_period_pct"] is not None]
    summary = None
    if period_moves:
        summary = {
            "stronger_against": sum(m > 0 for m in period_moves),
            "weaker_against": sum(m < 0 for m in period_moves),
            "average_change_pct": sum(period_moves) / len(period_moves),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period_days": days,
        "gold": gold,
        "gold_per_gram_usd": gold["price"] / TROY_OUNCE_GRAMS,
        "dollar_index": dxy,
        "fx": {"source": fx["source"], "as_of": fx["as_of"], "pairs": pairs},
        "dollar_summary": summary,
    }


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "    n/a"
    arrow = "▲" if value > 0 else "▼" if value < 0 else "•"
    return f"{arrow}{value:+6.2f}%"


def fmt_num(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:,.2f}"
    return f"{value:,.4f}"


def print_report(r: dict) -> None:
    days = r["period_days"]
    gold = r["gold"]
    print(f"Market check — {r['generated_at']}")
    print("=" * 64)

    print("\nGOLD")
    print(f"  Price:      ${gold['price']:,.2f} per troy oz  (${r['gold_per_gram_usd']:,.2f}/gram)")
    print(f"  1 day:      {fmt_pct(gold['change_1d_pct'])}")
    print(f"  {f'{days} days:':<12}{fmt_pct(gold['change_period_pct'])}")
    print(f"  Source:     {gold['source']}, as of {gold['as_of']}")

    print("\nUS DOLLAR INDEX (DXY — USD vs. a basket of 6 major currencies)")
    dxy = r["dollar_index"]
    if dxy:
        print(f"  Level:      {dxy['price']:.3f}")
        print(f"  1 day:      {fmt_pct(dxy['change_1d_pct'])}")
        print(f"  {f'{days} days:':<12}{fmt_pct(dxy['change_period_pct'])}")
    else:
        print("  unavailable")

    fx = r["fx"]
    print("\nUSD AGAINST WORLD CURRENCIES  (▲ = dollar stronger)")
    print(f"  {'Currency':<9}{'per USD':>12}{'1 day':>11}{f'{days} days':>11}{'Gold/oz':>16}")
    print(f"  {'-' * 57}")
    for p in fx["pairs"]:
        print(
            f"  {p['currency']:<9}{fmt_num(p['units_per_usd']):>12}"
            f"{fmt_pct(p['usd_change_1d_pct']):>11}{fmt_pct(p['usd_change_period_pct']):>11}"
            f"{fmt_num(p['gold_per_oz']):>16}"
        )
    print(f"  Source: {fx['source']}, as of {fx['as_of']}")

    s = r["dollar_summary"]
    if s:
        total = s["stronger_against"] + s["weaker_against"]
        avg = s["average_change_pct"]
        if abs(avg) < 0.25:
            trend = "roughly flat / mixed"
        else:
            trend = "strengthening overall" if avg > 0 else "weakening overall"
        print(
            f"\nVERDICT: over the last {days} days the dollar gained against "
            f"{s['stronger_against']} of {total} currencies (avg {s['average_change_pct']:+.2f}%) — "
            f"it is {trend}."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--currencies",
        default=",".join(DEFAULT_CURRENCIES),
        help="comma-separated ISO currency codes to compare the dollar against",
    )
    parser.add_argument("--days", type=int, default=30, help="look-back period for trend (default: 30)")
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of a table")
    args = parser.parse_args()

    currencies = [c.strip().upper() for c in args.currencies.split(",") if c.strip()]
    try:
        report = build_report(currencies, args.days)
    except Exception as exc:
        print(f"error: could not fetch market data: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
