# Trinno

AI-assisted literature research workflow for graduate students and early-career researchers: search OpenAlex and arXiv (keyless) into a reading list, ingest local papers (PDF/BibTeX text extraction plus OpenAlex metadata completion) into per-paper note card skeletons, and scaffold a research-methodology workspace (protocol, PRISMA screening log, quality appraisal, reproducibility checklist) plus a TRIZ/ARIZ-85C innovation workspace. LLM analysis (gap analysis, systematic innovation, proposal drafting) is done by the BSH agent guided by the bundled skills, not by the tools.

Id: com.open1s.trinno  Version: 1.1.0  Runtime: process  Domain: research

## Status

Implemented against `requirement.md` (including its §12 v1.1 amendment): three tools (`search_literature`, `intake_papers`, `init_project`) and three skills (`research-workflow`, `research-methodology`, `ariz-triz`). No commands, panels, prompts or contexts.

## Tools

- `search_literature(path, query, limit=10, download=true, max_downloads=2)` — queries OpenAlex and arXiv, appends deduplicated entries to `reading-list.md`, downloads arXiv PDFs into `papers/_inbox/` at about one paper every 3 seconds. The number of PDFs per call is bounded (`max_downloads`, default 2) so the call returns inside the host time limit; the remaining hits are reported in `pending_downloads` and a repeated call resumes the download.
- `intake_papers(path, files?)` — extracts text and metadata from PDFs and BibTeX files, completes missing metadata from OpenAlex, and writes one non-overwriting note card skeleton per paper into `notes/`.
- `init_project(path)` — creates `papers/_inbox/`, `notes/`, `innovation/` and seven markdown skeletons (`protocol.md`, `screening-log.md`, `quality-appraisal.md`, `reproducibility.md`, `innovation/triz-analysis.md`, `innovation/ariz-worksheet.md`, `innovation/solutions.md`). Idempotent: existing files are skipped, never overwritten. No network.

## Skills

- `research-workflow` — entry point: search → intake → gap analysis → innovation → Chinese opening-report draft; routes to the two specialist skills below.
- `research-methodology` — preregistration-style protocol (PICO/SPIDER), reproducible search strings, PRISMA-style screening with an exclusion log, critical appraisal by study type (RoB 2 / ROBINS-I / CASP thinking), evidence-strength grading for gap claims, reproducibility checklist.
- `ariz-triz` — TRIZ toolbox (IFR, technical/physical contradictions, 40 inventive principles, separation principles, resource analysis, evolution trends) and the ARIZ-85C nine-part algorithm: turns evidenced gaps into verifiable innovation points and writes them into the proposal's 创新点 section.

## Install

    bsh ext install /Users/gaosg/Projects/hello/trinno
    bsh ext list
    bsh ext info com.open1s.trinno

## Capability grants

The package requests `process.execute`, `network.http`, `workspace.write`, `workspace.read`, `agent.tools.register` and `agent.skills.provide`. Explicit grants:

    bsh ext grant com.open1s.trinno process.execute --scope program:python3
    bsh ext grant com.open1s.trinno network.http --scope domain:api.openalex.org
    bsh ext grant com.open1s.trinno network.http --scope domain:export.arxiv.org
    bsh ext grant com.open1s.trinno network.http --scope domain:arxiv.org
    bsh ext grant com.open1s.trinno workspace.write --scope path:/Users/gaosg/Projects/hello

`workspace.read`, `agent.tools.register` and `agent.skills.provide` are low/medium-risk automatic capabilities.

## Optional dependency

PDF extraction uses `pypdf` when it is importable:

    python3 -m pip install pypdf

Without it the extension falls back to a standard-library PDF text extractor, which is less accurate but keeps intake working.

## Develop

    devkit validate .
    devkit lint .
    devkit check . smoke=true
    python3 -m unittest discover -s tests

## Layout

    extension.toml
    docs/design.md       implementation plan and acceptance gates
    server.py            process runtime: all three tools
    tools/               declared tools only
    skills/research-workflow/SKILL.md
    skills/research-methodology/SKILL.md
    skills/ariz-triz/SKILL.md
    tests/               dependency-free package and tool checks
