"use client";

import type { Race, SequenceRole, UserTag } from "../lib/types";
import { HorseRow, HorseRowHeader } from "./HorseRow";

const LEG_LABELS: Record<SequenceRole, string> = {
  "pick5-leg-1": "Leg 1",
  "pick5-leg-2": "Leg 2",
  "pick5-leg-3": "Leg 3",
  "pick5-leg-4": "Leg 4",
  "pick5-leg-5": "Leg 5",
};

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
