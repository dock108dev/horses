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

export function driftLabel(d: DriftDirection): string {
  switch (d) {
    case "shorter":
      return "↓ shorter";
    case "longer":
      return "↑ longer";
    case "flat":
      return "—";
    default:
      return "";
  }
}

export function formatPercent(p: number | null | undefined, digits = 0): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "—";
  return `${(p * 100).toFixed(digits)}%`;
}
