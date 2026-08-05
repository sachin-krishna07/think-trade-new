/**
 * Trading-style metadata — single source of truth for the UI.
 *
 * Must stay in sync with backend/config.py (SCALPING / SWING and style_cfg()).
 */
export type StyleId = "scalping" | "swing";

export interface StyleMeta {
  id: StyleId;
  label: string;
  blurb: string;
  scored: boolean;
  /** backend clamps capital_pct to this when set */
  maxCapitalPct?: number;
  /** shown when the style needs a heads-up before starting */
  caution?: string;
  /** one-line exit-rule summary — must mirror this style's block in config.py */
  exitSummary: string;
}

export const STYLES: Record<StyleId, StyleMeta> = {
  scalping: {
    id: "scalping",
    label: "Scalping",
    blurb: "2–8 min holds · 15m trend · 5m entry · 7-layer signal",
    scored: true,
    // config.py SCALPING: atr_sl_mult 1.35, sl_entry_r 1.0, tp_entry_r 2.5,
    // trail_trigger_r 1.1, trail_gap_r 0.4
    exitSummary: "SL: ATR×1.35×1.0R · Hard cap +2.5R · Trailing arms at +1.1R (0.4R gap)",
  },
  swing: {
    id: "swing",
    label: "Swing",
    blurb: "Hours–days · 4h trend · 1h entry · 7-layer signal",
    scored: true,
    // config.py SWING has no sl_entry_r/tp_entry_r/trailing keys — the engine's
    // cfg.get(..., 1.0) fallback makes this a plain ATR×3.0 stop/target, no trail.
    exitSummary: "SL: ATR×3.0×1.0R · Fixed TP +1.0R · No trailing",
  },
};

export const STYLE_IDS: StyleId[] = ["scalping", "swing"];

export function styleMeta(id: string): StyleMeta {
  return STYLES[id as StyleId] ?? STYLES.scalping;
}

export function isScored(id: string): boolean {
  return styleMeta(id).scored;
}
