# Extension design: Trinno

> AI-assisted literature research workflow for graduate students and early-career researchers: search OpenAlex and arXiv (keyless) into a reading list, ingest local papers (PDF/BibTeX text extraction plus OpenAlex metadata completion) into per-paper note card skeletons in a project folder; LLM analysis (gap analysis, proposal drafting) is done by the BSH agent guided by the bundled research-workflow skill, not by the tools.

Id: `com.open1s.trinno`  |  Version: 1.1.0  |  Runtime: `process`

This document follows `requirement.md` (the confirmed specification, including its §12 v1.1 amendment). It records the implemented surface; the checklist is updated as each item lands.

## Domain fit

| Field | Value |
|---|---|
| Domain | research |
| Confidence | high |
| Matched signals | search, extract, research |
| Runtime | process |
| Why this changes the design | HTTP fetching, PDF text extraction and file maintenance need code. A declarative runtime makes no network requests. |

## Architecture decisions

| Decision | Value |
|---|---|
| LLM provider | The BSH agent performs all analysis; the extension does deterministic I/O only. |
| Credentials | None. No API key, no secret capability, no LLM cost. |
| Sources | OpenAlex and arXiv, both keyless. |
| Language | Python 3 standard library; `pypdf` is used for PDF text extraction when installed, and a standard-library fallback extractor keeps intake working without it. |

## Contributions (v1.1 exact scope)

**3 tools + 3 skills**: no command, panel, prompt or context.

| Kind | Id | File | Capability | Purpose |
|---|---|---|---|---|
| tool | search_literature | tools/search_literature.json | network.http, workspace.write, workspace.read, process.execute | Search OpenAlex + arXiv, append to `reading-list.md`, download arXiv PDFs into `papers/_inbox/`. |
| tool | intake_papers | tools/intake_papers.json | network.http, workspace.write, workspace.read, process.execute | Extract PDF/BibTeX metadata, complete it from OpenAlex, write note card skeletons into `notes/`. |
| tool | init_project | tools/init_project.json | workspace.write, workspace.read, process.execute | Create the project skeleton: directories plus methodology and TRIZ/ARIZ markdown skeletons; idempotent, never overwrites, no network. |
| skill | research-workflow | skills/research-workflow/SKILL.md | agent.skills.provide | Entry point: search → intake → gap analysis → innovation → proposal drafting; routes to the two specialist skills. |
| skill | research-methodology | skills/research-methodology/SKILL.md | agent.skills.provide | Protocol (PICO/SPIDER) → reproducible search → PRISMA screening → critical appraisal (RoB 2 / ROBINS-I / CASP thinking) → evidence grading → reproducibility checklist. |
| skill | ariz-triz | skills/ariz-triz/SKILL.md | agent.skills.provide | TRIZ toolbox (IFR, contradictions, 40 principles, separation, resources, trends) + ARIZ-85C nine-part walk; gaps → verifiable innovation points → proposal 创新点. |

`analyze_gaps`, `draft_proposal` and every ARIZ reasoning step are deliberately not tools: they are agent workflow steps, so no empty-shell tools are shipped.

## Tool surface

### search_literature

- File: `tools/search_literature.json`
- Input: `path` (absolute project folder), `query`, `limit` (1–50, default 10), `download` (default true), `max_downloads` (0–50, default 2)
- Returns: `{path, added, skipped, downloaded, sources, results, reading_list, skipped_entries, downloaded_files, pending_downloads, failures, timestamp}`
- Runs: OpenAlex `works?search=`, arXiv Atom `api/query`, then an append-only, deduplicated write to `reading-list.md`; arXiv PDFs are downloaded serially (about 3 s per paper) into `papers/_inbox/`. The download count and wall-clock time are bounded per call, so the tool returns inside the host time limit; unfinished hits are reported as `pending_downloads` and the next call resumes them.

### intake_papers

- File: `tools/intake_papers.json`
- Input: `path` (absolute project folder), optional `files` (absolute PDF/`.bib` paths; default scans `papers/` including `_inbox/`)
- Returns: `{path, processed, skipped, notes, failures, processed_files, skipped_files}`
- Runs: PDF text extraction (pypdf, standard-library fallback), BibTeX field parsing, OpenAlex metadata completion by title, then one non-overwriting markdown card per paper in `notes/`.

### init_project (v1.1)

- File: `tools/init_project.json`
- Input: `path` (absolute, existing project folder)
- Returns: `{path, created, skipped, directories, failures}`
- Runs: creates `papers/`, `papers/_inbox/`, `notes/`, `innovation/`, then exclusively creates (`open("x")`) seven skeletons: `protocol.md`, `screening-log.md`, `quality-appraisal.md`, `reproducibility.md`, `innovation/triz-analysis.md`, `innovation/ariz-worksheet.md`, `innovation/solutions.md`. Existing files are skipped and reported; the call is idempotent and makes no network request.

