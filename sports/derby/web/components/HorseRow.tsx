"use client";

import type { Horse, UserTag } from "../lib/types";
import { driftDirection, driftLabel, formatPercent } from "../lib/odds";
import { OddsBadge } from "./OddsBadge";

interface HorseRowProps {
  horse: Horse;
  tag: UserTag | undefined;
  oddsOverride: string | undefined;
  onOpenTag: () => void;
  onOpenOddsOverride: () => void;
}

const TAG_COLORS: Record<UserTag, string> = {
  single: "#1a4fd0",
  A: "#1f9d55",
  B: "#7a4fd0",
  C: "#a36b00",
  toss: "#5e5e68",
  chaos: "#b53b3b",
  boost: "#0a8c6a",
  fade: "#7a5a00",
};

function TagPill({ tag }: { tag: UserTag | undefined }) {
  if (!tag) {
    return (
      <span
        style={{
          display: "inline-block",
          padding: "2px 8px",
          borderRadius: 999,
          border: "1px dashed var(--border)",
          color: "var(--text-muted)",
          fontSize: "0.75rem",
        }}
      >
        Tag
      </span>
    );
  }
  const color = TAG_COLORS[tag];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 999,
        background: color,
        color: "white",
        fontSize: "0.75rem",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
      }}
    >
      {tag}
    </span>
  );
}

function FlagBadges({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
      {flags.map((f) => (
        <span
          key={f}
          style={{
            display: "inline-block",
            padding: "1px 6px",
            borderRadius: 4,
            background: "var(--surface-alt)",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
            fontSize: "0.7rem",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {f.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

export function HorseRow({
  horse,
  tag,
  oddsOverride,
  onOpenTag,
  onOpenOddsOverride,
}: HorseRowProps) {
  const drift = driftDirection(horse.morningLineOdds, oddsOverride ?? horse.currentOdds);
  const scratched = !!horse.scratched;

  return (
    <div
      role="row"
      style={{
        display: "grid",
        gridTemplateColumns:
          "44px minmax(140px, 1.6fr) minmax(140px, 1.4fr) 80px 80px 80px 90px auto",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        borderTop: "1px solid var(--border)",
        background: scratched ? "var(--surface-alt)" : "var(--surface)",
        opacity: scratched ? 0.55 : 1,
        minHeight: 56,
      }}
    >
      <div
        style={{
          fontWeight: 700,
          fontSize: "1.1rem",
          fontVariantNumeric: "tabular-nums",
          textAlign: "center",
        }}
      >
        {horse.post}
      </div>

      <button
        type="button"
        className="tap-target"
        onClick={onOpenTag}
        aria-label={`Tag ${horse.name}`}
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: 2,
          padding: "6px 8px",
          borderRadius: 8,
          border: "1px solid transparent",
          background: "transparent",
          color: "var(--text)",
          textAlign: "left",
          textDecoration: scratched ? "line-through" : undefined,
        }}
      >
        <span style={{ fontWeight: 600 }}>{horse.name}</span>
        {horse.jockey || horse.trainer ? (
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            {horse.jockey ?? "—"}
            {horse.trainer ? ` · ${horse.trainer}` : ""}
          </span>
        ) : null}
      </button>

      <button
        type="button"
        className="tap-target"
        onClick={onOpenOddsOverride}
        aria-label={`Override odds for ${horse.name}`}
        style={{
          display: "flex",
          alignItems: "center",
          padding: "4px 6px",
          background: "transparent",
          border: "1px solid transparent",
          borderRadius: 8,
        }}
      >
        <OddsBadge
          morningLine={horse.morningLineOdds}
          current={horse.currentOdds}
          override={oddsOverride ?? null}
        />
      </button>

      <div
        style={{
          fontVariantNumeric: "tabular-nums",
          fontSize: "0.85rem",
          color:
            drift === "shorter"
              ? "var(--good)"
              : drift === "longer"
              ? "var(--text-muted)"
              : "var(--text)",
          textAlign: "center",
        }}
      >
        {driftLabel(drift)}
      </div>

      <div
        style={{
          fontVariantNumeric: "tabular-nums",
          fontSize: "0.9rem",
          textAlign: "right",
        }}
      >
        {formatPercent(horse.marketProbability ?? null, 0)}
      </div>

      <div
        style={{
          fontVariantNumeric: "tabular-nums",
          fontSize: "0.95rem",
          fontWeight: 600,
          textAlign: "right",
        }}
      >
        {formatPercent(horse.finalProbability ?? null, 0)}
      </div>

      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <button
          type="button"
          className="tap-target"
          onClick={onOpenTag}
          aria-label={`Change tag for ${horse.name}`}
          style={{
            padding: "4px 6px",
            background: "transparent",
            border: "none",
            borderRadius: 8,
          }}
        >
          <TagPill tag={tag} />
        </button>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <FlagBadges flags={horse.flags} />
      </div>
    </div>
  );
}

export function HorseRowHeader() {
  return (
    <div
      role="row"
      style={{
        display: "grid",
        gridTemplateColumns:
          "44px minmax(140px, 1.6fr) minmax(140px, 1.4fr) 80px 80px 80px 90px auto",
        alignItems: "center",
        gap: 8,
        padding: "6px 12px",
        background: "var(--surface-alt)",
        borderTop: "1px solid var(--border)",
        fontSize: "0.7rem",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        color: "var(--text-muted)",
      }}
    >
      <div style={{ textAlign: "center" }}>Post</div>
      <div>Horse</div>
      <div>ML → Current</div>
      <div style={{ textAlign: "center" }}>Drift</div>
      <div style={{ textAlign: "right" }}>Market %</div>
      <div style={{ textAlign: "right" }}>Final %</div>
      <div>Tag</div>
      <div>Flags</div>
    </div>
  );
}
