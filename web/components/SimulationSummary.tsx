"use client";

import type { SimulationResult } from "../lib/types";
import { money, num, pct } from "../lib/format";
import { Spinner } from "./Spinner";

interface SimulationSummaryProps {
  result: SimulationResult | null;
  loading: boolean;
  error: string | null;
  /** Optional human label per ticket id (e.g. "Balanced", "Safer", "Upside"). */
  labels?: Record<string, string>;
}

const CARD: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 14,
  padding: "0.85rem 1rem",
  display: "flex",
  flexDirection: "column",
  gap: "0.5rem",
  minWidth: 180,
};

function defaultLabel(ticketId: string): string {
  if (ticketId === "balanced") return "Balanced";
  if (ticketId === "safer") return "Safer";
  if (ticketId === "upside") return "Upside";
  return ticketId;
}

export function SimulationSummary({
  result,
  loading,
  error,
  labels,
}: SimulationSummaryProps) {
  return (
    <section
      aria-label="Simulation summary"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 14,
        padding: "0.85rem 1rem",
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: "0.75rem",
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ margin: 0, fontSize: "1.05rem" }}>Simulation Summary</h2>
        {result ? (
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            {result.n_iterations.toLocaleString()} iterations
          </span>
        ) : null}
      </div>

      {loading ? (
        <div
          role="status"
          aria-live="polite"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            color: "var(--text-muted)",
            fontSize: "0.9rem",
          }}
        >
          <Spinner /> Running simulation…
        </div>
      ) : null}

      {!loading && error ? (
        <div
          role="alert"
          style={{
            background: "#fde2e2",
            color: "#7a1f1f",
            border: "1px solid #f1a3a3",
            borderRadius: 10,
            padding: "0.6rem 0.9rem",
          }}
        >
          <strong>Simulation failed</strong>
          <div style={{ fontSize: "0.85rem", marginTop: 4 }}>{error}</div>
        </div>
      ) : null}

      {!loading && !error && !result ? (
        <div style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Tap <strong>Run Sim</strong> to estimate Pick 5 hit rates for the
          current tickets.
        </div>
      ) : null}

      {!loading && result && result.tickets.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          No eligible Pick 5 selections — tag horses or refresh the card.
        </div>
      ) : null}

      {!loading && result && result.tickets.length > 0 ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: "0.75rem",
          }}
        >
          {result.tickets.map((t) => (
            <article
              key={t.ticket_id}
              aria-label={`Ticket ${t.ticket_id}`}
              style={CARD}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                }}
              >
                <span style={{ fontWeight: 700 }}>
                  {labels?.[t.ticket_id] ?? defaultLabel(t.ticket_id)}
                </span>
                <span
                  style={{
                    fontSize: "0.8rem",
                    color: "var(--text-muted)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {money(t.cost)}
                </span>
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: "0.4rem",
                }}
              >
                <span
                  style={{
                    fontSize: "1.4rem",
                    fontWeight: 700,
                    fontVariantNumeric: "tabular-nums",
                    color: "var(--accent)",
                  }}
                >
                  {pct(t.estimated_hit_rate_pct, 2)}
                </span>
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                  hit rate
                </span>
              </div>
              <dl
                style={{
                  margin: 0,
                  display: "grid",
                  gridTemplateColumns: "auto 1fr",
                  rowGap: 2,
                  columnGap: "0.5rem",
                  fontSize: "0.8rem",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {t.payout_score !== undefined ? (
                  <>
                    <dt style={{ color: "var(--text-muted)" }}>Payout score</dt>
                    <dd style={{ margin: 0, textAlign: "right" }}>
                      {num(t.payout_score, 2)}
                    </dd>
                  </>
                ) : null}
                {t.confidence !== undefined ? (
                  <>
                    <dt style={{ color: "var(--text-muted)" }}>Confidence</dt>
                    <dd style={{ margin: 0, textAlign: "right" }}>
                      {num(t.confidence, 2)}
                    </dd>
                  </>
                ) : null}
                <dt style={{ color: "var(--text-muted)" }}>Chalkiness</dt>
                <dd style={{ margin: 0, textAlign: "right" }}>
                  {pct(t.chalkiness_pct, 1)}
                </dd>
                <dt style={{ color: "var(--text-muted)" }}>Chaos cover</dt>
                <dd style={{ margin: 0, textAlign: "right" }}>
                  {pct(t.chaos_coverage_pct, 1)}
                </dd>
                <dt style={{ color: "var(--text-muted)" }}>Separator cover</dt>
                <dd style={{ margin: 0, textAlign: "right" }}>
                  {pct(t.separator_coverage_pct, 1)}
                </dd>
              </dl>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
