# Production source sync — 2026-09-27

Read-only comparison against the running server source tree: `/opt/general-geo-eval`.

Business source matches the local working copy, ignoring CRLF and trailing whitespace. Local tests, Skill source and packaging tooling are included alongside production code. Runtime databases, credentials, uploads, temporary probes and private handoff notes are excluded. This commit does not redeploy production.
