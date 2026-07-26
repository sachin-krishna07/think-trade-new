"""Adaptive per-pair entry filter — learns from the bot's own closed trades.

Keeps a rolling window of the last K *net* R-multiples per pair. If a pair's
recent mean is negative it stops taking new entries there, and re-tests it with
a single probe trade every ADAPTIVE_PROBE_SECS so a pair can recover.

Probes are deliberately RARE (7d default). Each one is a real trade on a pair
the filter already flagged as losing, so frequent probing measurably reverses
the filter's benefit — see the numbers in config.py. Expect the bot to trade
noticeably less over time; for a net-negative strategy that is the filter
working, not failing.

Causal by construction: only results of trades that have actually CLOSED are
ever recorded, so a decision can never see its own outcome or any future one.

Net R (after fees) is used, not the gross r_multiple — fees are ~0.16R per
trade here, so gross would systematically overstate every pair.
"""
import time
import logging
from collections import deque, defaultdict
from typing import Dict, Optional, Tuple

from config import (ADAPTIVE_ENABLED, ADAPTIVE_K, ADAPTIVE_MIN_SAMPLES,
                    ADAPTIVE_PROBE_SECS)

log = logging.getLogger("thinktrade.adaptive")


class AdaptiveFilter:
    def __init__(self, k: int = ADAPTIVE_K,
                 min_samples: int = ADAPTIVE_MIN_SAMPLES,
                 probe_secs: int = ADAPTIVE_PROBE_SECS,
                 enabled: bool = ADAPTIVE_ENABLED):
        self.k           = k
        self.min_samples = min_samples
        self.probe_secs  = probe_secs
        self.enabled     = enabled
        self._hist: Dict[str, deque]  = defaultdict(lambda: deque(maxlen=self.k))
        self._last_probe: Dict[str, float] = {}
        self._blocked_since: Dict[str, float] = {}

    # ─── learning ────────────────────────────────────────────
    def record(self, pair: str, net_r: Optional[float]) -> None:
        """Feed one CLOSED trade's net R-multiple."""
        if net_r is None:
            return
        try:
            self._hist[pair].append(float(net_r))
        except (TypeError, ValueError):
            return
        m = self.mean(pair)
        log.info(f"{pair}: adaptive record netR={net_r:+.3f} "
                 f"-> window={len(self._hist[pair])}/{self.k} mean={m:+.3f}")

    def warm_start(self, rows) -> int:
        """Rebuild state from DB rows (oldest first) so a restart keeps learning.

        Each row needs `pair` plus either `net_pnl`+`risk_amount`, or an
        already-computed net R under `net_r`.
        """
        n = 0
        for row in rows:
            pair = row.get("pair")
            if not pair:
                continue
            net_r = row.get("net_r")
            if net_r is None:
                risk = row.get("risk_amount")
                net  = row.get("net_pnl")
                if net is None or not risk:
                    continue
                try:
                    net_r = float(net) / float(risk)
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
            self._hist[pair].append(float(net_r))
            n += 1
        if n:
            log.info(f"Adaptive filter warm-started from {n} closed trades "
                     f"across {len(self._hist)} pairs")
        return n

    # ─── decision ────────────────────────────────────────────
    def mean(self, pair: str) -> Optional[float]:
        dq = self._hist.get(pair)
        if not dq:
            return None
        return sum(dq) / len(dq)

    def allows(self, pair: str) -> Tuple[bool, str]:
        """(allowed, reason). Reason is for logging/UI only."""
        if not self.enabled:
            return True, "adaptive disabled"
        dq = self._hist.get(pair)
        n  = len(dq) if dq else 0
        if n < self.min_samples:
            return True, f"learning ({n}/{self.min_samples})"
        m = sum(dq) / n
        if m > 0:
            self._blocked_since.pop(pair, None)
            return True, f"mean {m:+.3f}R over {n}"
        now = time.time()
        self._blocked_since.setdefault(pair, now)
        # Probe timer runs from when the pair was blocked, not from epoch 0 —
        # defaulting to 0.0 would make the very first check look overdue and
        # hand out a free probe, cancelling the block entirely.
        last = self._last_probe.get(pair, self._blocked_since[pair])
        if now - last >= self.probe_secs:
            self._last_probe[pair] = now
            log.info(f"{pair}: adaptive PROBE trade (mean {m:+.3f}R over {n}) "
                     f"— re-testing a blocked pair")
            return True, f"probe (mean {m:+.3f}R)"
        wait_m = int((self.probe_secs - (now - last)) / 60)
        return False, f"blocked: mean {m:+.3f}R over {n}, next probe in {wait_m}m"

    # ─── introspection ───────────────────────────────────────
    def _peek(self, pair: str) -> Tuple[bool, str]:
        """Same verdict as allows() but WITHOUT consuming a probe slot.
        snapshot() must use this — calling allows() would burn the probe."""
        if not self.enabled:
            return True, "adaptive disabled"
        dq = self._hist.get(pair)
        n  = len(dq) if dq else 0
        if n < self.min_samples:
            return True, f"learning ({n}/{self.min_samples})"
        m = sum(dq) / n
        if m > 0:
            return True, f"mean {m:+.3f}R over {n}"
        now = time.time()
        baseline = self._last_probe.get(pair)
        if baseline is None:
            baseline = self._blocked_since.get(pair, now)
        waited = now - baseline
        if waited >= self.probe_secs:
            return True, f"probe due (mean {m:+.3f}R)"
        return False, (f"blocked: mean {m:+.3f}R over {n}, "
                       f"next probe in {int((self.probe_secs - waited)/60)}m")

    def snapshot(self) -> Dict:
        """State for the API / dashboard."""
        pairs = {}
        for pair, dq in self._hist.items():
            if not dq:
                continue
            n = len(dq)
            m = sum(dq) / n
            allowed, reason = self._peek(pair)
            pairs[pair] = {
                "samples":  n,
                "mean_r":   round(m, 4),
                "wins":     sum(1 for x in dq if x > 0),
                "allowed":  allowed,
                "reason":   reason,
                "blocked_since": self._blocked_since.get(pair),
            }
        return {
            "enabled":     self.enabled,
            "k":           self.k,
            "min_samples": self.min_samples,
            "probe_secs":  self.probe_secs,
            "pairs":       pairs,
            "blocked":     sorted(p for p, v in pairs.items() if not v["allowed"]),
        }
