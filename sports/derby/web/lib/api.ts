import type {
  BuildTicketsResponse,
  Day,
  Envelope,
  OddsRacePayload,
  Race,
  SimulationResult,
} from "./types";

// All requests go through Next.js rewrites configured in next.config.mjs,
// so the path is the same in dev, Docker, and production.
const BASE = "/api";

async function call<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<Envelope<T>> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${method} ${path} failed: ${res.status}`);
  }
  return (await res.json()) as Envelope<T>;
}

export const fetchCard = (day: Day) =>
  call<Race[]>("GET", `/cards/${day}`);

export const refreshCard = (day: Day) =>
  call<Race[]>("POST", `/cards/${day}/refresh`);

export const fetchOdds = (day: Day) =>
  call<OddsRacePayload[]>("GET", `/odds/${day}`);

export const refreshOdds = (day: Day) =>
  call<OddsRacePayload[]>("POST", `/odds/${day}/refresh`);

// `tags` and `oddsOverrides` are intentionally NOT in the request bodies:
// the FastAPI models reject unknown fields (extra="forbid"), and the
// backend has no tag-aware sim wiring yet. UI-side tagging remains as a
// local-only display affordance until the backend feature lands. See
// docs/audits/error-handling-report.md F17 / Escalation E1.
export interface SimulateBody {
  n_iterations?: number;
}

export interface BuildTicketsBody {
  budget_dollars?: number;
  base_unit?: number;
}

export const simulate = (day: Day, body: SimulateBody) =>
  call<SimulationResult | null>("POST", `/simulate/${day}`, body);

export const buildTickets = (day: Day, body: BuildTicketsBody) =>
  call<BuildTicketsResponse | null>("POST", `/tickets/${day}/build`, body);
