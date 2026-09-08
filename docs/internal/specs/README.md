# Internal specification register

This directory records implementation specifications and their lifecycle. The
root [`spec.md`](../../../spec.md) is the canonical active specification used by
the project workflow.

| ID | Title | Status | Canonical location | Planned archive |
| --- | --- | --- | --- | --- |
| SPEC-0001 | Initial IPFire Blocky add-on | Implemented | [`0001-initial-ipfire-blocky-addon.md`](0001-initial-ipfire-blocky-addon.md) | — |
| SPEC-0002 | CI-built IPFire packages and GitHub Releases | Ready for implementation | [`spec.md`](../../../spec.md) | `0002-ci-built-ipfire-packages-and-github-releases.md` |

## Lifecycle

1. Give each specification a monotonic `SPEC-NNNN` identifier.
2. Keep the active specification in root `spec.md` and register it here.
3. Record status, creation date, predecessors, and related research in the
   specification.
4. When its implementation is accepted, copy the final text into the planned
   numbered archive file and mark it **Implemented** in this table.
5. Archived specifications are immutable historical decisions. Amend or
   supersede them with a new numbered specification rather than rewriting
   history.
6. A new active spec links to any specification it amends or supersedes.

Allowed statuses are **Draft**, **Ready for implementation**, **Implemented**,
**Superseded**, and **Abandoned**.
