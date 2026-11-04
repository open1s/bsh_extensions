---
name: extdev-ship
description: Use when a BSH extension is ready to review, version, package or publish to the Git market, or when a release gate or market index check fails. Covers check, bump, package, market, signing and the release record.
version: 1.1.0
---

# Ship a BSH extension

Use this skill when the package validates and the reader wants a release.

## Gate before versioning

1. check with smoke=true: validation, lint, hash, file count and a real call
   per declared tool.
2. design with the package path and the blueprint domain: the package should
   match the blueprint or the differences should be explained.
3. The package has README.md, LICENSE, CHANGELOG.md and a tests directory
   that runs without the host.
4. Every high-risk capability is named in the README with its grant.

Do not bump a version to make a gate pass. Fix the finding.

## Version and archive

- bump with patch for a fix, minor for a new surface, major for a breaking
  removal or rename. Edit the changelog sentence it writes.
- package builds a deterministic .tar.gz and reports the package hash and the
  archive digest. Two builds of the same bytes produce the same digest.
- Remove __pycache__, build output and scratch files before hashing. They are
  hashed like any other file and make the release depend on who ran the
  tests.

## Market entry

1. market with action entry, show the JSON to the reader.
2. market with action merge once they agree. It writes the entry and keeps
   index.json sorted by id and version.
3. market with action verify. Every entry must match its directory and hash.
4. The package lives at packages/<id>/<version>/ and the index points at it.
5. Commit the package and index.json in one change. Users then run
   bsh ext market install <id>.

## Signing

- keygen creates a publisher key pair; sign writes package.sig over id,
  version and the package hash; trust records the publisher key.
- A signature proves publisher identity and package integrity. It does not
  replace capability review.
- Never commit a private key.

## Release note

Name what changed, the new surfaces, the capabilities the release asks for
and any migration. If the id or a contribution id was renamed, say so: it
breaks references in prompts, skills and history.
