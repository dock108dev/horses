"use client";

// LOC note: ~553 LOC, over the 500-line guideline. The budget-tab,
// keep/drop disposition, and per-leg breakdown all read the same
// `legs`/`horsesById`/`dispositions` props; splitting BudgetPanel /
// TicketCard into separate files would just shuffle the imports without
// changing the data flow. See docs/audits/cleanup-report.md
// "Files still >500 LOC".
import { useEffect, useMemo, useState } from "react";

import type {
  BudgetVariant,
  BuiltTicket,
  Horse,
  Race,
  TicketSimulationResult,
} from "../lib/types";
import { money, num, pct } from "../lib/format";
import { Spinner } from "./Spinner";

interface TicketBuilderProps {
  variants: BudgetVariant[];
  loading: boolean;
  error: string | null;
  /** Pick 5 races in leg order; used to label the leg breakdown. */
  legs: Race[];
  /** Optional sim results for hit-rate annotations, keyed by ticket id. */
  simResultsById?: Record<string, TicketSimulationResult>;
}

const TAB_BUTTON: React.CSSProperties = {
  padding: "0.5rem 0.9rem",
  borderRadius: 999,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  fontWeight: 600,
  whiteSpace: "nowrap",
};

const KEEP_DROP_BUTTON: React.CSSProperties = {
  padding: "0.3rem 0.7rem",
  borderRadius: 999,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  fontSize: "0.78rem",
  fontWeight: 600,
};

function ticketLabel(ticket: BuiltTicket): string {
  if (ticket.label) return ticket.label;
  if (ticket.id === "balanced") return "Balanced";
  if (ticket.id === "safer") return "Safer";
  if (ticket.id === "upside") return "Upside";
  return ticket.id;
}

type Disposition = "keep" | "drop" | undefined;

function makeKey(budget: number, ticketId: string): string {
  return `${budget}::${ticketId}`;
}

