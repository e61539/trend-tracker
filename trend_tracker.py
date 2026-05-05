#!/usr/bin/env python3
"""Observation-only trend opportunity tracker.

Finds shallow pullbacks in symbols with close above SMA20 and SMA20 above SMA50.
This script does not place orders, size trades, or make execution decisions.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_SYMBOLS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA")
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=4mo&interval=1d"


@dataclass(frozen=True)
class DailyBar:
    date: str
    close: float
    high: float


@dataclass(frozen=True)
class TrendResult:
    symbol: str
    close: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    recent_high: float | None = None
    pullback_pct: float | None = None
    trend_strength: float | None = None
    is_above_sma20: bool = False
    is_sma20_above_sma50: bool = False
    is_shallow_pullback: bool = False
    is_trend_pass: bool = False
    pullback_band: str = "unknown"
    reason: str = ""
    is_opportunity: bool = False
    error: str = ""


def finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def fetch_daily_bars(symbol: str, timeout_sec: int = 12) -> list[DailyBar]:
    url = YAHOO_CHART_URL.format(symbol=symbol.upper())
    request = Request(url, headers={"User-Agent": "trend-tracker/1.0"})
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"price fetch failed: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"price fetch failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("price fetch returned invalid JSON") from exc

    chart = payload.get("chart", {})
    errors = chart.get("error")
    if errors:
        description = errors.get("description") if isinstance(errors, dict) else str(errors)
        raise RuntimeError(f"price fetch failed: {description}")

    results = chart.get("result") or []
    if not results:
        raise RuntimeError("price fetch returned no chart data")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    highs = quote.get("high") or []

    bars: list[DailyBar] = []
    for timestamp, close, high in zip(timestamps, closes, highs):
        if not finite_number(close) or not finite_number(high):
            continue
        date = datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d")
        bars.append(DailyBar(date=date, close=float(close), high=float(high)))

    if len(bars) < 50:
        raise RuntimeError(f"not enough daily bars ({len(bars)})")
    return bars


def average(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return float("nan")
    return sum(values) / len(values)


def pullback_band_label(pullback_pct: float, min_pullback_pct: float, max_pullback_pct: float) -> str:
    if not finite_number(pullback_pct):
        return "unknown"
    if pullback_pct < min_pullback_pct:
        return "too small"
    if pullback_pct > max_pullback_pct:
        return "too deep"
    return "valid"


def build_reason(result: TrendResult) -> str:
    if result.error:
        return result.error

    pullback = format_pct(result.pullback_pct)
    if result.is_opportunity:
        return f"uptrend intact, SMA20 is above SMA50, shallow pullback {pullback}."

    reasons = []
    if not result.is_above_sma20:
        reasons.append("below SMA20")
    elif not result.is_sma20_above_sma50:
        reasons.append("SMA20 is not above SMA50")
    else:
        reasons.append("uptrend confirmed")

    if result.is_trend_pass:
        reasons.append("SMA20 is above SMA50")

    if result.pullback_band == "too small":
        reasons.append(f"but pullback only {pullback}, too close to high")
    elif result.pullback_band == "too deep":
        reasons.append(f"pullback {pullback} is too deep")
    elif result.pullback_band == "valid":
        reasons.append(f"pullback {pullback} is valid")

    if not result.is_trend_pass and result.trend_strength is not None and result.trend_strength < 0:
        reasons.append("trend is negative")

    sentence = ", ".join(reasons).strip()
    return sentence[:1].lower() + sentence[1:] + "." if sentence else "conditions not confirmed."


def analyze_symbol(
    symbol: str,
    recent_high_days: int = 20,
    min_pullback_pct: float = 1.0,
    max_pullback_pct: float = 3.0,
) -> TrendResult:
    try:
        bars = fetch_daily_bars(symbol)
    except RuntimeError as exc:
        return TrendResult(symbol=symbol.upper(), error=str(exc))

    closes = [bar.close for bar in bars]
    latest = bars[-1]
    sma20 = average(closes[-20:])
    sma50 = average(closes[-50:])
    recent_window = bars[-recent_high_days:]
    recent_high = max(bar.close for bar in recent_window)

    pullback_pct = ((recent_high - latest.close) / recent_high) * 100.0 if recent_high > 0 else float("nan")
    trend_pct = ((latest.close - sma20) / sma20) * 100.0 if sma20 > 0 else float("nan")

    is_above_sma20 = latest.close > sma20
    is_sma20_above_sma50 = sma20 > sma50
    is_trend_pass = is_above_sma20 and is_sma20_above_sma50
    band = pullback_band_label(pullback_pct, min_pullback_pct, max_pullback_pct)
    is_shallow_pullback = band == "valid"
    result = TrendResult(
        symbol=symbol.upper(),
        close=latest.close,
        sma20=sma20,
        sma50=sma50,
        recent_high=recent_high,
        pullback_pct=pullback_pct,
        trend_strength=trend_pct,
        is_above_sma20=is_above_sma20,
        is_sma20_above_sma50=is_sma20_above_sma50,
        is_shallow_pullback=is_shallow_pullback,
        is_trend_pass=is_trend_pass,
        pullback_band=band,
        is_opportunity=is_trend_pass and is_shallow_pullback,
    )
    return TrendResult(**{**result.__dict__, "reason": build_reason(result)})


def format_pct(value: float | None) -> str:
    if value is None or not finite_number(value):
        return "NA"
    return f"{float(value):.2f}%"


def format_money(value: float | None) -> str:
    if value is None or not finite_number(value):
        return "NA"
    return f"{float(value):.2f}"


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def print_results(results: list[TrendResult]) -> None:
    print("Trend Opportunity Tracker - observation only, no trading logic")
    print()
    print(
        f"{'Symbol':<8} {'Close':>10} {'SMA20':>10} {'SMA50':>10} {'RecentHigh':>10} "
        f"{'Pullback':>10} {'TrendPct':>10} {'Above20':>8} {'20>50':>8} {'Band':<10} "
        f"{'TrendOK':>8} {'Status':<10}"
    )
    print("-" * 125)
    for result in results:
        if result.error:
            print(
                f"{result.symbol:<8} {'NA':>10} {'NA':>10} {'NA':>10} {'NA':>10} "
                f"{'NA':>10} {'NA':>10} {'no':>8} {'no':>8} {'unknown':<10} {'no':>8} ERROR"
            )
            print(f"  {result.symbol} ERROR: {result.error}")
            print()
            continue
        status = "WATCH" if result.is_opportunity else "NO MATCH"
        print(
            f"{result.symbol:<8} "
            f"{format_money(result.close):>10} "
            f"{format_money(result.sma20):>10} "
            f"{format_money(result.sma50):>10} "
            f"{format_money(result.recent_high):>10} "
            f"{format_pct(result.pullback_pct):>10} "
            f"{format_pct(result.trend_strength):>10} "
            f"{yes_no(result.is_above_sma20):>8} "
            f"{yes_no(result.is_sma20_above_sma50):>8} "
            f"{result.pullback_band:<10} "
            f"{yes_no(result.is_trend_pass):>8} "
            f"{status:<10}"
        )
        print(f"  {result.symbol} {status}: {result.reason}")
        print()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find shallow pullbacks in strong uptrends.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=list(DEFAULT_SYMBOLS),
        help="Symbols to check. Default: SPY QQQ AAPL MSFT NVDA",
    )
    parser.add_argument(
        "--recent-high-days",
        type=int,
        default=20,
        help="Lookback window for recent high. Default: 20",
    )
    parser.add_argument(
        "--min-pullback-pct",
        type=float,
        default=1.0,
        help="Minimum pullback percent for WATCH. Default: 1.0",
    )
    parser.add_argument(
        "--max-pullback-pct",
        type=float,
        default=3.0,
        help="Maximum pullback percent for WATCH. Default: 3.0",
    )
    parser.add_argument(
        "--min-trend-pct",
        type=float,
        default=5.0,
        help="Accepted for compatibility; trend pass is Close>SMA20 and SMA20>SMA50.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    recent_high_days = max(5, int(args.recent_high_days))
    min_pullback_pct = max(0.0, float(args.min_pullback_pct))
    max_pullback_pct = max(min_pullback_pct, float(args.max_pullback_pct))
    symbols = [str(symbol).upper().strip() for symbol in args.symbols if str(symbol).strip()]
    if not symbols:
        print("No symbols supplied.", file=sys.stderr)
        return 2

    results = [
        analyze_symbol(
            symbol,
            recent_high_days=recent_high_days,
            min_pullback_pct=min_pullback_pct,
            max_pullback_pct=max_pullback_pct,
        )
        for symbol in symbols
    ]
    print_results(results)
    return 1 if all(result.error for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
