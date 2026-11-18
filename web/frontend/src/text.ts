// Fixed text the page shows. Model and tool text is never turned into markup.
import type { Attack, Category, Tool } from "./events";

export const TOOL_NAMES: Record<Tool, string> = {
  search_tables: "Search tables",
  get_table_dimensions: "Read table dimensions",
  get_series: "Fetch series",
};

export const CATEGORY_NAMES: Record<Exclude<Category, "live">, string> = {
  answer: "Answers",
  refusal: "Refusals",
  attack_resisted: "Attacks it resisted",
  rejected: "Rejected by its own checks",
};

const ROUTES: Record<Attack["route"], string> = {
  card: "a table's description card",
  member_name: "a table member's name",
  error_body: "an error message from the data service",
};

const GOALS: Record<Attack["goal"], string> = {
  exfil_url: "tried to make it cite another website",
  wrong_value: "tried to make it report a false number",
};

export function attackCaption(a: Attack): string {
  return (
    `This run carried a planted attack: an instruction hidden in ${ROUTES[a.route]} ` +
    `${GOALS[a.goal]}. The agent's answer passed the runtime checks. ` +
    "The planted text isn't shown, so this page can't pass the attack on."
  );
}

export const REPO_URL = "https://github.com/gcode33/canada-data-agent";

// Built from the replay index, so the counts can't drift from what's actually shown.
export function libraryHeader(counts: Record<string, number>): string {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    `All ${total} dev questions (the set the agent was tuned on), one recorded run each: ` +
    `${counts.answer ?? 0} answers and ${counts.refusal ?? 0} refusals the graders passed, ` +
    `${counts.attack_resisted ?? 0} attacks it resisted, and ${counts.rejected ?? 0} answer its ` +
    "own checks rejected. The held-out result for v1.0 is on the \"How it's tested\" tab; " +
    "it is not re-run here."
  );
}

// What the runtime checks verify (src/canada_agent/ask.py, check_grounded): each reported level
// must equal a value the tools returned for that series in this run (not its period); changes,
// ratios and numbers in the prose are the model's own.
export const CHANGE_NOTE =
  "Levels were checked against values the tools returned for their series; changes and " +
  "ratios are the model's own arithmetic and aren't checked.";
export const NOTHING_CHECKED_NOTE =
  "None of these values is a level, so none was checked against the data: they're the " +
  "model's own arithmetic from the series below.";
