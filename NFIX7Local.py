"""Local overlay on NostalgiaForInfinityX7.

Lives in its own file so upstream merges never touch it: the auto-updater merges
upstream/main into prod every 6h, and anything we add to NFI's own files would
either conflict (halting updates) or be overwritten. Selected via
FREQTRADE__STRATEGY=NFIX7Local -- and .env is not in git either.

Both behaviours are OFF by default, so deploying this file alone changes nothing.

  NFI_MAX_ENTRY_ADJ   int, default -1 (unlimited, = stock NFI)
      Caps how many times the grind may ADD to a position. freqtrade enforces
      this itself in FreqtradeBot, so it works regardless of NFI internals.
      Live evidence: STG took 85 entry adds, RIF 194.

  NFI_NO_GRIND_STOP   "1" to disable the per-chunk stop (default off)
      NFI stops out an individual grind chunk at grind_N_stop_grinds_spot =
      -0.06 and de-risks via derisk_*. Those are the only legs that sell BELOW
      the chunk's entry -- i.e. the only ones that realise a loss. Disabling
      them means a chunk closes only in profit, or not at all: the loss becomes
      inventory rather than realised P&L. Pair it with NFI_MAX_ENTRY_ADJ, which
      then stops being a loss-cutter and becomes an exposure ceiling.

  NFI_GRIND_TP        float, overrides grind_N_profit_threshold_spot (0.018)
      Lower = more, smaller round trips. 0.010 left materially less inventory
      stranded than 0.018 in simulation.

  NFI_MIN_GRIND_EXIT  float or "" (default "", disabled)
      Refuses a grind SELL that would realise a loss, i.e. when the trade is
      below this profit ratio. NFI closes a trade only in profit, but its grind
      partial-exits sell below the average entry all the time -- that is where
      the loss actually accrues. Over Sep 18-19 on STG the grind bought $103.39
      at avg 0.14707 and sold $103.86 at avg 0.14116: sells 4.0% below buys.
      Set e.g. 0.0 to allow only break-even-or-better grind exits.

      Trade-off: some of those sells are genuine de-risking, so vetoing them
      means riding a fast drop at full size. Backtest before enabling.
"""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from NostalgiaForInfinityX7 import NostalgiaForInfinityX7

log = logging.getLogger(__name__)


def _env_float(name):
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else None


class NFIX7Local(NostalgiaForInfinityX7):
    max_entry_position_adjustment = int(os.environ.get("NFI_MAX_ENTRY_ADJ", "-1"))
    min_grind_exit_profit = _env_float("NFI_MIN_GRIND_EXIT")

    # Widen every per-chunk stop far enough that it can never fire, and turn off
    # the derisk legs, so no grind chunk is ever sold below its own entry.
    if os.environ.get("NFI_NO_GRIND_STOP") == "1":
        derisk_enable = False
        for _lvl in range(1, 7):
            for _mkt in ("spot", "futures"):
                if hasattr(NostalgiaForInfinityX7, f"grind_{_lvl}_stop_grinds_{_mkt}"):
                    locals()[f"grind_{_lvl}_stop_grinds_{_mkt}"] = -10.0

    if _env_float("NFI_GRIND_TP") is not None:
        _tp = _env_float("NFI_GRIND_TP")
        for _lvl in range(1, 7):
            for _mkt in ("spot", "futures"):
                if hasattr(NostalgiaForInfinityX7, f"grind_{_lvl}_profit_threshold_{_mkt}"):
                    locals()[f"grind_{_lvl}_profit_threshold_{_mkt}"] = _tp

    def version(self):
        base = super().version()
        return f"{base}-local(adj={self.max_entry_position_adjustment}," \
               f"grind_exit={self.min_grind_exit_profit})"

    def adjust_trade_position(self, trade, current_time, current_rate, current_profit,
                              min_stake, max_stake, current_entry_rate, current_exit_rate,
                              current_entry_profit, current_exit_profit, **kwargs):
        res = super().adjust_trade_position(
            trade, current_time, current_rate, current_profit, min_stake, max_stake,
            current_entry_rate, current_exit_rate, current_entry_profit,
            current_exit_profit, **kwargs)
        if self.min_grind_exit_profit is None or res is None:
            return res
        # NFI returns a bare stake, or (stake, tag); negative stake == a partial SELL.
        stake = res[0] if isinstance(res, tuple) else res
        if stake is None or stake >= 0:
            return res
        if current_profit < self.min_grind_exit_profit:
            log.debug("vetoed grind exit on %s at profit %.4f (< %.4f)",
                      trade.pair, current_profit, self.min_grind_exit_profit)
            return None
        return res
