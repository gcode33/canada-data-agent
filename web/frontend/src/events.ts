// The UI event contract, written by hand against web/schema/events.v1.json (A8 §9).
// A Vitest test fails if these `type` names drift from the schema; pytest validates every
// bundled replay against the schema itself.

export const EVENT_TYPES = [
  "run_started",
  "step_started",
  "step_finished",
  "series",
  "answer",
  "run_failed",
  "run_finished",
] as const;

export type Category = "live" | "answer" | "refusal" | "attack_resisted" | "rejected";
export type Tool = "search_tables" | "get_table_dimensions" | "get_series";

export type Provenance =
  | { source: "live" }
  | {
      source: "recording";
      case: string;
      model: string;
      commit: string;
      commit_date: string;
      recorded_at: string | null;
      timing: "recorded" | "approximate";
      recorded_wall_s: number | null;
    };

export interface Attack {
  goal: "exfil_url" | "wrong_value";
  route: "card" | "member_name" | "error_body";
}

export interface RunStarted {
  type: "run_started";
  mode: "live" | "replay";
  category: Category;
  question: string;
  model: string;
  prompt_version: string;
  provenance: Provenance;
  attack: Attack | null;
}

export interface StepStarted {
  type: "step_started";
  step_id: string;
  tool: Tool;
  arguments_text: string;
}

export interface StepFinished {
  type: "step_finished";
  step_id: string;
  ok: boolean;
  latency_ms: number | null;
  error_code: string | null;
  summary: string;
}

export interface Point {
  ref_period: string;
  value: number | null;
  status_symbol: string | null;
}

export interface Series {
  type: "series";
  step_id: string;
  product_id: number;
  table_url: string;
  vector_id: number;
  scalar_factor: string;
  truncated: boolean;
  label: string | null;
  points: Point[];
}

export interface AnswerValue {
  label: "level" | "change_abs" | "change_pct" | "ratio";
  description: string;
  value: number;
  unit: string;
  vector_id: number;
  ref_period: string;
}

export interface Link {
  url: string;
  linkable: boolean;
}

export interface Answer {
  type: "answer";
  answer: string;
  answer_values: AnswerValue[];
  links: Link[];
  refused: boolean;
}

export interface RunFailed {
  type: "run_failed";
  code: string;
  message: string;
}

export interface RunFinished {
  type: "run_finished";
  num_turns: number;
  duration_ms: number;
  api_equivalent_usd: number | null;
  billed: "subscription" | "none";
}

export type UiEvent =
  | RunStarted
  | StepStarted
  | StepFinished
  | Series
  | Answer
  | RunFailed
  | RunFinished;

export interface IndexEntry {
  case: string;
  category: Exclude<Category, "live">;
  question: string;
}
