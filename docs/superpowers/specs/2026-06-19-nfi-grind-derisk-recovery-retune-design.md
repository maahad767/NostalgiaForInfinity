# NFI X7 — Grind/De-risk Recovery Retune (config-only, A/B-tested)

- **Date:** 2026-06-19
- **Strategy:** `NostalgiaForInfinityX7.py` (live: Binance spot, ~$200, 6 slots, `grinding_v2` system)
- **Status:** Design — approved inline; awaiting spec review before planning
- **Supersedes:** `2026-06-18-nfi-falling-knife-entry-filter-design.md` (entry-filter approach — tested and
  found weak; see "Why we pivoted")

## Problem (re-characterized from real data)

Original complaint: "trades stuck open for months, ~−10–12%, 50 entries/exits; catches falling knives that
drop another 10–20%." Pulling the **live trade DB** (read-only snapshot, 60 trades) reframed this precisely:

- **Closed trades realize ~0% losses** (avg +1.57%, loss rate 0%, avg duration 0.6 d). NFI grinds every
  position back to breakeven+; it almost never takes a hard loss.
- **The real cost is slot-lockup, not P&L.** 6 deep-grind trades (≥10 DCA entries, ≤−8% MAE) consumed
  **~85 slot-days** — on 6 slots over ~5 weeks that is **~37% of total capital capacity** — to net roughly
  breakeven. 4 were still open at snapshot time (DODO locked 27 d, NFP 18 d, OP 15 d, STG 5 d).
- **The mechanism:** NFI's `grinding_v2` runs two opposing engines on one position —
  - **Grinding** buys dips and sells the chunk at +2% → **lowers** the average (good).
  - **De-risking** sells 20%/30%/50% chunks at −6/−8/−10% drawdown → **raises** the average (bad).
  They fight. On **NFP**, grinding won: price fell −40% but the average dropped −22% (0.01212→0.00948).
  On **DODO**, de-risking won: it dumped cheap units near the lows (sold 50% at 0.01682 at the bottom),
  pushing the average **up** 0.02019→0.02328 (**+15% higher breakeven**) → 27 days locked and counting.

So the de-risk meant to protect is the very thing slowing recovery and locking the slot.

## Why we pivoted (away from the entry filter)

The per-pair velocity entry filter was calibrated against real knives and **failed the separation test**:
at entry, knives and good dips look nearly identical (median "drop below 1h high": knives +9.0% vs good
+7.7%; median 1h ROC: −7.6% vs −5.8%). Best velocity threshold blocks 75% of knives but **skips 40% of all
good entries** — gutting NFI's dip-buying edge. NFI buys into drops *by design*, so entry velocity is a weak
predictor of which dip becomes a knife. Conclusion: don't filter entries; **make the grind/recovery
machinery recover faster** instead — which attacks the measured pain (slot-lockup) directly.

## Decisions

- Keep entries unchanged. Improve **recovery** via two reinforcing levers: **tame de-risk drag** +
  **stronger grinding**. Both protect/lower the average so positions recover to a *real* profit faster and
  free the slot sooner. (User explicitly chose recovery over early "good-enough" breakeven exits.)
- **Config-only** implementation. No `.py` edits, no commits (repo syncs to the live VPS).
- Validate by **A/B backtest** before any live change.

## Goals

- Reduce average trade duration / slot-days and the count of trades stuck >5 days.
- Lower the average faster on underwater positions (recover to exit sooner).
- Preserve NFI's "no hard loss" behavior: no material increase in realized −24% "doom" exits.

## Non-Goals (this cycle)

- No entry-side changes (filter shelved — see deferred).
- No early breakeven/"good-enough" full exit (user declined that lever).
- No forced slot-cap / time-stop that realizes losses.
- Futures untargeted (user is spot); tune `*_spot` params only.

## Architecture

NFI exposes a config override system (`NostalgiaForInfinityX7.py:1006-1030`): a config `nfi_parameters`
block with `nfi_advanced_mode: true` runs `setattr(self, param, value)` for **any** class attribute. The
target `grinding_v2_*` params are not in `NFI_SAFE_PARAMETERS`, so `nfi_advanced_mode: true` is required.

- **Baseline config:** current live config (no `nfi_parameters`).
- **Tuned config:** same + an `nfi_parameters` block overriding the params below.
- A/B = run both, compare. Rollback = remove the block.

