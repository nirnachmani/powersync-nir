# Manual re-review of earlier AI rejections

The sequential updater ledger already records the following upstream commits as `rejected` and remains an immutable historical account. This review adds the compatible changes on the current private feature branch without rewinding or fabricating ledger entries. Future runs continue from the existing checkpoint; this file documents the later corrective private port.

| Upstream SHA | Earlier outcome | Independent review and current disposition |
|---|---|---|
| `251e89cb` | Rejected as unapproved AI | ChatGPT plan-explanation sign-in was already approved. Ported its optional host-ID storage change: an unused connection need not create credentials at startup, while first sign-in must durably save identity before provider contact. Upstream regression tests included. |
| `e6d56cc9` | Rejected as unapproved AI | Ported selective ChatGPT credential loading at setup and on provider selection. Unselected storage is not opened at startup; switching to ChatGPT restores credentials or returns a storage error. Upstream tests included. |
| `59769e2e` | Rejected as unapproved AI | Ported configurable local OpenAI-compatible explanation timeout, bounded 30–600 seconds (120 default), with one budget across schema retry and a matching browser watchdog. It is not an optimiser entitlement path. Upstream backend and frontend regressions included; `docs/wiki-configuration-map.json` does not exist in this private checkout and is not required by the integration. |

No upstream licensing manager, optimiser entitlement, hosted access, new AI credentials, or user secrets are imported. None of these corrections changes the last-processed upstream SHA in the ordered ledger; the new private commit/release is the audit link for their implementation.
