"use client";

import type { ComputedBucket, Horse, UserTag } from "../lib/types";
import {
  driftMagnitude,
  formatPercent,
  type DriftMagnitude,
} from "../lib/odds";
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

function ConfidenceDot({ score }: { score: number | null | undefined }) {
  if (score === null || score === undefined || !Number.isFinite(score)) {
    return null;
  }
  const level =
    score >= 0.6 ? "high" : score >= 0.35 ? "medium" : "low";
  const color =
    level === "high"
      ? "var(--good)"
      : level === "medium"
      ? "#e6a817"
      : "var(--bad)";
  const title = `Confidence ${(score * 100).toFixed(0)}% (${level})`;
  return (
    <span
      title={title}
      aria-label={title}
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        marginLeft: 6,
        flexShrink: 0,
        verticalAlign: "middle",
      }}
    />
  );
}

const BUCKET_STYLES: Record<ComputedBucket, { color: string; bg: string }> = {
  CORE: { color: "#1a4fd0", bg: "#e8effe" },
  VALUE: { color: "#1f9d55", bg: "#e6f4ec" },
  CHAOS: { color: "#b53b3b", bg: "#fde2e2" },
  TRAP: { color: "#a36b00", bg: "#fef3e2" },
  DEAD: { color: "#5e5e68", bg: "var(--surface-alt)" },
};

function BucketBadge({ bucket }: { bucket: ComputedBucket | undefined }) {
  if (!bucket) return null;
  // Defensive lookup — if the API ever returns a value outside the
  // ComputedBucket literal (malformed payload, future bug), fall through
  // instead of crashing with a destructure-of-undefined.
  const styles = BUCKET_STYLES[bucket];
  if (!styles) return null;
  const { color, bg } = styles;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 7px",
        borderRadius: 999,
        background: bg,
        border: `1px solid ${color}`,
        color,
        fontSize: "0.65rem",
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        marginTop: 3,
      }}
    >
      {bucket}
    </span>
  );
}

const TREND_STYLES: Record<
  DriftMagnitude,
  { label: string; color: string; title: string }
> = {
  "big-shorter": {
    label: "++",
    color: "var(--good)",
    title: "Steaming hard (≥3 pts shorter)",
  },
  shorter: {
    label: "+",
    color: "var(--good)",
    title: "Shortening",
  },
  flat: {
    label: "~",
    color: "var(--text-muted)",
    title: "Flat",
  },
  longer: {
    label: "-",
    color: "var(--text-muted)",
    title: "Drifting",
  },
  "big-longer": {
    label: "--",
    color: "var(--bad)",
    title: "Drifting hard (≥3 pts longer)",
  },
  unknown: {
    label: "",
    color: "var(--text-muted)",
    title: "",
  },
};

function TrendArrow({ magnitude }: { magnitude: DriftMagnitude }) {
  const { label, color, title } = TREND_STYLES[magnitude];
  if (!label) return <span style={{ color: "var(--text-muted)" }}>—</span>;
  return (
    <span
      title={title}
      aria-label={title}
      style={{
        color,
        fontSize: "0.95rem",
        fontWeight: 700,
        fontVariantNumeric: "tabular-nums",
        letterSpacing: "0.02em",
      }}
    >
      {label}
    </span>
  );
}

function EdgeScore({ score }: { score: number | null | undefined }) {
  if (score === null || score === undefined || !Number.isFinite(score)) {
    return null;
  }
  const pct = score * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  const color =
    pct > 0.05
      ? "var(--good)"
      : pct < -0.05
      ? "var(--bad)"
      : "var(--text-muted)";
  return (
    <span
      style={{
        fontSize: "0.7rem",
        fontWeight: 600,
        color,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {sign}
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

export function HorseRow({
  horse,
  tag,
  oddsOverride,
  onOpenTag,
  onOpenOddsOverride,
}: HorseRowProps) {
  const magnitude = driftMagnitude(
    horse.morningLineOdds,
    oddsOverride ?? horse.currentOdds,
  );
  const scratched = !!horse.scratched;

  return (
    <div
      role="row"
      style={{
        display: "grid",
        gridTemplateColumns:
          "44px minmax(140px, 1.6fr) minmax(140px, 1.4fr) 80px 80px 80px 100px auto",
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
        <span
          style={{
            fontWeight: 600,
            display: "inline-flex",
            alignItems: "center",
          }}
        >
          {horse.name}
          <ConfidenceDot score={horse.confidence_score} />
        </span>
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
          textAlign: "center",
        }}
      >
        <TrendArrow magnitude={magnitude} />
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
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 1,
          fontVariantNumeric: "tabular-nums",
          textAlign: "right",
        }}
      >
        <span style={{ fontSize: "0.95rem", fontWeight: 600 }}>
          {formatPercent(horse.finalProbability ?? null, 0)}
        </span>
        <EdgeScore score={horse.edge_score} />
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: 2,
        }}
      >
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
        <BucketBadge bucket={horse.computedBucket} />
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
          "44px minmax(140px, 1.6fr) minmax(140px, 1.4fr) 80px 80px 80px 100px auto",
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
      <div style={{ textAlign: "center" }}>Trend</div>
      <div style={{ textAlign: "right" }}>Market %</div>
      <div style={{ textAlign: "right" }}>Final % · Edge</div>
      <div>Tag · Bucket</div>
      <div>Flags</div>
    </div>
  );
}