### Lever A — tame de-risk drag
| param | current | proposed (start) |
|---|---|---|
| `grinding_v2_derisk_level_1_stake_spot` | 0.20 | 0.10 |
| `grinding_v2_derisk_level_2_stake_spot` | 0.30 | 0.15 |
| `grinding_v2_derisk_level_3_stake_spot` | 0.50 | 0.25 |

Smaller de-risk chunks keep more low-cost units → average stops being pushed up. Trigger thresholds
(`grinding_v2_derisk_level_*_spot`) left as-is initially; deepening them is a Phase-1 variant.

### Lever B — stronger grinding
| param | current | proposed (start) |
|---|---|---|
| `grinding_v2_grind_1_stakes_spot` | [0.20,0.22,0.24,0.26,0.28] | [0.25,0.30,0.35,0.40,0.45] |

Bigger grind adds when underwater → average drops faster (the NFP success, amplified).

**Unchanged backstops (tail safety):** `regular_mode_derisk_spot = −0.24`, `stop_threshold_doom_spot = 0.20`.

## Phase 0 — Verify which params actually execute

Before tuning, confirm the live spot regular-mode path reads exactly these `grinding_v2_*` attributes
(multiple `grind_1_stakes` variants exist: base / `regular_mode_` / `grinding_v2_` / `system_v3_`). Method:
run one short backtest with the tuned config and confirm via logs that the overridden values are applied and
that grind/de-risk order sizes change as expected. If a different variant is consumed, retarget the override.

## Phase 1 — Sweep & A/B backtest

- Variants: **baseline**, **mild** (de-risk 0.15/0.20/0.35; grind +25%), **proposed** (above),
  **aggressive** (de-risk 0.08/0.10/0.15; grind +75%).
- Windows: (a) full **2025-01-01 → 2026-03-01** (most grind trades), (b) **crash window
  2025-10-01 → 2026-03-01** (tail-risk stress — taming de-risk is riskiest here).
- Per-trade metrics from backtest exports (`min_rate`, `trade_duration`, `orders`, `exit_reason`):
  avg/median duration, # trades stuck >5 d, max position MAE, peak average-cost inflation, total return,
  max account drawdown, **count of doom/stoploss realized exits**.
- Reuse analysis tooling in `/tmp` (snapshot at `/tmp/nfi_live_snapshot.db`; recent candles in
  `/tmp/recent/binance`; local feather to 2026-05-29 for ~490 pairs).

## Phase 0 + Phase 1 RESULTS (2026-06-19)

**Phase 0 correction (critical):** active path is NOT `grinding_v2`. `system_name_use = system_v3_2_name`
(line 558) → every trade routes to `long_grind_adjust_trade_position_v3`, reading
`system_v3_2_derisk_level_{1,2,3}_stake_spot` (de-risk) and `system_v3_grind_1_stakes_spot` (grind).
`grinding_v2_*` overrides were a verified byte-identical no-op. Targets corrected.

**Data:** backtests under-produce deep grinds; validated by replaying live pairs over their real period.
Filled the Oct-2025→Mar-2026 gap for the 37 live pairs from `data-api.binance.vision`, overlaid into
`user_data/data` (gitignored, supersets, backups in `/tmp/userdata_backup*`). 35/37 now have crash coverage.

**A/B over Oct 2025 → Jun 2026, 37 live pairs (159 trades, crash + June grinds):**

| metric | baseline | mild | proposed | aggressive |
|---|---|---|---|---|
| return % | 4.10 | 4.13 | 4.14 | 4.15 |
| worst MAE % | −54.9 | −45.4 | −45.4 | −45.4 |
| total orders | 481 | 459 | 450 | 433 |
| stuck >5d | 5 | 5 | 5 | 5 |
| deep grinders (>10 ord) | 5 | 5 | 5 | 5 |
| doom/realized-loss exits | 0 | 0 | 0 | 0 |

