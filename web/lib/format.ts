// Display-layer formatters shared by SimulationSummary and TicketBuilder.
// pct/num degrade NaN/Infinity/null to "—" so a single bad payload field
// can't crash a render pass. `digits` is required at every call site so
// no caller silently inherits a different default than another.

export function pct(
  value: number | null | undefined,
  digits: number,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return `${value.toFixed(digits)}%`;
}

export function num(
  value: number | null | undefined,
  digits: number,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(digits);
}

export function money(value: number): string {
  return `$${value.toFixed(2)}`;
}
