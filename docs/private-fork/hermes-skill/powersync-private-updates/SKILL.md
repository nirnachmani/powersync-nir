---
name: powersync-private-updates
description: "Use when maintaining the PowerSync Nir private fork against upstream."
version: 1.0.0
---

# PowerSync Nir private-fork upstream maintenance

## When to use

Use this skill in the dedicated `powersync-maintainer` Hermes profile on the
maintainer server to review, integrate, and validate upstream PowerSync changes
for the private `powersync-nir` fork.

## Scope and safety boundary

- Work only in the configured private-fork checkout and a disposable candidate
  worktree; never edit a deployed checkout directly.
- Confirm the target Git remote/repository is private before any push. Never
  publish to the public `upstream` remote.
- Preserve the architecture in `docs/private-fork/local-change-inventory.md`.
- Do not widen scope to Tesla, EVDC, OCPP, Zaptec, or other excluded backends.
- Apply relevance triage before tests or a candidate: reject battery-vendor changes unless they target Sigenergy, and reject provider changes unless they target Amber. Keep a vendor-neutral optimiser/site/infrastructure change only when it can affect Sigenergy, Amber, solar/site power flows, or private shared-EV operation.
- The updater's role is classification and private-fork compatibility, not upstream quality assurance. Rely on upstream developer tests for an unamended compatible update. Do not hunt for theoretical upstream bugs or re-test every upstream behavior; later upstream releases are the normal route for upstream bug fixes.
- Do not weaken, delete, bypass, or misreport a failing validator or test.
- Never expose secrets, tokens, device addresses, or captures in commits or
  reports.
- Deployment is a separate gated phase. Never deploy, reload/restart Home
  Assistant, or control a physical charger without separate authorisation and
  the server's approved deployment procedure.

## Required inputs

Before work, establish:

1. The private-fork checkout, branch, and private deploy remote.
2. A clean worktree or explicitly recorded local changes.
3. The last reviewed upstream SHA/tag and target upstream range.
4. The current local-change inventory.
5. A working Python environment for the fork.
6. A schema-versioned `maintainer_ledger.py` state file. Create it only from an
   explicit baseline with a migration boundary/reference. For old v1418 state,
   use the CLI's safe `migrate --legacy-state` command with a matching baseline;
   do not create fictional historical commit outcomes.

## Required gates

Run from the private-fork root before and after every candidate integration:

```bash
python scripts/private-fork/validate_local_architecture.py
scripts/private-fork/run_private_tests.sh
```

The focused runner includes Android-contract and private shared-loadpoint/
reconciliation tests. Use `--broader` only for release validation or when the
affected subsystem lacks focused coverage; compare its stable failure IDs to
the starting revision and report the difference. Do not repeat broad runs for
small isolated ports or create speculative tests for unconfigured vendors.

## No-paywall upstream classification

- **Never wholesale rebase or merge upstream 1404+**. Treat each upstream
  change as a source-level classification and review its changed paths,
  imports, symbols, and tests before proposing a candidate.
- Reject every `custom_components/power_sync/licensing/**` file and any
  licensing import, optimiser-access entitlement/permission guard, entitlement
  pairing UI, hosted `api.powersync.cc/ha-license` dependency, subscription UI,
  entitlement storage, command/service fence, or licence-recovery wrapper.
- Do not port `subscription_required`, `LicensedBatteryController`,
  `optimizer_access`, or an optimiser entitlement pairing flow. These are
  concrete paywall symbols, not ordinary provider authentication mechanics.
- A hunk coupled to licensing is **incompatible until disentangled**. Do not
  resolve it by importing a guard, a recovery path, or an access-status UI.
- Port an eligible optimiser fix only as manually reviewed, minimal hunks into
  the existing no-paywall optimiser; never use a wholesale 1404+ integration
  as a substitute for hunk review.
- Preserve upstream source attribution and licence notices for every adapted
  hunk, and retain this private fork's noncommercial scope.
- Before a candidate can be proposed, run the current source-only gates:
  `python scripts/private-fork/validate_local_architecture.py` and
  `scripts/private-fork/run_private_tests.sh`.

ChatGPT plan-explanation sign-in is explicitly distinct from optimiser
licensing. It is permitted only as a separately approved AI feature after a
dedicated security and API-contract review; it must not import optimiser
entitlement, permission, command-fencing, or hosted optimiser-access code.

## Workflow

1. Record `git status --short`, private starting SHA, last reviewed upstream
   SHA/tag, and target upstream SHA/tag.
2. Read `docs/private-fork/local-change-inventory.md` and
   `docs/private-fork/powersync-private-updates-reference.md`.
3. Fetch and compare the explicit upstream range deterministically using the
   repository tools; identify changed paths, symbols, tests, and release notes.
4. Apply this relevance and interaction screen before the no-paywall classification:
   - Is it relevant to Amber, Sigenergy, solar/site flows, private shared EVs,
     or an explicitly approved optional feature? If not, record `irrelevant to
     configured setup` with the specific unavailable vendor/feature reason and
     reject it without a candidate.
   - Does it plausibly interact with private two-EV or external-session code?
     If not, port it minimally without a private quality audit or new tests.
   - If it does interact, decide whether private behavior remains compatible.
     If the choice is uncertain or trades private functionality against another
     required outcome, stop and ask the user before implementation.
   Then classify the remaining delta as one of:
   - **No overlap:** no private modules/direct tests touched.
   - **Mechanical overlap:** same file, separable hunks.
   - **Compatible semantic overlap:** private invariants can be preserved with
     test-backed adaptation.
   - **Redundant:** the private fork already covers the upstream behaviour.
   - **Incompatible:** private behavioural invariants cannot be preserved
     safely.
