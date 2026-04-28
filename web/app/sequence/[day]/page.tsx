"use client";

import { notFound } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DayHeader } from "../../../components/DayHeader";
import { RaceCard } from "../../../components/RaceCard";
import { SimulationSummary } from "../../../components/SimulationSummary";
import { StaleBanner } from "../../../components/StaleBanner";
import { TagPicker } from "../../../components/TagPicker";
import { TicketBuilder } from "../../../components/TicketBuilder";
import { OddsOverride } from "../../../components/OddsOverride";
import {
  buildTickets,
  fetchCard,
  refreshCard,
  refreshOdds,
  simulate,
} from "../../../lib/api";
import type {
  BudgetVariant,
  Day,
  Envelope,
  Race,
  SequenceRole,
  SimulationResult,
  TicketSimulationResult,
  UserTag,
} from "../../../lib/types";

const DAYS: Day[] = ["friday", "saturday"];

const SEQUENCE_ORDER = [
  "pick5-leg-1",
  "pick5-leg-2",
  "pick5-leg-3",
  "pick5-leg-4",
  "pick5-leg-5",
] as const;

function legSort(a: Race, b: Race): number {
  const ai = a.sequenceRole ? SEQUENCE_ORDER.indexOf(a.sequenceRole) : 99;
  const bi = b.sequenceRole ? SEQUENCE_ORDER.indexOf(b.sequenceRole) : 99;
  if (ai !== bi) return ai - bi;
  return a.raceNumber - b.raceNumber;
}

interface PageProps {
  params: { day: string };
}

