"use client";

import type {
  RaceClassification,
  Race,
  SequenceRole,
  UserTag,
} from "../lib/types";
import { HorseRow, HorseRowHeader } from "./HorseRow";

const LEG_LABELS: Record<SequenceRole, string> = {
  "pick5-leg-1": "Leg 1",
  "pick5-leg-2": "Leg 2",
  "pick5-leg-3": "Leg 3",
  "pick5-leg-4": "Leg 4",
  "pick5-leg-5": "Leg 5",
};

const STRATEGY_STYLES: Record<string, { bg: string; color: string }> = {
  SINGLE: { bg: "#1a4fd0", color: "white" },
  "2-DEEP": { bg: "#7a4fd0", color: "white" },
  MID: { bg: "#1f9d55", color: "white" },
  "CHAOS SPREAD": { bg: "#a36b00", color: "white" },
  "MAX CHAOS": { bg: "#b53b3b", color: "white" },
};

const CLASSIFICATION_STYLES: Record<
  RaceClassification,
  { color: string; border: string }
> = {
  KEY: { color: "#1a4fd0", border: "#1a4fd0" },
  TIGHT: { color: "#7a4fd0", border: "#7a4fd0" },
  MID: { color: "#1f9d55", border: "#1f9d55" },
  CHAOS: { color: "#b53b3b", border: "#b53b3b" },
};

function StrategyBadge({
  strategy,
  classification,
}: {
  strategy: string | undefined;
  classification: RaceClassification | undefined;
}) {
  if (!strategy && !classification) return null;
  const stratStyle = strategy
    ? STRATEGY_STYLES[strategy] ?? {
        bg: "var(--surface-alt)",
        color: "var(--text)",
      }
    : null;
  const classStyle = classification
    ? CLASSIFICATION_STYLES[classification]
    : null;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 999,
        overflow: "hidden",
        fontSize: "0.7rem",
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
      }}
    >
      {stratStyle ? (
        <span
          style={{
            padding: "2px 9px",
            background: stratStyle.bg,
            color: stratStyle.color,
          }}
        >
          {strategy}
        </span>
      ) : null}
      {classStyle ? (
        <span
          style={{
            padding: "2px 8px",
            background: "var(--surface)",
            color: classStyle.color,
            border: `1px solid ${classStyle.border}`,
            borderLeft: stratStyle ? "none" : undefined,
          }}
        >
          {classification}
        </span>
      ) : null}
    </span>
  );
}

interface RaceCardProps {
  race: Race;
  tagsByHorseId: Record<string, UserTag>;
  oddsOverridesByHorseId: Record<string, string>;
  onOpenTag: (horseId: string) => void;
  onOpenOddsOverride: (horseId: string) => void;
}

export function RaceCard({
  race,
  tagsByHorseId,
  oddsOverridesByHorseId,
  onOpenTag,
  onOpenOddsOverride,
}: RaceCardProps) {
  const legLabel = race.sequenceRole ? LEG_LABELS[race.sequenceRole] : "";

  return (
    <section
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 14,
        overflow: "hidden",
        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.75rem",
          padding: "0.75rem 1rem",
          background: "var(--surface-alt)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem" }}>
          <span
            style={{
              fontSize: "0.7rem",
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--accent)",
            }}
          >
            {legLabel}
          </span>
          <span style={{ fontSize: "1.1rem", fontWeight: 700 }}>
            Race {race.raceNumber}
          </span>
          {race.name ? (
            <span style={{ color: "var(--text)", fontWeight: 500 }}>
              {race.name}
            </span>
          ) : null}
        </div>
        <div
          style={{
            display: "flex",
            gap: "0.75rem",
            alignItems: "center",
            flexWrap: "wrap",
            color: "var(--text-muted)",
            fontSize: "0.85rem",
          }}
        >
          {race.surface ? <span>{race.surface}</span> : null}
          {race.distance ? <span>{race.distance}</span> : null}
          {race.postTime ? (
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              Post {race.postTime}
            </span>
          ) : null}
          <StrategyBadge
            strategy={race.strategy}
            classification={race.classification}
          />
        </div>
      </header>

      <HorseRowHeader />
      {race.horses.map((h) => (
        <HorseRow
          key={h.id}
          horse={h}
          tag={tagsByHorseId[h.id]}
          oddsOverride={oddsOverridesByHorseId[h.id]}
          onOpenTag={() => onOpenTag(h.id)}
          onOpenOddsOverride={() => onOpenOddsOverride(h.id)}
        />
      ))}
    </section>
  );
}