5. Use `scripts/private-fork/candidate_worktree.py prepare` with explicit
   private repo, candidate root, source ref, upstream target ref, and manifest.
   It requires a clean private source and a policy-approved private GitHub
   `origin`, creates only a detached disposable worktree, and records that no
   integration occurred. Use its separate `cleanup` command only with the exact
   registered path beneath the candidate root.
6. Only for an exact `no_overlap` classifier result, use
   `scripts/private-fork/integrate_candidate.py` with the unchanged manifest,
   exact candidate path, target SHA, classification, and report path. It merges
   locally only in the registered candidate, runs every required gate, and
   commits only there after they pass. It must never publish, deploy, or control
   infrastructure.
7. For every overlap classification, stop with a report requiring
   compatible-resolution work; do not attempt an automatic merge.
8. For redundant changes, record the upstream SHA and equivalence rationale;
   retain the private implementation.
9. For incompatible changes or failed gates, retain the candidate untouched and
   report the precise conflict/failure. Do not push it as a release or deploy.

## Proportionate testing

- Relevant no-interaction hunk: classify, minimally port, then run the
  architecture validator and private compatibility gate once per update cycle.
  Do not add tests merely to re-prove upstream behavior.
- Relevant overlapping hunk that needs no amendment: port it and run the same
  cycle gate; do not turn it into an upstream quality review.
- Amended private-overlap hunk: add only the smallest interaction regression
  required to prove the amendment. Use a semantic review only where the
  amendment changes private behavior. Do not reject an important upstream EV
  or external-session fix merely because upstream's identity model differs:
  adapt it through the private logical-profile selector, canonical physical
  loadpoint, lease, session, and reconciler seams when that preserves the
  intended bug-fix outcome. Ask the user only if those requirements conflict
  or the correct private outcome is genuinely uncertain.
- Process upstream commits strictly oldest to newest. Every commit must reach a
  terminal outcome before advancing the processing checkpoint: `ported`,
  `amended`, `rejected`, or `admin/no-port`. Use
  `scripts/private-fork/maintainer_ledger.py next` to obtain the sole permitted
  commit, then `record --upstream-version <version>` it with reason and
  applicable private commit SHA(s).
  Its atomic write advances the checkpoint with the durable entry; it rejects
  `deferred`, missing mandatory details, unknown SHAs, and out-of-order work.
  If a commit needs user input, do not record it: stop the cycle at that commit
  and do not advance the checkpoint; resume it before processing later commits.
  Use `summary` as the end-of-cycle cron JSON payload. This naturally brings
  any prerequisite in before a later dependent fix.
- Broad testing is reserved for final release handoff or a clear regression
  discovered during an amendment. Never multiply review or broad test runs for
  irrelevant, theoretical, or unavailable-vendor scenarios.

## Private invariants

Keep these true:

- Shared profile selection fails closed; there is no first-profile fallback.
- Generic and Sigenergy EVAC physical start/stop/current commands pass the
  shared guard and physical ownership path.
- Reconciliation observes/categorises state; it does not replace charging-mode
  calculations.
- Existing Solar Surplus, Smart Schedule, Scheduled Charging, and Price-Level
  decisions remain authoritative.
- Shared physical sessions, leases, and runtime keys preserve logical-profile
  attribution.
- Android existing routes and payload fields remain compatible; shared
  diagnostics is an optional separate endpoint.

## Report

Use this exact structure:

```text
Scope: <private revision and upstream range>
Start state: <private SHA>; working tree <clean/recorded changes>
Classification: <no overlap/mechanical/compatible/redundant/incompatible>
Changed: <files and one-line purpose>
Gates:
- validate_local_architecture.py: <pass/fail>
- run_private_tests.sh: <pass/fail>
- broader suite, if requested: <pass/fail; all failures counted>
Commit/candidate: <SHA or retained worktree>
Deployment: <not attempted / separately authorised result>
Blockers / follow-up: <none or factual items>
```

## End-of-cycle update report

At the end of each upstream-update cycle, provide a brief table covering every
considered upstream update:

| Update | Outcome | Brief reason / adjustment |
|---|---|---|
| `<SHA or feature>` | ported / amended / rejected / admin/no-port | One sentence. For `irrelevant to configured setup`, name the unavailable vendor or unused feature; for `admin/no-port`, name release/version/documentation bookkeeping. |

For an uncertain overlap or a choice between private functionality and another
required outcome, do not decide silently: state the alternatives in one or two
sentences and ask the user for a preference.

Send this final report by email through the configured Resend MCP. Reuse the
sender and recipient defaults from the server's `ha-update` skill reference;
do not expose credentials or duplicate them into this skill. If email delivery
fails, retain the local report and state the delivery failure in the cron output.

## Deployment handoff

A maintenance integration is not deployment proof. Deployment needs separate
authorisation, a fresh backup, a manual stop capability, staging prerequisites,
and post-deployment verification. If any are absent, report deployment as
deferred and continue only with safe source-maintenance work.