export function TicketBuilder({
  variants,
  loading,
  error,
  legs,
  simResultsById,
}: TicketBuilderProps) {
  const [activeBudget, setActiveBudget] = useState<number | null>(null);
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({});

  const horsesById = useMemo<Record<string, Horse>>(() => {
    const map: Record<string, Horse> = {};
    for (const race of legs) {
      for (const horse of race.horses) {
        map[horse.id] = horse;
      }
    }
    return map;
  }, [legs]);

  // Keep the active tab in sync as variants change. Default to first; reset
  // when the previously active budget is no longer present.
  useEffect(() => {
    if (variants.length === 0) {
      setActiveBudget(null);
      return;
    }
    const present = variants.some((v) => v.budget_dollars === activeBudget);
    if (!present) setActiveBudget(variants[0].budget_dollars);
  }, [variants, activeBudget]);

  function setDisposition(budget: number, ticketId: string, value: Disposition) {
    setDispositions((prev) => {
      const next = { ...prev };
      const k = makeKey(budget, ticketId);
      if (value === undefined) delete next[k];
      else next[k] = value;
      return next;
    });
  }

  const activeVariant =
    activeBudget !== null
      ? variants.find((v) => v.budget_dollars === activeBudget) ?? null
      : null;

  return (
    <section
      aria-label="Ticket builder"
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
        <h2 style={{ margin: 0, fontSize: "1.05rem" }}>Tickets</h2>
        {variants.length > 0 ? (
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            {variants.length} budget {variants.length === 1 ? "variant" : "variants"}
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
          <Spinner /> Building tickets…
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
          <strong>Ticket build failed</strong>
          <div style={{ fontSize: "0.85rem", marginTop: 4 }}>{error}</div>
        </div>
      ) : null}

      {!loading && !error && variants.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Tap <strong>Build Tickets</strong> to generate Balanced, Safer, and
          Upside tickets per budget.
        </div>
      ) : null}

      {!loading && variants.length > 0 ? (
        <>
          <div
            role="tablist"
            aria-label="Budget"
            style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}
          >
            {variants.map((v) => {
              const active = v.budget_dollars === activeBudget;
              return (
                <button
                  key={v.budget_dollars}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className="tap-target"
                  onClick={() => setActiveBudget(v.budget_dollars)}
                  style={{
                    ...TAB_BUTTON,
                    background: active ? "var(--accent)" : "var(--surface)",
                    color: active ? "white" : "var(--text)",
                    borderColor: active ? "var(--accent)" : "var(--border)",
                  }}
                >
                  {money(v.budget_dollars)}
                  <span
                    style={{
                      marginLeft: 6,
                      fontSize: "0.7rem",
                      opacity: 0.8,
                      fontWeight: 500,
                    }}
                  >
                    {v.tickets.length}
                  </span>
                </button>
              );
            })}
          </div>

          {activeVariant ? (
            <BudgetPanel
              variant={activeVariant}
              legs={legs}
              horsesById={horsesById}
              simResultsById={simResultsById}
              dispositions={dispositions}
              onSetDisposition={setDisposition}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}

interface BudgetPanelProps {
  variant: BudgetVariant;
  legs: Race[];
  horsesById: Record<string, Horse>;
  simResultsById?: Record<string, TicketSimulationResult>;
  dispositions: Record<string, Disposition>;
  onSetDisposition: (budget: number, ticketId: string, value: Disposition) => void;
}

function BudgetPanel({
  variant,
  legs,
  horsesById,
  simResultsById,
  dispositions,
  onSetDisposition,
}: BudgetPanelProps) {
  if (variant.tickets.length === 0) {
    return (
      <div
        role="tabpanel"
        style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}
      >
        No tickets fit this budget. Try a higher budget or smaller base unit.
      </div>
    );
  }
  return (
    <div
      role="tabpanel"
      style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}
    >
      {variant.tickets.map((t) => (
        <TicketCard
          key={t.id}
          ticket={t}
          legs={legs}
          horsesById={horsesById}
          hitRate={simResultsById?.[t.id]?.estimated_hit_rate_pct ?? null}
          disposition={dispositions[makeKey(variant.budget_dollars, t.id)]}
          onSetDisposition={(value) =>
            onSetDisposition(variant.budget_dollars, t.id, value)
          }
        />
      ))}
    </div>
  );
}

interface TicketCardProps {
  ticket: BuiltTicket;
  legs: Race[];
  horsesById: Record<string, Horse>;
  hitRate: number | null;
  disposition: Disposition;
  onSetDisposition: (value: Disposition) => void;
}

function TicketCard({
  ticket,
  legs,
  horsesById,
  hitRate,
  disposition,
  onSetDisposition,
}: TicketCardProps) {
  const dropped = disposition === "drop";
  return (
    <article
      aria-label={`Ticket ${ticket.id}`}
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "0.7rem 0.85rem",
        background: dropped ? "var(--surface-alt)" : "var(--surface)",
        opacity: dropped ? 0.65 : 1,
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: "0.5rem",
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "0.6rem",
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontWeight: 700, fontSize: "1rem" }}>
            {ticketLabel(ticket)}
          </span>
          <span
            style={{
              fontSize: "0.8rem",
              color: "var(--text-muted)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {money(ticket.cost)}
          </span>
          {hitRate !== null ? (
            <span
              style={{
                fontSize: "0.8rem",
                color: "var(--accent)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {pct(hitRate, 2)} hit
            </span>
          ) : ticket.hit_rate_pct !== undefined ? (
            <span
              style={{
                fontSize: "0.8rem",
                color: "var(--accent)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {pct(ticket.hit_rate_pct, 2)} hit
            </span>
          ) : null}
          {ticket.payout_score !== undefined ? (
            <span
              style={{
                fontSize: "0.8rem",
                color: "var(--text-muted)",
                fontVariantNumeric: "tabular-nums",
              }}
              title="Payout score"
            >
              payout {num(ticket.payout_score, 2)}
            </span>
          ) : null}
          {ticket.confidence !== undefined ? (
            <span
              style={{
                fontSize: "0.8rem",
                color: "var(--text-muted)",
                fontVariantNumeric: "tabular-nums",
              }}
              title="Confidence"
            >
              conf {num(ticket.confidence, 2)}
            </span>
          ) : null}
          {ticket.chalk_exposure !== undefined ? (
            <span
              style={{
                fontSize: "0.8rem",
                color: "var(--text-muted)",
                fontVariantNumeric: "tabular-nums",
              }}
              title="Chalk exposure"
            >
              chalk {pct(ticket.chalk_exposure * 100, 0)}
            </span>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            type="button"
            className="tap-target"
            aria-pressed={disposition === "keep"}
            onClick={() =>
              onSetDisposition(disposition === "keep" ? undefined : "keep")
            }
            style={{
              ...KEEP_DROP_BUTTON,
              background:
                disposition === "keep" ? "var(--good-bg)" : "var(--surface)",
              borderColor:
                disposition === "keep" ? "var(--good)" : "var(--border)",
              color: disposition === "keep" ? "var(--good)" : "var(--text)",
            }}
          >
            Keep
          </button>
          <button
            type="button"
            className="tap-target"
            aria-pressed={disposition === "drop"}
            onClick={() =>
              onSetDisposition(disposition === "drop" ? undefined : "drop")
            }
            style={{
              ...KEEP_DROP_BUTTON,
              background:
                disposition === "drop" ? "#fde2e2" : "var(--surface)",
              borderColor:
                disposition === "drop" ? "var(--bad)" : "var(--border)",
              color: disposition === "drop" ? "var(--bad)" : "var(--text)",
            }}
          >
            Drop
          </button>
        </div>
      </header>

      {ticket.notes ? (
        <p
          style={{
            margin: 0,
            fontSize: "0.78rem",
            fontStyle: "italic",
            color: "var(--text-muted)",
          }}
        >
          {ticket.notes}
        </p>
      ) : null}

      <ol
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {ticket.selections.map((horseIds, legIdx) => {
          const race = legs[legIdx];
          return (
            <li
              key={legIdx}
              style={{
                display: "grid",
                gridTemplateColumns: "70px 1fr",
                gap: "0.5rem",
                padding: "4px 0",
              }}
            >
              <span
                style={{
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  color: "var(--text-muted)",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                Leg {legIdx + 1}
                {race ? (
                  <span
                    style={{
                      display: "block",
                      fontWeight: 500,
                      textTransform: "none",
                      letterSpacing: 0,
                      fontSize: "0.7rem",
                    }}
                  >
                    R{race.raceNumber}
                  </span>
                ) : null}
              </span>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 4,
                }}
              >
                {horseIds.map((hid) => {
                  const horse = horsesById[hid];
                  return (
                    <span
                      key={hid}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                        padding: "2px 8px",
                        borderRadius: 999,
                        background: "var(--surface-alt)",
                        border: "1px solid var(--border)",
                        fontSize: "0.8rem",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      <strong>{horse?.post ?? "?"}</strong>
                      <span>{horse?.name ?? hid}</span>
                    </span>
                  );
                })}
              </div>
            </li>
          );
        })}
      </ol>
    </article>
  );
}
