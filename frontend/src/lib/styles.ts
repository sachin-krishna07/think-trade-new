/**
 * Trading-style metadata — single source of truth for the UI.
 *
 * Must stay in sync with backend/config.py (SCALPING / SWING / VWAPFADE and
 * style_cfg()). The backend caps capital_pct for vwapfade at
 * VWAPFADE_MAX_CAPITAL_PCT, so `maxCapitalPct` here mirrors that; the UI warns
 * rather than silently letting the user set a value the backend will override.
 */
export type StyleId = "scalping" | "swing" | "vwapfade";

export interface StyleMeta {
  id: StyleId;
  label: string;
  blurb: string;
  /** vwapfade is a standalone rule, not the 7-layer scored signal */
  scored: boolean;
  /** backend clamps capital_pct to this when set */
  maxCapitalPct?: number;
  /** shown when the style needs a heads-up before starting */
  caution?: string;
}

export const STYLES: Record<StyleId, StyleMeta> = {
  scalping: {
    id: "scalping",
    label: "Scalping",
    blurb: "2–8 min holds · 15m trend · 5m entry · 7-layer signal",
    scored: true,
  },
  swing: {
    id: "swing",
    label: "Swing",
    blurb: "Hours–days · 4h trend · 1h entry · 7-layer signal",
    scored: true,
  },
  vwapfade: {
    id: "vwapfade",
    label: "VWAP Fade",
    blurb:
      "Mean reversion · fades 0.8% VWAP stretch + RSI(5) extreme · trades AGAINST the move",
    scored: false,
    maxCapitalPct: 6,
    caution:
      "~6.5h median hold (not scalping). Wide 4.5×ATR stop — backend caps capital at 6% per trade.",
  },
};

export const STYLE_IDS: StyleId[] = ["scalping", "swing", "vwapfade"];

export function styleMeta(id: string): StyleMeta {
  return STYLES[id as StyleId] ?? STYLES.scalping;
}

export function isScored(id: string): boolean {
  return styleMeta(id).scored;
}
