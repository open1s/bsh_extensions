---
name: ariz-triz
description: Systematic innovation for a Trinno research project using TRIZ (IFR, technical/physical contradictions, 40 inventive principles, separation principles, resource analysis, evolution trends) and the ARIZ-85C nine-part algorithm. Turns research gaps from gaps.md into verifiable innovation points and writes them back into the proposal draft. Use when the reader asks for innovation points, ARIZ, TRIZ, contradiction analysis, or systematic idea generation.
version: 1.0.0
---

# ARIZ / TRIZ systematic innovation

Use this skill when the reader wants defensible innovation points (创新点) for a proposal, or explicitly asks for TRIZ/ARIZ. The premise of TRIZ: inventive problems recur across fields as *contradictions*, and a finite set of principles resolves them. ARIZ is the step-by-step algorithm for problems the principles alone do not crack. You do all reasoning; Trinno's tools only scaffold files and verify novelty by literature search.

## Setup

1. Confirm the absolute project `path`; call `init_project(path)` if `innovation/` is missing. It creates `innovation/triz-analysis.md`, `innovation/ariz-worksheet.md`, `innovation/solutions.md` without overwriting.
2. Read `gaps.md` and the relevant `notes/` cards. Each candidate innovation must start from an evidenced gap or limitation, not from a brainstorm. If `gaps.md` is empty, run the `research-workflow` / `research-methodology` skills first.

## TRIZ toolbox (reference)

**IFR (Ideal Final Result)**: the system performs the needed function by itself, with no added cost or harm. Formulate it before proposing solutions; it is the yardstick every candidate is measured against.

**Contradictions**:
- *Technical*: improving parameter A worsens parameter B (e.g. accuracy vs latency, model capacity vs training data). Resolve with the 40 inventive principles via the contradiction matrix logic — you reason the mapping yourself; do not pretend to look up a table you do not have.
- *Physical*: one parameter must be both X and not-X (e.g. the cache must be large for hit rate and small for latency). Resolve with **separation principles**: in time, in space, on condition, between parts and whole.

**40 inventive principles** (short list; cite by number + name when used): 1 Segmentation, 2 Taking out, 3 Local quality, 4 Asymmetry, 5 Merging, 6 Universality, 7 Nested doll, 8 Anti-weight, 9 Preliminary anti-action, 10 Preliminary action, 11 Beforehand cushioning, 12 Equipotentiality, 13 The other way round, 14 Spheroidality, 15 Dynamics, 16 Partial or excessive actions, 17 Another dimension, 18 Mechanical vibration, 19 Periodic action, 20 Continuity of useful action, 21 Skipping, 22 Blessing in disguise, 23 Feedback, 24 Intermediary, 25 Self-service, 26 Copying, 27 Cheap short-living objects, 28 Mechanics substitution, 29 Pneumatics and hydraulics, 30 Flexible shells and thin films, 31 Porous materials, 32 Color changes, 33 Homogeneity, 34 Discarding and recovering, 35 Parameter changes, 36 Phase transitions, 37 Thermal expansion, 38 Strong oxidants, 39 Inert atmosphere, 40 Composite structures. In software/ML research the analogues are legitimate (e.g. 1 = modularization/sharding, 15 = adaptive schedules, 23 = closed-loop control, 25 = self-supervision, 26 = distillation/surrogates, 35 = precision/temperature changes) — state the analogy explicitly.

**Resources**: substance, energy/field, information, time, space and functional resources already inside the system or its supersystem. ARIZ prefers solutions that spend existing resources over ones that import new components.

**Evolution trends**: increasing ideality, increasing dynamism/controllability, transition to the micro level, coordination of rhythms, uneven development of parts, transition to supersystem, S-curve position. Use them to sanity-check whether a candidate points where the field is already going.

## ARIZ-85C walk (fill innovation/ariz-worksheet.md part by part)

Work the parts in order; write conclusion first, then evidence. Never skip a part silently — if a part does not apply, write why.

- **Part 1 — Analyze the problem.** State the mini-problem (keep the system simple, remove the harmful effect). Identify the conflict pair tool–artifact. Draw the two states (current vs desired). Pick the conflict whose resolution is more likely to satisfy the IFR. Intensify the conflict to its extreme form. Define the operative zone and operative time precisely — a vague zone is the most common failure. Check whether a known standard solution already applies.
- **Part 2 — Analyze the problem model.** Restate the IFR; extract the physical contradiction inside the operative zone. If it is directly resolvable by a separation principle, jump to Part 7.
- **Part 3 — Formulate IFR and physical contradiction.** Macro-level contradiction and the operational IFR ("the X-element itself, without complication, does …").
- **Part 4 — Mobilize substance-field resources.** List and combine resources from `triz-analysis.md` §4; prefer derived and supersystem resources before importing anything new.
- **Part 5 — Apply the knowledge base.** Map candidate inventive principles and separation principles with explicit reasoning; search analogous solved problems in other fields via `search_literature` (record the query). If a physical solution emerges, jump to Part 7.
- **Part 6 — Change or replace the problem.** If no solution: the problem statement is usually wrong. Change the conflict pair, move up/down a system level, or invert the problem; log the new statement and return to Part 1. Every backtrack goes into worksheet §10 with date and reason.
- **Part 7 — Evaluate the solution.** Check against the IFR (self-resolving? new harm introduced?). Verify novelty with `search_literature` using the solution's key terms — record queries and hits as evidence in `solutions.md`; "not found in OpenAlex/arXiv" is weaker than "novel", say exactly that. List the sub-problems the solution still leaves open.
- **Part 8 — Utilize the solution.** Where else does it apply; what supersystem changes follow.
- **Part 9 — Review the process.** Record the actual path, dead ends and backtracks — this is the audit trail that makes the innovation defensible in an opening defense.

## Outputs and hand-off

1. `innovation/triz-analysis.md`: system, IFR, contradictions, resources, trends — every claim linked to `gaps.md`/`notes/` evidence.
2. `innovation/ariz-worksheet.md`: the nine parts filled, backtracks logged.
3. `innovation/solutions.md`: candidate table (solution, originating principle/step, contradiction removed, novelty-search evidence, status), plus a falsifiable hypothesis, verification method and quantified success criterion for each adopted solution.
4. Write adopted solutions into `proposal-draft.md` §创新点, each as: 矛盾 → 解法 → 与现有工作的差异（证据链接）→ 验证计划. Log the write-back in `solutions.md` §3. An innovation point without a verification plan is not finished.

## Rules

- Analysis in Chinese; TRIZ terms (IFR, ARIZ, tool/artifact, principle names) stay in English.
- Every contradiction must cite the evidence (paper limitation, gap entry) that establishes it; invented contradictions produce invented innovations.
- Do not claim patent-level novelty from a two-source literature search; state the search's coverage limits.
- Prefer resource-spending solutions over component-adding ones; measure every candidate against the IFR.
- Never overwrite or delete project files; the worksheet's backtrack log is append-only.
- The tools do no reasoning and make no LLM calls; you are the only analysis engine.