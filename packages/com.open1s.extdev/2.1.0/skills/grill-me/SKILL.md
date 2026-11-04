---
name: grill-me
description: Use when a request is ambiguous, underspecified or high-stakes and guessing would be expensive. Interrogates the reader one hard question at a time until the decision is unambiguous, then states the plan back before acting.
version: 1.0.0
---

# Grill me

Use this skill when the request leaves a material decision open: which of two
readings is meant, what scope is wanted, what happens to existing work, or
what the reader would consider a failure. Inspection answers discoverable
facts; grilling resolves the choices only the reader can make.

## The method

1. Inspect first. Read the files, run the checks, list the directory. Never
   ask a question the workspace can answer.
2. Ask one question at a time. Each question is self-contained: the context
   in one sentence, the options, and your recommendation with the reason.
   The reader can answer in one word.
3. Wait for the answer before the next question. Never batch questions, never
   answer for the reader, never re-ask what was already answered.
4. Cap the grill at five questions. If five do not settle it, state the
   remaining ambiguity and the safest default, and let the reader veto.
5. Play the answer back. Before acting, restate the decisions as a numbered
   list and the plan that follows from them. "Go" starts the work.

## Question shapes

- Fork: "A or B? I recommend A because …" — for two readings of the request.
- Scope: "Touch only X, or also Y?" — for blast radius.
- Confirmation: "You want me to change the code, not report on it — right?"
  — for terse requests that could be a question.
- Veto: "I plan to delete Z; any objection?" — for destructive or
  hard-to-reverse steps.

## Stop conditions

Stop grilling and start working when the reader says go, when no material
ambiguity remains, or when the next unknown is discoverable by inspection.
If the reader answers "you decide", pick the recommended option, say so in
one sentence, and proceed.
