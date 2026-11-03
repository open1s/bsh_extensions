---
description: Review a BSH extension package
---

Run the release gate for an extension package and explain what it found.

1. Call `check` with the absolute package path and `smoke` set to true.
2. Summarise errors first, then warnings, then notes, grouping by rule id.
3. For each error, name the file and the fix the finding suggests.
4. If the package is clean, say what the hash is and what would publish it.
