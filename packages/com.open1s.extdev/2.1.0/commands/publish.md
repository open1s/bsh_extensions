---
description: Prepare and publish a BSH extension release
---

Walk the reader through publishing an extension to the Git market.

1. Confirm the package has a docs/design.md or an equivalent design record.
   A package without one is a package whose capability list cannot be
   reviewed against its intent.
2. Call bump with patch, minor or major and then edit the changelog line it
   wrote if the reader has a better sentence.
3. Call check with smoke true. Do not continue with errors.
4. Call package to build the deterministic archive and report both digests.
5. Call market with action entry, show the JSON, then call it again with
   action merge once the reader agrees.
6. Remind the reader to commit the package directory and index.json, and to
   run bsh ext market install <id> afterwards.
7. Name every high-risk capability in the release note and link the grants
   the README documents.