## Directory convention

```
<project>/
├── papers/            # user originals, read-only
│   └── _inbox/        # machine downloads only
├── notes/             # intake_papers note cards
├── reading-list.md    # search_literature output, append-only
├── gaps.md            # agent output
├── proposal-draft.md  # agent output
├── protocol.md            # init_project skeleton, agent fills (PICO/SPIDER, criteria, queries)
├── screening-log.md       # init_project skeleton, agent fills (PRISMA flow + decisions)
├── quality-appraisal.md   # init_project skeleton, agent fills (per-paper appraisal, grades)
├── reproducibility.md     # init_project skeleton, agent fills (checklist)
└── innovation/            # init_project skeletons, agent fills via ariz-triz
    ├── triz-analysis.md   # system, IFR, contradictions, resources, trends
    ├── ariz-worksheet.md  # ARIZ-85C nine parts + backtrack log
    └── solutions.md       # candidates, verification plans, write-back log
```

## Capabilities and grants

| Capability | Risk | Why | Grant |
|---|---|---|---|
| process.execute | critical | the process runtime starts the tools | `bsh ext grant com.open1s.trinno process.execute --scope program:python3` |
| network.http | high | OpenAlex, arXiv metadata and arXiv PDF downloads | `bsh ext grant com.open1s.trinno network.http --scope domain:api.openalex.org`, `... --scope domain:export.arxiv.org`, `... --scope domain:arxiv.org` |
| workspace.write | high | reading list, downloaded PDFs, note cards | `bsh ext grant com.open1s.trinno workspace.write --scope path:<absolute-workspace-path>` |
| workspace.read | low | reads papers and the existing reading list | automatic |
| agent.tools.register | low | exposes the two tools | automatic |
| agent.skills.provide | medium | ships the research workflow | automatic |

## Safety rules

1. `papers/` outside `_inbox/` is read-only; originals are never added, changed or deleted.
2. Network requests carry metadata only: query, title, DOI, arXiv id. Notes, drafts and PDF text are never uploaded.
3. `reading-list.md` is append-only and deduplicated by DOI, then normalized title; hand-written annotations are preserved.
4. Downloads land only in `papers/_inbox/`; existing files are never overwritten.
5. The package contains no delete operation.
6. Bounds: 20 s HTTP timeout, at most 3 redirects, 4 MiB API response limit, 64 MiB PDF limit, 200 000 extracted characters, arXiv serial delay of about 3 s, at most 2 PDF downloads and 90 s of download time per call; skipped entries, pending downloads and failures are reported.
7. The path argument is always named `path`; URLs are constructed internally from a fixed allow-list of hosts (`api.openalex.org`, `export.arxiv.org`, `arxiv.org`).
8. Writes stay inside the granted workspace path.

## Build order and status

v1:

1. [x] Scaffold package skeleton.
2. [x] Implement `search_literature`.
3. [x] Implement `intake_papers`.
4. [x] Write the `research-workflow` skill.
5. [x] Trim the manifest to 2 tools + 1 skill and record the safety rules.
6. [x] `validate` + `lint` + `check` (with smoke) and the unit tests.
7. [x] Publish the grant command list and install steps in README.md.

v1.1 (requirement.md §12):

8. [x] Amend requirement.md with the v1.1 scope before touching the package.
9. [x] Implement `init_project` (idempotent skeletons, no network, no overwrite).
10. [x] Write the `research-methodology` skill.
11. [x] Write the `ariz-triz` skill.
12. [x] Route `research-workflow` into the two specialist skills.
13. [x] Update the manifest to 3 tools + 3 skills; bump to 1.1.0.
14. [x] Extend the unit tests; `validate` + `lint` + `check` (with smoke) green.

## Acceptance gates

- [x] `papers/` (outside `_inbox/`) is never modified or deleted.
- [x] `reading-list.md` only grows and repeated searches do not duplicate entries.
- [x] Downloaded PDFs land only in `papers/_inbox/`.
- [x] Network requests only reach api.openalex.org / export.arxiv.org / arxiv.org.
- [x] Notes and drafts never appear in a network request.
- [x] No delete path exists in the code.
- [x] `validate`, `lint`, `check --smoke` and the unit tests pass.
- [x] `init_project` is idempotent: a second call creates nothing and never overwrites a filled-in skeleton.
- [x] `init_project` makes no network request.