**Verdict:** the tune is **safe** (zero extra losses even at aggressive, through the crash) and **helps the
`system_v3_2` deep grinders specifically** — e.g. SAHARA (tag 42): baseline `76 orders / −54.9% / +0.02%`
→ proposed `45 / −43.4% / +0.37%` → aggressive `28 / −37.6% / +0.80%`. The aggregate looks muted only
because 4 of the 5 deep grinders in this window were **grind-mode (tag 120)** trades, which use a *different*
path the override doesn't touch. The user's live deep grinders (DODO=45, NFP=103, STG=61, DEXE=42, EPIC,
SAHARA) are all `system_v3_2` → genuinely helped (≈halved order churn, shallower drawdown, better exits,
faster recovery). **Ship `proposed` as the balanced default** (most of the benefit, lower tail risk than
aggressive). **Known gap:** grind-mode (tag 120) deep grinders (some ZEC/INJ) are unaffected — a follow-up
should tune the regular grind path (`grind_*`/`regular_mode_derisk_*`) for those.

## Phase 1b — Grind-mode (tag-120) extension RESULTS (2026-06-20)

Closed the known gap. Grind-mode (tag 120) routes to `long_grind_adjust_trade_position`, reading
`grind_1..6_stakes_spot`, `grind_1..6_stop_grinds_spot` (per-grind stop, the drag analog),
`grind_1..6_sub_thresholds_spot`, and `regular_mode_derisk_spot` (backstop). Tuned: grind stakes up
~+30%, `stop_grinds` −0.06→−0.10. A/B (baseline / v3_2-only / **combined**) over Oct2025→Jun2026:

| metric | baseline | v3_2-only | combined |
|---|---|---|---|
| return % | 4.10 | 4.14 | 4.16 |
| avg duration (d) | 1.55 | 1.54 | **1.28 (−17%)** |
| worst MAE % | −54.9 | −45.4 | −43.4 |
| total orders | 481 | 450 | 440 |
| doom exits | 0 | 0 | 0 |
| max DD % | 0.08 | 0.08 | 0.10 |

Per tag-120 deep grinder (combined vs baseline): INJ 23o/−45%/94.7d → 17o/−35%/80.1d; ZEC 18o/−45%/13.6d
→ 15o/−22%/**7.4d**; INJ 20o/−22%/62.8d → 17o/−4%/44.2d. **The combined tune is the first to cut aggregate
duration (−17%)** — the actual slot-lockup win — with better return, lower drawdown, and still **zero extra
realized losses** through the crash. Cost: +0.02pp account DD, slightly more per-grind exposure (deeper
stop). **Recommended deliverable = combined** (`configs/nfi-recovery-tune.json`); v3_2-only keys remain the
conservative subset.

## Phase 2 — Ship (config delivery)

If a variant wins: deliver the `nfi_parameters` block for the user to add to their live config and redeploy
(user's action — repo/VPS untouched by us). Recommend a paper/dry-run confirmation first, then live.

**Ship criterion:** lower avg duration and fewer >5-day-stuck trades, at **equal-or-better** total return and
max drawdown, with **no material increase** in realized −24% doom exits in the crash window. Otherwise keep
baseline and report the finding.

## Risks & caveats

- **Increased exposure:** both levers hold/add more into a falling coin. A coin that never recovers rides to
  the −24% cut with a bigger bag → potentially more/realized-larger doom losses. The crash-window A/B exists
  to measure exactly this; ship only if it doesn't worsen materially.
- **Backtest under-produces deep grinds:** the live knife/grind rate (~choppy alts) exceeds what backtests
  generate, so backtest effect sizes may understate live impact. Mitigate by also dry-run confirming live.
- **Param-path risk:** overriding an attribute the active path doesn't read would silently no-op — Phase 0
  guards against this.

## Deferred (recorded so not lost)

- **Per-pair entry knife filter** — shelved (weak separation). A *narrow* extreme-only variant
  (block entries >~15% below 1h-6 high) catches ~38% of the worst knives at <10% good-entry cost; revisit
  only if recovery retune underdelivers.
- **"NFI doesn't ride gainers well"** — separate future cycle (entry breadth on uptrends / exits too early).
- **Slot-liberation exit** ("cut losses faster") — user declined; revisit only if recovery retune fails.

## Success criteria

1. Phase 0 confirms the override reaches the active grind/de-risk path.
2. Phase 1 yields a clear A/B verdict per variant on the metrics above.
3. If shipped: a config-only `nfi_parameters` block, reversible, that measurably shortens recovery/slot-lockup
   without worsening tail (doom) losses.
