---
description: Review a BSH extension package against its blueprint
---

Run the release gate for an extension package and explain what it found.

1. Call check with the absolute package path and smoke set to true.
2. Summarise errors first, then warnings, then notes, grouping by rule id.
3. For each error, name the file and the fix the finding suggests.
4. If docs/design.md exists, call design again with the package path and the
   blueprint's domain. Compare the package with the blueprint: missing
   contributions, missing capabilities, missing tool files and high-risk
   capabilities the blueprint did not justify. Report the gaps separately
   from the validator findings.
5. If the package is clean, say what the hash is and what would publish it.
   Do not call a package clean if the blueprint comparison is in-progress.
