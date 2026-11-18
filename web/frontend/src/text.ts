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

export const LIBRARY_HEADER =
  "20 of the 21 answerable dev questions (the set the agent was tuned on), 3 attacks it " +
  "resisted, and 1 answer its own checks rejected. The held-out result for v1.0 is 13/16; " +
  "it is not re-run here.";

export const CHANGE_NOTE =
  "Changes are computed by the model from the levels shown; only levels are checked against the data.";
