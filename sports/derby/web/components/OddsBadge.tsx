"use client";

import { driftDirection } from "../lib/odds";

interface OddsBadgeProps {
  morningLine?: string | null;
  current?: string | null;
  override?: string | null;
}

// Side-by-side ML and current odds. Background is green when the market is
// taking money on the horse (current odds shorter than ML), grey when the
// horse is drifting out, and white when there's no movement to compare.
export function OddsBadge({ morningLine, current, override }: OddsBadgeProps) {
  const liveOdds = override ?? current;
  const direction = driftDirection(morningLine, liveOdds);

  let background = "var(--surface)";
  let border = "1px solid var(--border)";
  if (direction === "shorter") {
    background = "var(--good-bg)";
    border = "1px solid #9bdcaf";
  } else if (direction === "longer") {
    background = "var(--surface-alt)";
    border = "1px solid var(--border)";
  }

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 8px",
        borderRadius: 8,
        background,
        border,
        fontVariantNumeric: "tabular-nums",
        whiteSpace: "nowrap",
      }}
      aria-label={`Morning line ${morningLine ?? "—"}, current ${liveOdds ?? "—"}`}
    >
      <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
        {morningLine ?? "—"}
      </span>
      <span aria-hidden="true" style={{ color: "var(--text-muted)" }}>
        →
      </span>
      <span style={{ fontWeight: 600 }}>{liveOdds ?? "—"}</span>
      {override !== null && override !== undefined && override !== current ? (
        <span
          title="Manual override"
          style={{
            fontSize: "0.7rem",
            color: "var(--accent)",
            border: "1px solid var(--accent)",
            borderRadius: 4,
            padding: "0 4px",
          }}
        >
          OVR
        </span>
      ) : null}
    </span>
  );
}
