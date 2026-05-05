# Trend Opportunity Tracker

A simple local CLI that identifies shallow pullbacks in symbols that remain in an uptrend.

This is observation-only. It has no trading logic, no order placement, no account integration, and no position sizing.

## What It Checks

- Symbols: `SPY`, `QQQ`, `AAPL`, `MSFT`, `NVDA` by default.
- Price is above the 20-day moving average.
- Current close is 1-3% below the recent high.
- Trend strength is a simple score:

```text
% above 20-day moving average + 20-day moving average slope %
```

## Run

```powershell
cd C:\Users\cheng_hamn078\trend-tracker
python .\trend_tracker.py
```

Custom symbols:

```powershell
python .\trend_tracker.py --symbols SPY QQQ MSFT
```

Custom recent-high lookback:

```powershell
python .\trend_tracker.py --recent-high-days 30
```

## Output

```text
Symbol        Close      SMA20   Pullback      Trend Status
SPY          600.00     590.00      1.80%      3.20% WATCH
```

`WATCH` means the symbol is above its 20-day moving average and has a 1-3% pullback from its recent high.
