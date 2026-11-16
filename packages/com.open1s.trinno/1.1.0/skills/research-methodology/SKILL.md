---
name: research-methodology
description: Best-practice research methodology for a Trinno project - preregistration-style protocol (PICO/SPIDER), reproducible search strings, PRISMA-style screening with an exclusion log, critical appraisal by study type, evidence grading for gap claims, and a reproducibility checklist. Use before and during literature review, and whenever the reader asks for rigorous review practice.
version: 1.0.0
---

# Research methodology

Use this skill when the reader wants a rigorous literature review, a systematic-review-style workflow, a study protocol, or asks how to make the research defensible. It layers methodology on top of the `research-workflow` skill; Trinno's tools stay deterministic I/O and you do all analysis.

## Setup

1. Confirm the absolute project `path`. Call `init_project(path)` once: it creates `protocol.md`, `screening-log.md`, `quality-appraisal.md`, `reproducibility.md` and the `innovation/` skeletons without ever overwriting existing files. Report `created` vs `skipped` honestly.
2. Read `protocol.md` before searching. If it is already filled in, treat it as the contract: any deviation is recorded in its 修订记录 with a date and a reason.

## Step 1 — Protocol before search (preregistration-style)

Fill `protocol.md` with the reader's input, proposing defaults where they are undecided:

- State the research question in one sentence, then structure it: **PICO** (Population, Intervention, Comparison, Outcome) for quantitative/intervention questions, **SPIDER** (Sample, Phenomenon of Interest, Design, Evaluation, Research type) for qualitative or method-survey questions. For an engineering/CS topic, use: object of study, capability gap, baseline, evaluation metric.
- Write inclusion/exclusion criteria per dimension (population, design, time window, language, publication type) *before* seeing results, so screening decisions are not retrofitted.
- Plan the search as concept blocks: for each concept list English synonyms and spelling variants, combine within a block with OR and across blocks with AND. Record each final query verbatim in the protocol table — `search_literature` sends the query as-is to OpenAlex and arXiv, so the recorded string is exactly reproducible.
- Note the known coverage bias: v1 searches only OpenAlex and arXiv; state what that misses (e.g. PubMed-only clinical work) instead of pretending the coverage is complete.

## Step 2 — Reproducible search

- Run one `search_literature` call per concept-block combination; after each call, record the query, date and hit count in `protocol.md` §3.
- Iterate: if a concept block returns near-zero hits, broaden synonyms; if hits are dominated by an unrelated field, add a discriminating term. Record every revision.
- `reading-list.md` is append-only and deduplicated (DOI first, then normalized title); never edit or reorder it by hand — annotate below entries instead.

## Step 3 — PRISMA-style screening

Screen in two passes and log every decision in `screening-log.md`:

1. **Title/abstract pass**: for each reading-list entry decide include/exclude against the protocol criteria; cite the criterion number as the reason. Borderline cases go to the full-text pass, not to silent exclusion.
2. **Full-text pass**: after `intake_papers` and reading the PDFs, confirm or reverse each decision with a reason.
3. Keep the flow counts consistent: hits → deduplicated → after title/abstract → after full text → included. The counts must match the actual files; if they diverge, fix the log, not the numbers.
4. Ask the reader to adjudicate genuinely ambiguous exclusions rather than deciding silently.

## Step 4 — Critical appraisal and evidence grading

After `intake_papers`, fill the note cards, then appraise each included paper in `quality-appraisal.md` using the checklist that matches its type:

- **Randomized trial** → RoB 2 thinking: randomization, deviations from intervention, missing outcome data, outcome measurement, selective reporting.
- **Non-randomized intervention/observational** → ROBINS-I thinking: confounding, selection, classification of interventions, deviations, missing data, measurement, selective reporting.
- **Qualitative** → CASP-style questions: clear aims, appropriate design, recruitment, data collection, reflexivity, ethics, rigor of analysis, value.
- **Method/engineering/CS paper** → three axes: internal validity (does the evaluation support the claim: baselines, ablations, statistical significance), external validity (datasets/tasks beyond the paper), reproducibility (code, data, hyperparameters available).

Rate each paper 高/中/低 with concrete reasons and evidence locations (section/page/DOI). Then grade each *theme-level* conclusion in `gaps.md` by the strength of its supporting evidence: 强 (multiple independent high-quality studies), 中 (consistent but limited or medium-quality), 弱 (single study or low quality), 仅个案. A gap claim inherits the grade of the evidence that establishes it — "no evidence found in this reading list" is always weaker than "nobody has done this", and only the former is usually defensible.

## Step 5 — Reproducibility checklist

Before declaring the review done, walk `reproducibility.md` and tick each item only when it is actually true:

- every query recorded with date and hits; every exclusion has a logged reason;
- every card conclusion has an evidence location; every gap and proposal claim links back to `notes/`, `reading-list.md` or a DOI/URL;
- data/code/environment/seeds recorded when the project has experiments;
- coverage and analysis biases stated explicitly (two sources, English-only, LLM over-generalization) with the mitigation used.

## Rules

- Analysis output is Chinese; paper titles, key terms, method names (PICO, PRISMA, ROBINS-I, CASP…) stay in English.
- Protocol first, search second; deviations are logged, never silent.
- Never fabricate an appraisal: if the full text is unavailable, say so and grade on the abstract with that limitation stated.
- Never delete or overwrite anything under `papers/`; never rewrite `reading-list.md`.
- The tools do no analysis and make no LLM calls; you are the only analysis engine.

## Outputs

- `protocol.md`, `screening-log.md`, `quality-appraisal.md`, `reproducibility.md` filled in.
- `gaps.md` upgraded with per-claim evidence strength grades.
- Hand-off: when the reader wants innovation points rather than more review, switch to the `ariz-triz` skill, which consumes `gaps.md`.