# Build plan: Canada Data Agent & Eval Lab v1.0

This plan follows SPEC v1.0 (§13.2): **18 PRs over about 6 weekends.** Each PR is one reviewable slice, with a Conventional Commit title and a squash merge. A tag marks the end of each week. **Bold = George writes it by hand** (the ownership rule in SPEC §2); Claude explains, reviews and writes the rest.

Every PR description says *what changed, how it was verified, and what it proves*. From W4 on, it also includes the eval delta.

## W1: data in, vector retrieval measured (tag `w1`)
| PR | Title | Done when |
|---|---|---|
| 1 | `chore: uv project, ruff, pytest, Compose (Postgres 17 + pgvector), CI skeleton (pull_request only, SHA-pinned actions, gitleaks)` | `uv sync --locked && pytest` is green in CI; Day-one check of SPEC §13.1 recorded in ADR 0001 (stack versions verified against docs) |
| 2 | `feat(wds): StatCan client - host allowlist hook, limiter, retries with jitter, http_cache (never caches errors)` | **Limiter** hand-written; unit tests with vcr cassettes cover the reset, empty-body, 409 and 5xx paths |
| 3 | `feat(index): scope config + table_card/member schema + card builder` | `config/scope.toml` written with the prefixes confirmed live; 525 null-subject tables logged; card ≤600 tokens; Rent (81) appears in `member` |
| 4 | `feat(index): Voyage embeddings, idempotent re-index, index dump (make index / make seed)` | Re-running is a no-op; `make seed` restores the index with no Voyage key |
| 5 | `feat(eval): retrieval-only eval + 15 retrieval questions; vector-only baseline` | recall@5 and MRR printed and committed as ablation row 1 |

## W2: hybrid search and MCP tools (tag `w2`)
| PR | Title | Done when |
|---|---|---|
| 6 | `feat(search): full-text over all member names (ORed terms) + RRF` | **RRF** hand-written; ablation rows 2–3 committed |
| 7 | `feat(search): rerank-3 behind a flag` | Ablation row 4; enabled only if recall@5 improves (ADR 0002 records the result either way) |
| 8 | `feat(series): coordinate builder + get_series via LatestNPeriods, with the responseStatusCode/vectorId check` | **Coordinate builder** hand-written; tests cover Ontario+Rent = `14.81.0.0.0.0.0.0.0.0`, invalid → `BAD_MEMBERS`, null → suppressed |
| 9 | `feat(mcp): canada-data server with 3 tools, untrusted_text escaping, server-built URLs, result caps` | `claude mcp add` works; Claude Code calls all 3 tools; tool-description snapshot test |

## W3: the agent (tag `w3`)
| PR | Title | Done when |
|---|---|---|
| 10 | `feat(agent): canada-ask CLI on the tool runner, system prompt v1 with canary, budgets` | Answers the Rent question with +2.0% and a StatCan link |
| 11 | `feat(agent): structured answer_values + refused, --trace, JSON logs with cost` | 5 demo questions answered; README GIF recorded from `--trace` |

## W4: golden set and graders (tag `w4`)
| PR | Title | Done when |
|---|---|---|
| 12 | `test(golden): 40 cases committed before tuning (24 dev / 16 test), each checked on the StatCan site` | Lint check: every case has `checked_on_statcan_site: true`; ≥⅓ paraphrased from The Daily |
| 13 | `feat(eval): deterministic graders (values in prose, grounding recompute, citation hosts, refusal, trajectory)` | **Graders** hand-written; they pass on hand-made good transcripts and fail on hand-made bad ones |
| 14 | `feat(eval): snapshot backend + make snapshot + query-embedding cache; SNAPSHOT_MISS as a failure` | A full dev run works offline except for the Claude call |

## W5: gate, security, proof (tag `w5`)
| PR | Title | Done when |
|---|---|---|
| 15 | `ci(eval): flakiness study, baseline.json, dev gate (k=3, flip rule, $2 cap), CI diff flag, dedicated key` | Study results in the README; the gate runs on ready-for-review PRs only, and fork PRs never get the key |
| 16 | `test(security): 6 injection cases (3 vectors × 2 goals), canary, allowed_tools, max_tool_calls` | All 6 pass at k=3; "limits of this suite" section written |
| 17 | `demo: a deliberately degraded tool description, failed by the gate` | **The PR is left open or closed unmerged and linked from the README** as the evidence |

## W6: release (tag `v1.0.0`)
| PR | Title | Done when |
|---|---|---|
| 18 | `docs: v1.0 - test-split headline (Wilson CI), history chart, FINDINGS.md (3 real catches), claims-to-evidence table, ADR index` | The `v1.0.0` tag triggers the one test-split run; the README headline comes from it |

## If behind schedule
At the end of W4, if PRs 1–14 aren't merged, ship **v0.9**: retrieval ablation + agent + offline graders, with no LLM gate. The gate, injection suite and release move to v1.0 the following weekend.

## Out of scope for this plan
Everything in SPEC §5 v1.1: Open Canada and FX tools, the LLM judge, the weekly drift job, the month-to-date guard, the `compute` tool, more cases.
