# Formulas

Plain-English reference for every calculation. Code lives in `pipeline/indicators.py`
(per-stock), `pipeline/sectors.py` (sector roll-up), and `pipeline/rotation.py` (RRG).

## Per-stock indicators (`indicators.py`)

| Field | Formula | Meaning |
|-------|---------|---------|
| `change_pct` | `(close / prev_close − 1) × 100` | Today's move |
| `ema10/20/50/200` | Exponential moving averages | Smoothed price at 4 horizons |
| `ema50_slope` | `ema50.pct_change(slope_window)` | Regime axis: is the trend rising/falling/flat |
| `atr` | Wilder 14-period true range (EWM, α=1/14) | Typical daily move (volatility) |
| `atr_pct` | `atr / close × 100` | Volatility as % of price |
| `ext` | `((close / ema50) − 1) / (atr / close)` | Extension above/below EMA50 in ATR units |
| `rsi` | Wilder 14-period RSI | Momentum oscillator (>70 hot, <30 cold) |
| `rvol` | `volume / 20-day avg volume` | Is volume above normal? |
| `rvol_avg` | rolling mean of `rvol` over `rvol_window` | Smoothed RVOL → drives `Vol_Confirmed` |
| `ytd` | `(close / first_close_of_year − 1) × 100` | Return since Jan 1 |
| `weekly` | `(close / close_5d_ago − 1) × 100` | 5-day return |
| `monthly` | `(close / close_21d_ago − 1) × 100` | 21-day return |

## Stage classification (`classify_stages`)

Two axes, both tunable in `config.ini [stage_thresholds]`:

- **Regime** from `ema50_slope` and price vs `ema200`:
  `1` basing · `2` advancing · `3` topping · `4` declining.
- **Phase** (A/B/C) from EMA stair-step alignment + RSI + extension:
  - `2A` loose uptrend (EMA10>EMA20, EMA10>EMA50) + RSI ≥ floor
  - `2B` full stack (EMA10>EMA20>EMA50) + healthy RSI
  - `2C` full stack + extreme RSI + over-extended
  - `4A/4B/4C` are the mirror for downtrends; `1B`/`3B` are rotation pre-signals.
- `Vol_Confirmed` = `round(rvol_avg, 2) ≥ rvol_confirm` (high-conviction volume tag).

A ticker with insufficient history (NaN EMA200/slope) is `New`.

## Sector roll-up (`sectors.py`)

- `sqrt_mcap = sqrt(Market_Cap)` — weighting factor that tempers mega-cap dominance.
- Sector `Daily/Weekly/Monthly/YTD/Avg_RSI/Avg_RVOL` = sqrt-mcap-weighted mean of members.
- `Breadth_Pct` = `% of members whose Stage is in breadth_stages` (default 2A,2B).
- `AD` = advances/declines count; `Top3` = top 3 weekly contributors (weighted).

## Rotation / RRG (`rotation.py`)

- **Cohesion**: each ticker's correlation with its sector's median daily return over
  `cohesion_window` days; low-cohesion outliers get down-weighted (soft ramp).
- **Sector return**: cohesion × sqrt(mcap)-weighted mean of member log-returns
  (trimmed mean for small sectors).
- **RS** (relative strength) = cumulative (sector − equal-weight benchmark), optionally EMA-smoothed.
- **X** (position) = `RS_now − RS[−window_position]`; **Y** (momentum) =
  `(RS_now − RS[−window_momentum]) / window_momentum`. Both z-score normalized across sectors.
- **Quadrant**: STRONG (x≥0,y≥0) · WARMING (x<0,y>0) · WEAK (x<0,y≤0) · COOLING (x≥0,y<0).
