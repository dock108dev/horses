"use client";

import Link from "next/link";

interface DayHeaderProps {
  day: string;
  lastCardRefresh: string | null;
  lastOddsRefresh: string | null;
  source: string;
  budget: number;
  baseUnit: number;
  busy: { card: boolean; odds: boolean; sim: boolean; tickets: boolean };
  onRefreshCard: () => void;
  onRefreshOdds: () => void;
  onRunSim: () => void;
  onBuildTickets: () => void;
  onBudgetChange: (value: number) => void;
  onBaseUnitChange: (value: number) => void;
}

function fmt(iso: string | null): string {
  if (!iso) return "never";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

const BUTTON: React.CSSProperties = {
  padding: "0.6rem 1rem",
  borderRadius: 10,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  fontWeight: 600,
  whiteSpace: "nowrap",
};

export function DayHeader({
  day,
  lastCardRefresh,
  lastOddsRefresh,
  source,
  budget,
  baseUnit,
  busy,
  onRefreshCard,
  onRefreshOdds,
  onRunSim,
  onBuildTickets,
  onBudgetChange,
  onBaseUnitChange,
}: DayHeaderProps) {
  return (
    <header
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
        padding: "0.75rem 1rem",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 14,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.75rem",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem" }}>
          <Link href="/" className="tap-target" style={{ ...BUTTON, padding: "0.4rem 0.75rem" }}>
            ← Days
          </Link>
          <h1
            style={{
              margin: 0,
              fontSize: "1.4rem",
              textTransform: "capitalize",
            }}
          >
            {day}
          </h1>
        </div>
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            flexWrap: "wrap",
            justifyContent: "flex-end",
          }}
        >
          <button
            type="button"
            className="tap-target"
            onClick={onRefreshCard}
            disabled={busy.card}
            style={{ ...BUTTON, opacity: busy.card ? 0.55 : 1 }}
          >
            {busy.card ? "Refreshing card…" : "Refresh Card"}
          </button>
          <button
            type="button"
            className="tap-target"
            onClick={onRefreshOdds}
            disabled={busy.odds}
            style={{ ...BUTTON, opacity: busy.odds ? 0.55 : 1 }}
          >
            {busy.odds ? "Refreshing odds…" : "Refresh Odds"}
          </button>
          <button
            type="button"
            className="tap-target"
            onClick={onRunSim}
            disabled={busy.sim}
            style={{ ...BUTTON, opacity: busy.sim ? 0.55 : 1 }}
          >
            {busy.sim ? "Running…" : "Run Sim"}
          </button>
          <button
            type="button"
            className="tap-target"
            onClick={onBuildTickets}
            disabled={busy.tickets}
            style={{
              ...BUTTON,
              background: "var(--accent)",
              color: "white",
              borderColor: "var(--accent)",
              opacity: busy.tickets ? 0.55 : 1,
            }}
          >
            {busy.tickets ? "Building…" : "Build Tickets"}
          </button>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.5rem 1.25rem",
          fontSize: "0.85rem",
          color: "var(--text-muted)",
        }}
      >
        <span>
          Last card refresh: <strong style={{ color: "var(--text)" }}>{fmt(lastCardRefresh)}</strong>
        </span>
        <span>
          Last odds refresh: <strong style={{ color: "var(--text)" }}>{fmt(lastOddsRefresh)}</strong>
        </span>
        <span>
          Source: <strong style={{ color: "var(--text)" }}>{source || "—"}</strong>
        </span>
        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            marginLeft: "auto",
          }}
        >
          Budget&nbsp;$
          <input
            type="number"
            min={0}
            step={1}
            value={budget}
            onChange={(e) => onBudgetChange(Number(e.target.value))}
            className="tap-target"
            style={{
              width: 80,
              padding: "4px 8px",
              borderRadius: 8,
              border: "1px solid var(--border)",
              fontVariantNumeric: "tabular-nums",
            }}
          />
        </label>
        <label
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          Base unit&nbsp;$
          <input
            type="number"
            min={0}
            step={0.5}
            value={baseUnit}
            onChange={(e) => onBaseUnitChange(Number(e.target.value))}
            className="tap-target"
            style={{
              width: 80,
              padding: "4px 8px",
              borderRadius: 8,
              border: "1px solid var(--border)",
              fontVariantNumeric: "tabular-nums",
            }}
          />
        </label>
      </div>
    </header>
  );
}
