---
name: research-workflow
description: Guide the research workflow from literature search through gap analysis to a Chinese graduate proposal draft, using Trinno's search_literature, intake_papers and init_project tools; routes rigorous review practice to research-methodology and innovation-point generation to ariz-triz.
version: 1.1.0
---

# Research workflow

Use this skill when the reader asks for literature review, research gap analysis, or a proposal/opening draft. Trinno's tools do deterministic I/O only; you do the analysis and writing.

## Workflow

1. **Locate and initialize the project folder.** The folder is the workspace root for this research task. Call `init_project` with the absolute `path` once: it creates `papers/_inbox/`, `notes/`, `innovation/` and the methodology skeletons (`protocol.md`, `screening-log.md`, `quality-appraisal.md`, `reproducibility.md`, `innovation/triz-analysis.md`, `innovation/ariz-worksheet.md`, `innovation/solutions.md`) without ever overwriting existing files. Never modify files under `papers/` except files inside `papers/_inbox/`.
   For a rigorous, systematic-review-style workflow (protocol first, PRISMA screening, critical appraisal), follow the **research-methodology** skill for steps 2–5 below; it layers on top of this workflow.
2. **Search.** Call `search_literature` with the absolute project `path`, a focused `query`, `limit` (default 10) and `download` (default true). Run several queries for the key concepts of the topic; each call appends only new entries to `reading-list.md`. PDF downloads are bounded per call (`max_downloads`, default 2): when `pending_downloads` is non-empty, call the tool again with the same query to fetch the rest.
3. **Intake.** Call `intake_papers` with the absolute project `path`. It scans `papers/` (including `_inbox/`) and writes one note card skeleton per paper into `notes/`. Existing cards are skipped, never overwritten.
4. **Fill the cards.** Read each card in `notes/`, consult the paper or its abstract, and replace the `<!-- 待智能体填写 -->` markers with: the research question, the method, the main conclusions, the limitations, and the evidence links. Keep the original metadata; correct it only when the source proves it wrong.
5. **Cluster and find gaps.** Write `gaps.md` in Chinese: group the literature into themes, list contradictions between studies, identify questions that no included work answers, and attach an evidence link (DOI, URL, or note path) to every claim. Distinguish "no evidence found in this reading list" from "nobody has done this". When the research-methodology skill is in use, grade each gap's evidence strength (强/中/弱/仅个案) from `quality-appraisal.md`.
6. **Generate innovation points systematically.** Before writing the 创新点 section, follow the **ariz-triz** skill: turn the evidenced gaps into TRIZ contradictions, walk the ARIZ-85C worksheet in `innovation/`, verify novelty with `search_literature`, and adopt only solutions that have a falsifiable hypothesis and a verification plan. Skip this step only when the reader explicitly wants a plain draft without systematic innovation.
7. **Draft the proposal.** Write `proposal-draft.md` in Chinese following the Chinese university opening-report structure: 选题背景与意义 / 国内外研究现状 / 研究内容与目标 / 研究方法与技术路线 / 创新点 / 进度安排 / 参考文献. Keep paper titles, key terms and method names in their original English. Every factual claim in 研究现状 and 创新点 must point back to `notes/`, `reading-list.md`, `innovation/solutions.md` or a DOI/URL; each 创新点 follows 矛盾 → 解法 → 差异证据 → 验证计划.

## Rules

- Analysis output is Chinese; titles, key terms and method names stay in English.
- Never claim a source says something it does not; cite the note card or link for each conclusion.
- Never delete or rewrite files under `papers/`; the tools never do either.
- `reading-list.md` is append-only and deduplicated by DOI, then normalized title.
- Do not call an LLM API from the extension and do not add credentials; the BSH agent is the only analysis engine.
- Report skipped items and failures from the tool results honestly.

## Output expectations

- `gaps.md`: theme clusters, contradictions, open questions, evidence links (with strength grades when research-methodology is in use).
- `innovation/`: TRIZ analysis, ARIZ worksheet and verified candidate solutions (when ariz-triz is in use).
- `proposal-draft.md`: the seven sections above, with a reference list drawn from the reading list.
