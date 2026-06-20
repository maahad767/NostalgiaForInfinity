# NFI X7 — Data-Driven Per-Pair Falling-Knife Entry Filter

> **SUPERSEDED (2026-06-19)** by `2026-06-19-nfi-grind-derisk-recovery-retune-design.md`.
> Phase-1 calibration showed entry velocity does not separate knives from good dips (blocking 75% of
> knives costs 40% of good entries), and the real pain is slot-lockup, not entries. Kept for the findings.

- **Date:** 2026-06-18
- **Strategy:** `NostalgiaForInfinityX7.py` (live: Binance spot, ~$200, 6 slots)
- **Status:** Design — awaiting user review before planning

## Problem

Two observed pathologies in live trading:

1. **Stuck trades:** positions open for months, ~−10–12% total, with 50+ entries/exits.
2. **Falling knives:** an entry fires during a crash and the pair drops another 10–20% in the fall.

These pull in opposite directions on NFI's central tradeoff. Problem 1 is NFI's
**grind-and-recover** design working as intended — `stoploss = -0.99` (effectively off),
grinding adds small stakes to average down, and full derisk only triggers very deep
(`regular_mode_derisk_spot = -0.24`). Problem 2 is **entry timing** — signals fire into a
crash, then grinding deepens the hole.

## Decisions (from brainstorming)

- **Direction: "enter better, keep grinding."** Leave the grind/derisk/exit machinery 100%
  untouched. Fix only the *entry* side.
- **Knife type: per-pair velocity.** Detect when *this coin* is dropping too fast and block
  the entry. (Not a market-wide/BTC guard — that was considered and deferred.)
- **Validation: analyze real trades first.** Set the threshold from actual trade data, not a
  guess. Then A/B backtest before shipping.
- **Filter form: test all three candidate forms in Phase 1, pick the best separator.**

## Goals

- Reduce the count and depth of deep-loss trades (the "knife" entries) and the resulting
  months-long underwater grinds.
- Do so with **minimal damage** to NFI's dip-buying edge (it profits by buying oversold dips,
  so it buys into drops by design — this is a tradeoff we must quantify, not ignore).
- Reversible: gated behind a toggle, default off, A/B-testable.

## Non-Goals (out of scope for this cycle)

- No changes to grinding, derisk, DCA, exits, or stoploss.
- No hard stoploss or time-based exit (the "cut losses faster" path was explicitly *not* chosen).
- No market-wide/BTC crash guard (a possible later layer; not now).
- Futures path not targeted (user is spot-only); calibrate on spot.

## Deferred to a future cycle (captured so it is not lost)

- **"NFI doesn't catch/ride gainers well."** Separate problem (entry breadth on uptrends +
  exiting winners too early). Its own brainstorm → spec → plan cycle. Noted here only so it
  is not forgotten.

## Architecture

A single new entry gate, calibrated from data, injected into the one place all long entries
already funnel through.

- **Injection point:** `df["protections_long_global"]` (defined ~line 5248). Every one of the
  30+ long entry conditions appends `protections_long_global == True`, so adding one ANDed
  clause here applies the filter everywhere without touching individual signals.
- **Toggle + params (new class attributes):**
  - `entry_knife_filter_enable = False` (default off — must be explicitly enabled)
  - threshold constants chosen in Phase 1 (e.g. `entry_knife_drop_pct`, `entry_knife_lookback`)
- **Reuse only existing indicators** — no new math. Available per-pair velocity features
  already computed by NFI: `change_pct`, `change_pct_15m/1h/4h/1d`, `roc_9_15m/1h/4h/1d`,
  `close_max_6/12/48`, `close_min_6/12/48`, `change_pct_min_3/6`, `change_pct_max_3/6`.

## Phase 1 — Measure (calibrate the threshold from real trades)

