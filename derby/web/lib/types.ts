// Shared frontend types. Field names mirror api/model.py so JSON crosses the
// FastAPI ↔ Next.js boundary without renames.

export type Day = "friday" | "saturday";

export type Track = "Churchill Downs";

export type SequenceRole =
  | "pick5-leg-1"
  | "pick5-leg-2"
  | "pick5-leg-3"
  | "pick5-leg-4"
  | "pick5-leg-5";

export type UserTag =
  | "single"
  | "A"
  | "B"
  | "C"
  | "toss"
  | "chaos"
  | "boost"
  | "fade";

export interface Horse {
  id: string;
  raceId: string;
  post: number;
  name: string;
  jockey?: string;
  trainer?: string;
  morningLineOdds?: string;
  currentOdds?: string;
  scratched?: boolean;
  source?: string;
  marketProbability?: number;
  morningLineProbability?: number;
  modelProbability?: number;
  finalProbability?: number;
  userTag?: UserTag;
  flags: string[];
}

export interface Race {
  id: string;
  day: Day;
  track: Track;
  raceNumber: number;
  postTime?: string;
  name?: string;
  surface?: string;
  distance?: string;
  sequenceRole?: SequenceRole;
  horses: Horse[];
}

export interface OddsSnapshot {
  timestamp: string;
  day: Day;
  raceNumber: number;
  horseId: string;
  odds: string;
  impliedProbability: number;
  source: string;
}

// ---------------------------------------------------------------------------
// API envelope and odds payload — mirror api/main.py
// ---------------------------------------------------------------------------

export interface Envelope<T> {
  data: T;
  stale: boolean;
  cached_at: string | null;
  source: string;
  errors: string[];
}

export interface OddsRunner {
  horseId: string;
  horseName: string;
  odds: string;
  impliedProbability: number;
  source: string;
  capturedAt: string;
}

export interface OddsRacePayload {
  raceId: string;
  raceNumber: number;
  sequenceRole: SequenceRole;
  runners: OddsRunner[];
}

// ---------------------------------------------------------------------------
// Simulation + ticket payloads — mirror api/sim.py and api/tickets.py
// ---------------------------------------------------------------------------

export interface TicketSimulationResult {
  ticket_id: string;
  cost: number;
  estimated_hit_rate_pct: number;
  chalkiness_pct: number;
  chaos_coverage_pct: number;
  separator_coverage_pct: number;
}

export interface SimulationResult {
  n_iterations: number;
  tickets: TicketSimulationResult[];
}

export interface BuiltTicket {
  id: string;
  cost: number;
  selections: string[][];
}

export interface BudgetVariant {
  budget_dollars: number;
  tickets: BuiltTicket[];
}

export interface BuildTicketsResponse {
  variants: BudgetVariant[];
}
