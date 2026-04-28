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
  | "chaos";

export type ComputedBucket = "CORE" | "VALUE" | "CHAOS" | "TRAP" | "DEAD";

export type RaceClassification = "KEY" | "TIGHT" | "MID" | "CHAOS";

export type ChaosLevel = "LOW" | "MODERATE" | "HIGH" | "EXTREME";

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
  true_prob?: number;
  ownership_proxy?: number;
  edge_score?: number;
  confidence_score?: number;
  computedBucket?: ComputedBucket;
  userTag?: UserTag;
  flags: string[];
  steam_horse?: boolean;
  separator_candidate?: boolean;
  trap_favorite?: boolean;
  value_horse?: boolean;
  cold_horse?: boolean;
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
  classification?: RaceClassification;
  strategy?: string;
  entropy?: number;
  chaos_level?: ChaosLevel;
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
  payout_score?: number;
  confidence?: number;
}

export interface SimulationResult {
  n_iterations: number;
  tickets: TicketSimulationResult[];
}

export type TicketLabel = "Balanced" | "Safer" | "Upside";

export interface BuiltTicket {
  id: string;
  cost: number;
  selections: string[][];
  edge_score?: number;
  confidence?: number;
  payout_score?: number;
  chalk_exposure?: number;
  notes?: string;
  label?: TicketLabel;
  hit_rate_pct?: number;
}

export interface BudgetVariant {
  budget_dollars: number;
  tickets: BuiltTicket[];
}

export interface BuildTicketsResponse {
  variants: BudgetVariant[];
}