**Data source:** local NFI X7 backtest exports (richest: `backtest-result-2026-04-28_15-38-30.zip`,
178 trades). Trades carry `min_rate`/`max_rate`, so worst drawdown is computable directly.
The live VPS DB is the truest source and can be pulled later to confirm; backtest is the
faithful proxy we can run now. **If the existing trade set is too thin or too bull-biased to
contain enough knives, re-run an NFI X7 backtest over a crash-heavy window** (`--export trades`)
to get a rich knife sample before calibrating.

**Method:**
1. Load closed trades. For each, compute **Maximum Adverse Excursion**:
   `mae = min_rate / open_rate − 1`.
2. Classify:
   - **knife** — `mae ≤ −0.10` (price fell ≥10% below first entry at some point).
   - **stuck** — `trade_duration` very long (e.g. > 30 days) **and** `profit_ratio < 0`.
   - **good dip** — `profit_ratio > 0` (recovered to profit despite a dip).
3. At each trade's **entry timestamp**, compute the three candidate velocity features **using
   NFI's exact indicator definitions** (read from the populate-indicators code so thresholds
   transfer 1:1 into the live filter):
   - **Form A — drop-from-recent-high:** `close / close_max_N` for N ∈ {6, 12, 48} (5m/15m).
   - **Form B — momentum:** `change_pct_15m`, `roc_9_15m`, `change_pct` (5m).
   - **Form C — multi-TF confirmed:** Form-A/B fast drop AND 1h/4h `roc_9` negative.
4. For each form, sweep the threshold and measure **separation**: % of knives blocked vs
   % of good dips lost. Report a table per form (threshold → knives blocked / good dips lost /
   net trades affected).
5. **Pick the form + threshold with the best separation.** If no threshold cleanly separates
   knives from good dips (heavy overlap in velocity space), report that honestly — it means a
   per-pair velocity filter cannot help much, and we stop before shipping a net-negative change.

**Deliverable:** a short written analysis (the separation tables + chosen form/threshold, or a
"no clean separation" finding).

## Phase 2 — Build the filter

Only if Phase 1 finds a usable threshold.

- Add `entry_knife_filter_enable` + threshold constants as class attributes.
- Add one ANDed clause to `df["protections_long_global"]` implementing the chosen form, e.g.
  (Form A shape): pass only when `close ≥ close_max_N × (1 − drop_pct)` — i.e. block entry when
  the pair is already `drop_pct` below its N-candle high. Guard the whole clause so that when
  the toggle is off the column is byte-for-byte unchanged (no behavior change when disabled).
- Keep it spot-focused; mirror to futures only if trivial and free.

## Phase 3 — Validate (A/B backtest; ship only if it wins)

- Run the **same** backtest with the filter **OFF vs ON** over the calibration window, and
  ideally also a second crash-heavy window.
- Compare: **max drawdown**, **count + depth of deep-loss trades**, **total return**, win rate,
  trade count, avg duration.
- **Ship criterion:** drawdown and/or deep-loss-trade count drop materially **without gutting
  total return**. Quantify the upside given up. If it's net-negative, do not ship — keep the
  toggle off and record the finding.

## Risks & caveats

- **Edge erosion:** NFI's profit comes from buying oversold dips; an over-aggressive knife
  filter removes good dip-buys too. Phase 1 (separation check) and Phase 3 (A/B) exist
  specifically to bound this.
- **Backtest vs live drift:** thresholds calibrated on backtest may differ slightly live;
  mitigated by using identical indicator definitions and confirming against the live DB later.
- **Sample size:** 178 trades may be too few for robust separation; re-run over a longer/
  crash-heavy window if needed.
- **Look-ahead safety:** all features use only data available at the entry candle (no future
  bars); the filter clause uses the same last-candle values NFI already uses.

## Success criteria

1. Phase 1 produces a clear verdict: either a calibrated (form, threshold) with a quantified
   knives-blocked / good-dips-lost tradeoff, or a documented "no clean separation."
2. If shipped: A/B backtest shows lower drawdown / fewer deep-loss trades without gutting
   return, behind a default-off toggle that leaves behavior unchanged when disabled.
