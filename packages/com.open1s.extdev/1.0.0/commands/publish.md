---
description: Prepare and publish a BSH extension release
---

Walk the reader through publishing an extension to the Git market.

1. Call `bump` with `patch`, `minor` or `major` and then edit the
   changelog line it wrote if the reader has a better sentence.
2. Call `check` with `smoke` true.
3. Call `package` to build the deterministic archive and report both digests.
4. Call `market` with `action` `entry`, show the JSON, then call it again
   with `action` `merge` once the reader agrees.
5. Remind the reader to commit the package directory and `index.json`, and to
   run `bsh ext market install <id>` afterwards.
