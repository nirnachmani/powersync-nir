---
name: powersync-private-updates
description: "Use when maintaining the PowerSync Nir fork against upstream."
version: 1.0.6
---

# PowerSync Nir fork upstream maintenance

## When to use

Use this skill in the dedicated `powersync-maintainer` Hermes profile on the
maintainer server to review, integrate, and validate upstream PowerSync changes
for the `nirnachmani/powersync-nir` fork.

## Scope and safety boundary

- Work only in the configured fork checkout and a disposable candidate
  worktree; never edit a deployed checkout directly.
- Confirm both fetch and push URLs of `origin` target exactly
  `nirnachmani/powersync-nir` before any push, independent of visibility. Never
  publish to the `upstream` remote, change repository visibility, or force-push.
- Preserve the architecture in `docs/private-fork/local-change-inventory.md`.
- Do not widen scope to Tesla, EVDC, OCPP, Zaptec, or other excluded backends.
- Apply relevance triage before tests or a candidate: reject battery-vendor changes unless they target Sigenergy, and reject provider changes unless they target Amber. Keep a vendor-neutral optimiser/site/infrastructure change only when it can affect Sigenergy, Amber, solar/site power flows, or private shared-EV operation.
- The updater's job is to carry applicable upstream behavior forward, not to
  reassess upstream's product choices or perform upstream quality assurance.
  When a supported feature was inherited unchanged, include upstream fixes,
  enhancements, settings, new defaults, and upgrade behavior as upstream
  implements them—even if the default changes previously active behavior.
  Do not invent an upgrade migration or solicit the user's preference merely
  to retain the previous upstream behavior. Ask only about a concrete conflict
  with this fork's intentional changes that cannot be safely adapted (or a
  genuinely unresolved fork-specific security boundary); exclude paywall
  code outright. Rely on upstream developer tests for an unamended compatible
  update; do not hunt for theoretical upstream bugs or re-test every upstream
  behavior. Later upstream releases are the normal route for upstream fixes.
- Do not weaken, delete, bypass, or misreport a failing validator or test.
- Never expose secrets, tokens, device addresses, or captures in commits or
  reports.
- Deployment is a separate gated phase. Never deploy, reload/restart Home
  Assistant, or control a physical charger without separate authorisation and
  the server's approved deployment procedure.

## Required inputs

Before work, establish:

