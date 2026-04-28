// Helpers for parsing fractional odds strings ("5/2", "8-1", "EVEN") into
// implied probabilities. Mirrors the behavior of api/normalize.py just enough
// to colour the UI consistently with the backend.

export function parseFractional(odds: string | null | undefined): number | null {
  if (!odds) return null;
  const s = odds.trim().toUpperCase();
  if (!s) return null;
  if (s === "EVEN" || s === "EVS") return 1.0;
  const m = s.match(/^(\d+(?:\.\d+)?)\s*[\/\-]\s*(\d+(?:\.\d+)?)$/);
  if (m) {
    const num = parseFloat(m[1]);
    const den = parseFloat(m[2]);
    if (den <= 0) return null;
    return num / den;
  }
  const f = parseFloat(s);
  return Number.isFinite(f) && f > 0 ? f : null;
}

export function impliedProbability(odds: string | null | undefined): number | null {
  const f = parseFractional(odds);
  if (f === null) return null;
  return 1 / (f + 1);
}

export type DriftDirection = "shorter" | "longer" | "flat" | "unknown";

// "Shorter" odds = higher implied probability = more money on the horse.
export function driftDirection(
  ml: string | null | undefined,
  current: string | null | undefined,
): DriftDirection {
  const a = impliedProbability(ml);
  const b = impliedProbability(current);
  if (a === null || b === null) return "unknown";
  const delta = b - a;
  if (delta > 0.005) return "shorter";
  if (delta < -0.005) return "longer";
  return "flat";
}

export type DriftMagnitude =
  | "big-shorter"
  | "shorter"
  | "flat"
  | "longer"
  | "big-longer"
  | "unknown";

// Bucket the decimal-odds delta into five trend tiers. "Big" thresholds at
// ±3.0 fractional points match the magnitude bands documented in the
// frontend-edge-ui-layout research.
export function driftMagnitude(
  ml: string | null | undefined,
  current: string | null | undefined,
): DriftMagnitude {
  const a = parseFractional(ml);
  const b = parseFractional(current);
  if (a === null || b === null) return "unknown";
  const delta = b - a;
  if (Math.abs(delta) < 0.5) return "flat";
  if (delta <= -3.0) return "big-shorter";
  if (delta < 0) return "shorter";
  if (delta >= 3.0) return "big-longer";
  return "longer";
}

export function formatPercent(p: number | null | undefined, digits = 0): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "—";
  return `${(p * 100).toFixed(digits)}%`;
}