export default function SequenceDayPage({ params }: PageProps) {
  if (!DAYS.includes(params.day as Day)) {
    notFound();
  }
  const day = params.day as Day;

  const [races, setRaces] = useState<Race[]>([]);
  const [cardEnvelope, setCardEnvelope] = useState<Envelope<Race[]> | null>(null);
  const [lastCardRefresh, setLastCardRefresh] = useState<string | null>(null);
  const [lastOddsRefresh, setLastOddsRefresh] = useState<string | null>(null);
  const [refreshFailedAt, setRefreshFailedAt] = useState<string | null>(null);
  const [source, setSource] = useState<string>("");
  const [tags, setTags] = useState<Record<string, UserTag>>({});
  const [oddsOverrides, setOddsOverrides] = useState<Record<string, string>>({});
  const [budget, setBudget] = useState<number>(96);
  const [baseUnit, setBaseUnit] = useState<number>(0.5);
  const [busy, setBusy] = useState({
    card: false,
    odds: false,
    sim: false,
    tickets: false,
  });
  const [error, setError] = useState<string | null>(null);
  const [tagPickerHorseId, setTagPickerHorseId] = useState<string | null>(null);
  const [oddsHorseId, setOddsHorseId] = useState<string | null>(null);
  const [resultMsg, setResultMsg] = useState<string | null>(null);
  const [simResult, setSimResult] = useState<SimulationResult | null>(null);
  const [simError, setSimError] = useState<string | null>(null);
  const [ticketVariants, setTicketVariants] = useState<BudgetVariant[]>([]);
  const [ticketsError, setTicketsError] = useState<string | null>(null);

  const ingestEnvelope = useCallback(
    (env: Envelope<Race[]>, kind: "card" | "odds") => {
      setCardEnvelope(env);
      const sorted = [...env.data].sort(legSort);
      setRaces(sorted);
      setSource(env.source);
      const stamp = env.cached_at ?? new Date().toISOString();
      if (kind === "card") setLastCardRefresh(stamp);
      if (kind === "odds") setLastOddsRefresh(stamp);
      if (env.stale && env.errors.length > 0) {
        setRefreshFailedAt(new Date().toISOString());
      } else {
        setRefreshFailedAt(null);
      }
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    fetchCard(day)
      .then((env) => {
        if (cancelled) return;
        ingestEnvelope(env, "card");
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [day, ingestEnvelope]);

  const allHorses = useMemo(
    () => races.flatMap((r) => r.horses),
    [races],
  );

  const pick5Legs = useMemo<Race[]>(() => {
    const byRole = new Map<SequenceRole, Race>();
    for (const r of races) {
      if (r.sequenceRole && !byRole.has(r.sequenceRole)) {
        byRole.set(r.sequenceRole, r);
      }
    }
    return SEQUENCE_ORDER.map((role) => byRole.get(role)).filter(
      (r): r is Race => r !== undefined,
    );
  }, [races]);

  const simResultsById = useMemo<Record<string, TicketSimulationResult>>(() => {
    if (!simResult) return {};
    const map: Record<string, TicketSimulationResult> = {};
    for (const t of simResult.tickets) map[t.ticket_id] = t;
    return map;
  }, [simResult]);

  const tagPickerHorse = tagPickerHorseId
    ? allHorses.find((h) => h.id === tagPickerHorseId)
    : null;
  const oddsHorse = oddsHorseId
    ? allHorses.find((h) => h.id === oddsHorseId)
    : null;

  async function handleRefreshCard() {
    setBusy((b) => ({ ...b, card: true }));
    setError(null);
    try {
      const env = await refreshCard(day);
      ingestEnvelope(env, "card");
    } catch (e) {
      setError(String(e));
      setRefreshFailedAt(new Date().toISOString());
    } finally {
      setBusy((b) => ({ ...b, card: false }));
    }
  }

  async function handleRefreshOdds() {
    setBusy((b) => ({ ...b, odds: true }));
    setError(null);
    try {
      const env = await refreshOdds(day);
      // Odds refresh returns per-race odds payloads, but the cached card
      // already carries the latest odds via the backend's
      // `races_with_latest_odds`; we pull a fresh card to keep the UI in sync.
      const cardEnv = await fetchCard(day);
      if (env.stale) {
        setCardEnvelope({ ...cardEnv, stale: true, errors: env.errors });
        setRaces([...cardEnv.data].sort(legSort));
        setRefreshFailedAt(new Date().toISOString());
      } else {
        ingestEnvelope(cardEnv, "odds");
      }
      setLastOddsRefresh(env.cached_at ?? new Date().toISOString());
      setSource(env.source);
    } catch (e) {
      setError(String(e));
      setRefreshFailedAt(new Date().toISOString());
    } finally {
      setBusy((b) => ({ ...b, odds: false }));
    }
  }

  async function handleRunSim() {
    setBusy((b) => ({ ...b, sim: true }));
    setSimError(null);
    setResultMsg(null);
    try {
      // tags / oddsOverrides intentionally omitted — backend forbids
      // extras and does not yet consume them. See lib/api.ts comment.
      const env = await simulate(day, {});
      if (env.errors.length > 0) {
        setSimError(env.errors.join("; "));
        setSimResult(null);
      } else {
        setSimResult(env.data);
      }
    } catch (e) {
      setSimError(String(e));
      setSimResult(null);
    } finally {
      setBusy((b) => ({ ...b, sim: false }));
    }
  }

  async function handleBuildTickets() {
    setBusy((b) => ({ ...b, tickets: true }));
    setTicketsError(null);
    setResultMsg(null);
    try {
      // tags / oddsOverrides intentionally omitted — see handleRunSim.
      const env = await buildTickets(day, {
        budget_dollars: budget,
        base_unit: baseUnit,
      });
      if (env.errors.length > 0) {
        setTicketsError(env.errors.join("; "));
        setTicketVariants([]);
      } else {
        setTicketVariants(env.data?.variants ?? []);
      }
    } catch (e) {
      setTicketsError(String(e));
      setTicketVariants([]);
    } finally {
      setBusy((b) => ({ ...b, tickets: false }));
    }
  }

  function applyTag(horseId: string, tag: UserTag | null) {
    setTags((prev) => {
      const next = { ...prev };
      if (tag === null) delete next[horseId];
      else next[horseId] = tag;
      return next;
    });
  }

  function applyOddsOverride(horseId: string, value: string | null) {
    setOddsOverrides((prev) => {
      const next = { ...prev };
      if (value === null) delete next[horseId];
      else next[horseId] = value;
      return next;
    });
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        padding: "1rem clamp(0.75rem, 2vw, 2rem) 3rem",
        display: "flex",
        flexDirection: "column",
        gap: "1rem",
        // The grid + card layout already wraps; this keeps overflow vertical
        // so iPad portrait/landscape never need horizontal scroll.
        overflowX: "hidden",
      }}
    >
      <DayHeader
        day={day}
        lastCardRefresh={lastCardRefresh}
        lastOddsRefresh={lastOddsRefresh}
        source={source}
        budget={budget}
        baseUnit={baseUnit}
        busy={busy}
        onRefreshCard={handleRefreshCard}
        onRefreshOdds={handleRefreshOdds}
        onRunSim={handleRunSim}
        onBuildTickets={handleBuildTickets}
        onBudgetChange={setBudget}
        onBaseUnitChange={setBaseUnit}
      />

      {cardEnvelope?.stale ? (
        <StaleBanner
          cachedAt={cardEnvelope.cached_at}
          failedAt={refreshFailedAt}
          errors={cardEnvelope.errors}
        />
      ) : null}

      {error ? (
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
          {error}
        </div>
      ) : null}

      {resultMsg ? (
        <div
          role="status"
          style={{
            background: "#e8f0fe",
            color: "#173366",
            border: "1px solid #b9cdf3",
            borderRadius: 10,
            padding: "0.6rem 0.9rem",
          }}
        >
          {resultMsg}
        </div>
      ) : null}

      {races.length === 0 ? (
        <div
          style={{
            padding: "2rem",
            textAlign: "center",
            color: "var(--text-muted)",
            background: "var(--surface)",
            border: "1px dashed var(--border)",
            borderRadius: 14,
          }}
        >
          No card loaded yet — tap <strong>Refresh Card</strong>.
        </div>
      ) : (
        <div
          style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}
        >
          {races.map((r) => (
            <RaceCard
              key={r.id}
              race={r}
              tagsByHorseId={tags}
              oddsOverridesByHorseId={oddsOverrides}
              onOpenTag={setTagPickerHorseId}
              onOpenOddsOverride={setOddsHorseId}
            />
          ))}
        </div>
      )}

      {races.length > 0 ? (
        <SimulationSummary
          result={simResult}
          loading={busy.sim}
          error={simError}
        />
      ) : null}

      {races.length > 0 ? (
        <TicketBuilder
          variants={ticketVariants}
          loading={busy.tickets}
          error={ticketsError}
          legs={pick5Legs}
          simResultsById={simResultsById}
        />
      ) : null}

      {tagPickerHorse ? (
        <TagPicker
          horseName={tagPickerHorse.name}
          current={tags[tagPickerHorse.id]}
          onSelect={(t) => applyTag(tagPickerHorse.id, t)}
          onClose={() => setTagPickerHorseId(null)}
        />
      ) : null}

      {oddsHorse ? (
        <OddsOverride
          horseName={oddsHorse.name}
          current={oddsHorse.currentOdds}
          morningLine={oddsHorse.morningLineOdds}
          initial={oddsOverrides[oddsHorse.id] ?? null}
          onSubmit={(v) => applyOddsOverride(oddsHorse.id, v)}
          onClose={() => setOddsHorseId(null)}
        />
      ) : null}
    </main>
  );
}