1. The fork checkout, branch, and approved `origin` fetch/push URLs.
2. A clean worktree or explicitly recorded local changes.
3. The last reviewed upstream SHA/tag and target upstream range.
4. The current local-change inventory.
5. A working Python environment for the fork.
6. A schema-versioned `maintainer_ledger.py` state file at a distinct
   `maintainer_ledger.json` path. For old v1418 `upstream.json`, retain that
   legacy file as read-only input/backup and use the CLI's safe `migrate
   --legacy-state` command with a matching baseline; do not create fictional
   historical commit outcomes or let `maintainer_cycle.py` overwrite the ledger.

## Skill source of truth and synchronisation

The tracked `docs/private-fork/hermes-skill/powersync-private-updates/SKILL.md`
on the approved GitHub fork is canonical. When discussing what the maintainer
*currently* does, inspect the copy installed in its named server profile; a
missing local profile says nothing about that server. Compare the tracked
GitHub file, the server checkout's tracked file, and the profile's installed
`skills/powersync-private-updates/SKILL.md` by content, not mtime alone.

After an authorised policy change, reconcile useful rules into the tracked
source, commit/publish it, install that version to the named profile with the
repository installer, and verify exact content equality. A repository push
alone does not update a profile-local skill; a profile-local `skill_manage`
change does not update GitHub. Do not edit another profile without explicit
authorisation.

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
- Classify licensing-adjacent commits **hunk by hunk**, not by filename or
  subject alone. If a relevant bug fix or enhancement has an independently
  useful non-entitlement path, port or minimally amend that behavior without
  the licence gate. Reject only entitlement-only work or behavior genuinely
  inseparable from it; adapt private EV overlaps through existing guards.
- Port an eligible optimiser fix only as manually reviewed, minimal hunks into
  the existing no-paywall optimiser; never use a wholesale 1404+ integration
  as a substitute for hunk review.
- Preserve upstream source attribution and licence notices for every adapted
  hunk, and retain this fork's noncommercial scope.
- Before a candidate can be proposed, run the current source-only gates:
  `python scripts/private-fork/validate_local_architecture.py` and
  `scripts/private-fork/run_private_tests.sh`.

ChatGPT plan-explanation sign-in has **already been authorised and reviewed**
as distinct from optimiser licensing. Treat follow-up ChatGPT registration,
credential-storage, startup and explanation-API fixes, as well as relevant
enhancements to existing AI explanation providers, as normal upstream candidates;
include existing providers even if they are not currently selected, and never
reject them for lacking a second blanket AI approval. Follow upstream changes
to provider authentication and API contracts when they do not conflict with
this fork's intentional credential-handling boundaries; ask only if such a
specific fork boundary cannot be preserved. Keep optimiser entitlement,
permission, command-fencing and hosted-access code out.

## Workflow

1. Record `git status --short`, private starting SHA, last reviewed upstream
   SHA/tag, and target upstream SHA/tag. Fetch the approved `origin` before
   preparing candidates. If its feature branch is ahead, verify those commits'
   provenance and relation to the ledger before fast-forwarding a clean source.
   If release `main` has separate published private commits, reconcile them in
   a detached candidate, preserve their behavior, and rerun both gates before
   advancing the feature branch and fast-forwarding `main`. Never overwrite
   published private fixes with an older feature tip.
2. Read `docs/private-fork/local-change-inventory.md` and
   `docs/private-fork/powersync-private-updates-reference.md`.
3. Fetch and compare the explicit upstream range deterministically using the
   repository tools; identify changed paths, symbols, tests, and release notes.
   For **each relevant upstream hunk**, compare the same path/function with the
   fork's current implementation before copying or discarding it. A difference
   from upstream is not an invitation to restore upstream: first identify why
   the fork diverged (inventory, fork commits/tests, and dependent callers).
   Treat the capacity source of truth, physical charger entity projection and
   fail-closed shared command path as deliberate semantic differences. If the
   reason cannot be established, do not assume equivalence or overwrite it;
   stop at that ledger commit for review. The structural classifier is only a
   triage signal and cannot prove that an apparently no-overlap hunk is safe.
   When a port exposes or changes a setting/UI that activates an existing
   side-effecting path, trace that path through its API/options, scheduler or
   action, identity lookup, and final install/physical command—even when the
   downstream file is unchanged upstream. Check the fork-specific boundary at
   each seam, not upstream's general product design. In particular, scheduled
   updates must target only the verified `nirnachmani/powersync-nir` HACS
   repository (ID and current slug) and fork release tags; an old upstream HACS
   entity or upstream release must fail closed. Pin the validated tag at the
   `update.install` write seam rather than trusting HACS's mutable latest value,
   and verify restart intent against a newer pending release. Add one focused
   regression for a wrong target and the physical/install boundary.
4. Apply outcome-first relevance and interaction triage **before preparing a
   candidate or delegating an adaptation**. For each changed hunk, identify
   what upstream actually enables, including its validation, backend gates and
   tests; then ask whether that *outcome* benefits a supported fork path, an
   approved optional capability, or a relevant shared prerequisite. A shared
   function, vendor-neutral subject or earlier related port does not extend a
   vendor-gated outcome to Generic/EVAC. If the outcome is unavailable here,
   reject it without inventing a supported-backend implementation or asking
   the user to choose one. An identically named fork function is not required
   for a genuinely applicable new capability. In particular:
   - Is it relevant to Amber, Sigenergy, solar/site flows, private shared EVs,
     an existing AI explanation provider, or another explicitly approved optional
     feature? Existing AI providers are in scope even if presently unselected.
     Otherwise record the specific unavailable vendor or feature as
     `irrelevant to configured setup` and reject without a candidate.
   - If the fork already achieves the outcome, record equivalent private
     coverage instead of copying code.
   - If an upstream change touches code retained from upstream without a
     fork-introduced behavioral change, port the applicable upstream behavior,
     including upstream option defaults on upgrades. Do not stop to ask whether
     the upstream default or feature design is desirable. A change affecting
     existing installations is not itself a fork-specific conflict.
   - Does it plausibly interact with private two-EV, external-session or other
     documented fork-introduced behavior? If not, port the relevant behavior
     minimally without a private quality audit or new tests. If it does, adapt
     the upstream outcome to those private invariants, excluding entitlement
     code, with a targeted interaction regression.
   - Ask the user only if a specific intentional fork divergence (including
     no-paywall or private credential boundaries) makes the upstream outcome
     impossible to preserve through a safe amendment. State the exact fork
     change and conflicting upstream hunk. A failed gate stops publication
     for diagnosis; it is not a referendum on upstream's product decision.
     Do not reject a relevant fix merely because upstream implements it
     differently.
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
   It requires a clean fork source and a policy-approved GitHub
   `origin`, creates only a detached disposable worktree, and records that no
   integration occurred. Use its separate `cleanup` command only with the exact
   registered path beneath the candidate root.
6. Only for an exact `no_overlap` classifier result, use
   `scripts/private-fork/integrate_candidate.py` with the unchanged manifest,
   exact candidate path, target SHA, classification, and report path. It merges
   locally only in the registered candidate, runs every required gate, and
   commits only there after they pass. It must never publish, deploy, or control
   infrastructure.
7. Only after an upstream outcome passes relevance triage, make the smallest
   compatible amendment for an overlapping hunk with one targeted interaction
   regression. A file overlap alone is not applicability; stop only when the
   applicable outcome conflicts with a concrete private-behaviour/security
   invariant that cannot be safely amended.
8. For redundant changes, record the upstream SHA and equivalence rationale;
   retain the private implementation.
9. A failed gate blocks publication, not investigation. Preserve the candidate
   and diagnose the failure against the starting revision, then independently
   correct the adaptation or its specifically reviewed test expectations within
   the existing functional scope. Rerun the relevant check and required gates;
   continue through the pinned target once they pass. Never bypass a failure.
   If an optimiser source fingerprint rejects an intended change, review its
   actual diff and protected invariants, extend only the exact approved lineage,
   and retain mutation-rejection coverage. Never blindly refresh a fingerprint
   or weaken a validator. The failure itself is not evidence of a product bug.
   Act autonomously on ordinary coding, test, compatibility, and tooling issues;
   do not ask the user to approve an implementation detail or resume the run.

## Proportionate testing

- Relevant no-interaction hunk: classify, minimally port, then run the
  architecture validator and private compatibility gate once per update cycle.
  Do not add tests merely to re-prove upstream behavior.
- Relevant overlapping hunk that needs no amendment: port it and run the same
  cycle gate; do not turn it into an upstream quality review.
- Amended private-overlap hunk: add only the smallest interaction regression
  required to prove the amendment. Use a semantic review only where the
  amendment changes private behavior. First establish that the upstream EV or
  external-session fix actually affects a supported path; vendor-specific
  identity checks and tests are not a mandate to add that behavior to another
  backend. For an applicable fix, do not reject it merely because upstream's
  identity model differs: adapt it through the private logical-profile
  selector, canonical physical loadpoint, lease, session, and reconciler seams
  when that preserves the intended bug-fix outcome. Ask the user only if that
  applicable outcome conflicts with private invariants or its private outcome
  is genuinely uncertain.
- Process upstream commits strictly oldest to newest. Every commit must reach a
  terminal outcome before advancing the processing checkpoint: `ported`,
  `amended`, `rejected`, or `admin/no-port`. Use
  `scripts/private-fork/maintainer_ledger.py next --target refs/remotes/upstream/main`
  to obtain the sole permitted commit, then
  `record --target refs/remotes/upstream/main --upstream-version <version>` it with reason and
  applicable private commit SHA(s). Every private SHA must be reachable from
  the intended private ref; `record` defaults to
  `--private-ref feature/shared-logical-evs`, and an explicit `--private-ref`
  is required when a different intended branch is used.
  At upstream merge branches, use the ledger CLI's `next` result rather than
  first-parent log order or a simple `checkpoint..target` range: independent
  side-branch commits must each be recorded once. The CLI enumerates from its
  migration baseline and filters already-recorded SHAs; a simple range can
  replay sibling commits after the checkpoint crosses branches.
  Its atomic write advances the checkpoint with the durable entry; it rejects
  `deferred`, missing mandatory details, unknown or wrong-branch private SHAs,
  and out-of-order work.
  If a commit needs user input, do not record it: stop the cycle at that commit
  and do not advance the checkpoint; resume it before processing later commits.
  Spell the upstream remote ref in full: `upstream/main` is ambiguous when an
  `origin/upstream/main` ref also exists and can silently select stale history.
  Use `summary` as the end-of-cycle cron JSON payload. This naturally brings
  any prerequisite in before a later dependent fix.
- **Completion gate: never end on a backlog.** Pin the fetched upstream target
  for this cycle and continue calling ledger `next` and recording each terminal
  outcome until `next` reports no remaining commits through that target. The
  number of commits, a convenient version boundary, three completed ports, or
  a desire to send a progress email is **not** a blocker or stopping point.
  Do not voluntarily wrap up while turns/time remain. Do not run final gates,
  write an end-of-cycle report, or publish until the target is exhausted.
  After final gates, recheck the ledger summary/`next`; a successful test run
  does not convert unfinished work into a finished cycle.
- Stop to request a user choice only when a concrete, investigated conflict
  requires choosing between materially different outcomes affecting significant user-facing functionality,
  architecture, activation limits, or a protected security boundary. Explain
  the actual consequence and alternatives; ordinary upstream product decisions
  already covered by policy are not such a choice. Do not claim a safety
  failure alone requires a choice. A genuinely unrecoverable missing access,
  technical failure, or enforced resource limit is an operational interruption,
  not a product decision: exhaust reasonable diagnosis and safe alternatives,
  preserve the candidate and checkpoint, and report evidence and next action.
  Never publish with a failing gate or fabricate success. Record the exact
  stopping commit and evidence. For a real runtime
  limit, save the durable checkpoint and next SHA, identify the limit, and
  arrange immediate continuation after the current claim releases rather than
  waiting for the next regular schedule; if no safe handoff can be arranged,
  report an operational interruption requiring continuation, not a fork
  conflict or a request for a product decision. Never mark `complete: true`,
  `release_published: true`, or claim the cycle finished while `next` is
  non-null. A cron execution marked `completed/ok` only means the agent
  returned, not that the maintenance objective was met.
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

## Review a stopped or incomplete run

1. Read the latest cron execution/output and saved maintenance report in the
   **named server profile**, not just the email; separate scheduler outcome
   from the report's `complete` and `release_published` fields.
2. Read the session `end_reason` and actual call/turn count against the
   configured cap. Do not infer timeout from a large backlog or `ok` from a
   normally returned session; if the trace gives no reason for stopping, say
   so instead of inventing one.
3. Run the ledger CLI's `next` against `refs/remotes/upstream/main`, compare
   its checkpoint/remaining count with the reported target, and inspect local
   versus remote feature/main heads plus worktree status. Distinguish local
   tested commits from pushed changes, a GitHub release, and HA deployment.
4. Name a **blocker** only for an investigated significant user choice or a
   genuine operational interruption after reasonable attempts; a failed gate
   alone blocks release, not further investigation. Unreviewed commits are pending work: identify
   the next SHA and describe whether it was actually examined. Explain this in
   plain language before the per-commit table so the email does not imply an
   ordinary backlog needs a human decision.

## End-of-cycle update report

Begin the report and email with a short plain-language summary written for a
non-developer. Explain what the affected feature does, what went wrong and
under what circumstances, the practical effect on the user's system, what
is known versus unverified, and whether a user decision is actually needed.
Explain what was tried and why it could not continue; distinguish a release
gate from a real need for input and an operational interruption. Describe a
source-fingerprint mismatch as an unrecognised code change, not proof that
hardware or the feature is broken or safe. Place technical identifiers, exact
tests and the complete per-update table after this context. Never expose secrets.

At the end of each upstream-update cycle, include this brief Markdown table
for **every processed commit** in both the detailed report and the **email body**
(not just a linked file or attachment). Keep the detailed maintenance narrative
and gates alongside it:

| Upstream version / commit | Outcome | Brief reason / adjustment |
|---|---|---|
| `<tag or version> / <SHA>` | ported / amended / rejected / admin/no-port | One sentence; name the adaptation for amended work and the concrete reason for rejection. For `irrelevant to configured setup`, name the unavailable vendor or unused feature; for `admin/no-port`, name release/version/documentation bookkeeping. |

For a concrete conflict between a documented fork-specific change and the
required upstream outcome that cannot be safely amended, do not decide
silently: identify the conflicting fork hunk and upstream hunk, state the
alternatives in one or two sentences, and ask the user. Do not ask whether to
accept an upstream product choice on an inherited feature.

Send this final report by email through the configured Resend MCP. Reuse the
sender and recipient defaults from the server's `ha-update` skill reference;
do not expose credentials or duplicate them into this skill. If email delivery
fails, retain the local report and state the delivery failure in the cron output.

## Fork release publication

`main` is the fork release branch. Do not use repository visibility as a
maintenance eligibility, relevance, or publication condition; only the approved
origin identity and required gates matter. A public repository can be added to
HACS as a custom repository, but a release alone is not proof that Home
Assistant installed it. After a cycle that ports or amends one or more upstream
changes and passes its required gates, publish the tested feature branch to
the approved origin: update `custom_components/power_sync/manifest.json`
and `RELEASE_NOTES.md` with a unique fork version/tag of the form
`v<latest-fully-processed-upstream-tag>-nir.<serial>`, commit that release
metadata on `feature/shared-logical-evs`, fast-forward `main` to the verified
feature head, push both branches, and create the matching GitHub
release. Do not publish when the cycle only rejects/admin-skips updates, when
there is an unresolved commit, or when gates fail. Never deploy Home Assistant;
HA delivery needs a separately authorised method.

## Deployment handoff

A maintenance integration is not deployment proof. Deployment needs separate
authorisation, a fresh backup, a manual stop capability, staging prerequisites,
and post-deployment verification. If any are absent, report deployment as
deferred and continue only with safe source-maintenance work.
