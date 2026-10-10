# Private PowerSync Fork: Shared Loadpoints and External-Session Control Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Maintain the private Home Assistant integration **PowerSync Nir** (repository/release slug `powersync-nir`, Home Assistant domain/package `powersync_nir`) as the in-place replacement for original PowerSync on this HA instance. It supports two logical EVs sharing one Generic or Sigenergy charger and safely governs externally started sessions for all enabled EV modes—and, under `override`, when no mode is enabled—while regularly integrating upstream improvements without losing compatibility with the closed-source PowerSync Android app.

**Architecture:** Separate the *logical vehicle profile* (target SoC, deadline, capacity, priority, history attribution) from a *physical loadpoint* (charger endpoint, telemetry, command target, one active physical session) internally only. Preserve the Android app’s existing WebSocket/REST contracts, route names, field names, enum values, and response shapes; publish new private data only through additive optional fields or a separate private endpoint that the unmodified app never needs to call. Add one backend-neutral external-session reconciler that observes loadpoints before policy evaluation, owns external-session lifecycle, then presents a single result to all charging modes. Maintain local work as small, tested commits rebased onto tracked upstream tags; a scheduled Hermes job automatically integrates and deploys verified compatible updates.

**Tech Stack:** Home Assistant custom integration; Python/asyncio; PowerSync v2.12.1363 baseline; pytest; contract/snapshot tests; git worktrees; Hermes Agent cron + isolated profile; HACS/manual custom-repository deployment.

---

## Product scope and non-goals

### Required product boundary

- Support **two logical EV profiles** bound to exactly one selected physical charger backend: either the existing Generic Charger bridge **or** a Sigenergy EVAC charger. The private fork need not support both backends simultaneously.
- A physical loadpoint has **one active vehicle/session at a time**. An externally maintained HA entity is the authoritative indication of which logical EV is connected; PowerSync reads it and attributes the physical session to that profile.
- Each profile has a required, user-editable display name. Configure or rename the two names through the PowerSync integration's Options Flow; persist them as each logical profile's existing `display_name` and publish that same field unchanged to the Android app.
- Each profile retains its own capacity, target SoC, departure/deadline, Smart Schedule settings, Solar Surplus eligibility, and priority, using the existing multi-vehicle planning model wherever possible. Solar Surplus policy thresholds, Price-Level policy, and Scheduled Charging policy remain shared charger/site settings in the first release because the released Android app exposes only global controls for them.
- Physical start/stop/current, fresh power observation, ownership, session reconciliation, and exclusion of competing modes operate on the **one selected loadpoint**, never independently on two profiles that share hardware.

### Android app compatibility boundary

The Android app is closed source and is a supported client of the private fork. Treat its existing backend protocol as a versioned public contract.

- Do not remove, rename, repurpose, or change the type/meaning of fields, routes, services, WebSocket events, enum values, or list ordering that the released app may consume.
- Keep existing `vehicle_charging_configs` records and public vehicle identities app-compatible. Internal `loadpoint_id`, session association, lease, reconciliation, and adapter data must be stored separately or represented as optional additive fields only.
- Preserve existing endpoints/views and response envelopes. New diagnostics/controls should be either optional additions that older clients ignore or private endpoints used by HA/developer tooling; they cannot be prerequisites for normal app operation.
- The Android app multi-vehicle feasibility spike is complete for released Android app 1.0.7 build 336: it renders arbitrary records from the existing vehicle-list contract without requiring Tesla VIN/brand semantics; it displays `display_name`, supports a multi-vehicle Smart Schedule selector, and sends the selected stable ID through existing endpoints. It does not provide per-profile global Solar Surplus policy, Price-Level, or Scheduled Charging policy screens, so those remain shared charger/site settings.
- Emit two stable app-compatible logical records (`id`/`vehicle_id`, `display_name`, status fields) and retain one shared physical-control binding internally. The backend must resolve either profile ID to the selected shared Generic/EVAC command target without changing an app route, request shape, or response shape.
- The released app has no profile-name editor. The private integration Options Flow is the naming UI; any configured `display_name` must appear identically in the app vehicle list, Smart Schedule selector, configuration cards, sessions, and history.
- Before every private change and upstream integration, run protocol contract tests using captured/sanitised real app requests and expected response/event snapshots. An app-facing change is incompatible unless a currently installed app build demonstrably handles it.

### Explicit non-goals for the first release

- Supporting Tesla, Sigenergy EVDC, OCPP, Zaptec, or any other charger backend in the private fork. Disable/remove their private-fork paths if necessary rather than spending effort preserving them.
- Simultaneous charging of two vehicles from one physical charge outlet.
- Reworking PowerSync’s energy forecasts, optimiser, price selection, or power-management algorithms. The fork reuses existing per-vehicle planning and existing mode decisions; it changes only profile-to-charger binding and external-session observation/control.
- Adding a new policy that decides external charging should continue. Under `override`, an unplanned external session is stopped; if an existing charging mode already plans/allows that profile, its existing decision controls the adopted session.
- Requiring a modified Android app. The private fork must preserve compatibility with the currently installed closed-source app; extra two-profile controls may live in Home Assistant/private server interfaces when the app has no compatible UI surface.
- General-purpose migration, multi-user tenancy, or support for arbitrary pre-existing configurations. The implementation is tailored to the user’s current HA setup and can use a deliberate one-time private configuration conversion.

### Policy rule to implement

For every configured, observed physical loadpoint:

| External policy | Desired mode state | Required action |
|---|---|---|
| `yield` | any | Record external ownership; no PowerSync command. |
| `override` | a mode allows charging | Adopt/reconcile one physical session and apply that mode’s limits. |
| `override` | no mode allows charging, including all modes disabled | Request a safe stop, retain `stop_pending` until fresh stopped/zero-power confirmation, then release. |
| telemetry stale/unknown | any | Do not infer an active or stopped session; record uncertainty and do not command based solely on stale data. |

The aggregate desired state must be decided once per loadpoint after every EV mode is evaluated. A priority order should be explicit and tested: user-approved manual/boost > scheduled/planned PowerSync owner > Solar Surplus > external yield > override/no-mode stop.

---

## Current-code findings that drive the design

Implementation baseline: upstream tag `v2.12.1363`. Re-map the exact symbols and regressions against this tag before coding; prior architectural findings identify likely areas but are not treated as line-level truth.

1. `vehicle_charging_configs` currently combines logical vehicle metadata and physical adapter configuration. `vehicle_id` is frequently used for both identity types.
2. Generic uses synthetic `generic_ev`; Sigenergy uses `sigenergy_charger`. Each represents a charger/loadpoint, not a particular car.
3. `ev_ownership.py`, dynamic state in `actions.py`, and `ChargingSessionManager` key state by `vehicle_id`; two profile IDs sharing one command target could each obtain a lease and race commands.
4. Site EV-load aggregation already deduplicates physical meters in `__init__.py`, but that does not enforce command/session exclusivity.
5. Generic external-session adoption exists only in the Solar Surplus dynamic loop. Smart Schedule, Price-Level, Scheduled Charging, and all-modes-off have no general non-Tesla takeover path.
6. The existing Tesla observer is backend-specific; it remains outside the private-fork scope and must not be used as a dependency for Generic/EVAC reconciliation.

---

## Phase 0: Fork, baseline, and safety rails

### Task 1: Establish the private-fork topology

**Objective:** Make upstream and private ownership unambiguous before code changes.

**Files:**
- Create: `README_PRIVATE_FORK.md`
- Create: `AGENTS.md`
- Create: `.github/CODEOWNERS` only if the private repository uses GitHub review

**Steps:**
1. Rename the private repository/release/HACS slug to `powersync-nir` and keep it private. The Home Assistant integration's visible title is `PowerSync Nir`; its unique domain/package/directory is `powersync_nir` (HA domains cannot contain `-`).
2. Rename the upstream component directory `custom_components/power_sync/` to `custom_components/powersync_nir/`; update the manifest, constants, config-entry unique IDs, entity unique-ID prefixes, storage keys, services, translations, tests, and all internal imports. This fork replaces original PowerSync on the HA instance; do not attempt to support simultaneous loading.
3. Preserve the released Android client’s hard-coded `/api/power_sync/...` HTTP route namespace and its request/response semantics. The integration domain must not leak into or rename those app routes; register them from `powersync_nir` with the existing route names. This makes simultaneous loading with original PowerSync impossible because HA HTTP routes are unique; deployment must remove/disable original PowerSync first.
4. Clone the private fork to the Ubuntu server. Configure `origin` = private `powersync-nir` fork and `upstream` = `bolagnaise/PowerSync`.
5. Create permanent branches:
   - `main`: private release branch, always deployable;
   - `upstream/main`: fast-forward mirror of upstream only;
   - `feature/integration-rename`;
   - `feature/shared-logical-evs`;
   - `feature/external-session-reconciler`.
6. In `README_PRIVATE_FORK.md`, record the distinct integration identity, scope, upstream baseline, deployment method, app-route compatibility exception, and explicit non-goals above.
7. In `AGENTS.md`, require: no direct edits to `main`, every upstream integration produces a report, test commands and Android-app protocol contract tests must pass, and automatic deployment is permitted only through the defined updater gates with verified rollback.

**Verification:**
```bash
git remote -v
git log --oneline --decorate -5 main upstream/main
git status --short
```
Expected: clean worktree; distinct `origin` and `upstream`; both branch tips recorded.

### Task 2: Capture the Android app protocol and build compatibility tests

**Objective:** Establish a regression contract for the released closed-source Android app before internal data-model changes. Static APK evidence is the implementation gate; a controlled physical capture is optional pre-release confirmation, not a blocker.

**Files:**
- Create: `tests/contracts/android_app/README.md`
- Create: `tests/contracts/android_app/fixtures/` (sanitised request, response, and WebSocket-event snapshots)
- Create: `tests/test_android_app_contract.py`
- Create: `scripts/private-fork/capture_android_contract.py`
- Modify: `README_PRIVATE_FORK.md`

**Steps:**
1. Identify every app-facing PowerSync endpoint, WebSocket command/event, and service/view used by the released app through the decoded APK and integration routing/source.
2. Store a versioned static baseline tied to the app version and PowerSync baseline tag. It must contain only derived route, field, enum, and payload-shape evidence—never credentials, addresses, identifiers, or raw app traffic.
3. Write contract tests that compare the static app route/field baseline against the test Home Assistant harness or registered views. Allow explicitly whitelisted additive optional fields only; reject removed, renamed, type-changed, or semantically repurposed existing fields.
4. Provide a capture-sanitisation tool for optional controlled captures from the user’s HA instance. Do not use a capture as an implementation prerequisite and do not commit raw traffic.
5. Keep a manual physical-app smoke checklist for a pre-release environment: app loads, existing Generic/Sigenergy charger view loads, existing schedule controls save, existing status/history views render, and no app-facing errors occur.

**Verification:**
```bash
/home/nir/PowerSync/.venv/bin/python -m pytest -q tests/test_android_app_contract.py
```
Expected: static baseline fixtures pass against the upstream baseline before private changes begin. A physical-app smoke test remains required before deployment.

### Task 3: Record Android-app feasibility result and lock its contract

**Objective:** Convert the completed Android-app feasibility spike into executable regression requirements before internal profile/loadpoint work.

**Files:**
- Modify: `tests/test_android_app_contract.py`
- Create: `tests/test_android_app_multi_vehicle_contract.py`
- Create: `docs/private-fork/android-multi-vehicle-feasibility.md`

**Established result:** released Android app 1.0.7 build 336 accepts two arbitrary logical vehicle records, displays each `display_name`, renders a multi-vehicle Smart Schedule selector, and sends selected stable IDs to existing endpoints. It does not have per-profile global Solar Surplus, Price-Level, or Scheduled Charging policy screens.

**Steps:**
1. Document the static evidence: exact app version/checksum, vehicle-list field mapping, config write by `vehicle_id`, and Smart Schedule selector/ID flow. Do not claim an app feature that was not observed in the decoded released build.
2. Add contract fixtures containing two anonymous logical records with unique stable IDs, distinct `display_name` values, `vin: null`, and existing non-Tesla-compatible status fields.
3. Assert the backend returns both records, preserves names/types/order, accepts an existing vehicle-config write keyed by either logical ID, and accepts the corresponding Smart Schedule ID.
4. Assert command requests retain their current route/body shape. The private backend maps the logical ID to the shared charger only internally.
5. Assert the global Solar Surplus, Price-Level, and Scheduled Charging response shapes remain single shared-policy objects; do not create a false per-profile app contract for them.

**Verification:**
```bash
/home/nir/PowerSync/.venv/bin/python -m pytest -q \
  tests/test_android_app_contract.py tests/test_android_app_multi_vehicle_contract.py
```
Expected: two named logical records and per-profile Smart Schedule are contract-compatible without Tesla impersonation or an app change.

### Task 4: Create a private regression harness before refactoring

**Objective:** Freeze known desired behaviour with tests that fail against current limitations.

**Files:**
- Create: `tests/test_private_shared_loadpoints.py`
- Create: `tests/test_external_session_reconciler.py`
- Modify: `tests/test_ev_ocpp_actions.py`
- Modify: `tests/test_ev_price_level_ownership.py`

**Steps:**
1. Add a test fixture for a Generic charger with switch, amps, status and fresh power entities.
2. Add an equivalent fixture for whichever backend is selected for implementation: Generic or Sigenergy EVAC.
3. Write failing tests for:
   - two profiles resolving to one physical Generic loadpoint;
   - only one physical command writer/lease across those profiles;
   - external active Generic session under override/no enabled mode produces one Stop request and waits for readback;
   - stale power does not create a session;
   - each mode consumes the same reconciled external-session result.
4. Run the tests and commit only the red tests as the specification baseline.

**Verification:**
```bash
/home/nir/PowerSync/.venv/bin/python -m pytest -q \
  tests/test_private_shared_loadpoints.py tests/test_external_session_reconciler.py
```
Expected: failures that describe missing physical loadpoint identity/reconciliation, not import errors.

---

## Phase 1: Separate logical vehicles from physical loadpoints

### Task 5: Bind two logical profiles to the one selected physical charger

**Objective:** Add the smallest private internal binding needed to reuse existing multi-vehicle planning while guaranteeing that only the HA-selected connected profile can control the shared charger.

**Files:**
- Modify: `custom_components/powersync_nir/config_flow.py`
- Modify: `custom_components/powersync_nir/const.py`
- Create: `custom_components/powersync_nir/automations/shared_loadpoint.py`
- Modify: `custom_components/powersync_nir/__init__.py`
- Modify: `custom_components/powersync_nir/automations/ev_charging_planner.py`
- Test: `tests/test_private_shared_loadpoints.py`
- Test: `tests/test_android_app_multi_vehicle_contract.py`

**Design:**
```python
@dataclass(frozen=True)
class SharedLoadpointBinding:
    backend: Literal["generic", "sigenergy_evac"]
    binding_id: str
    connected_vehicle_entity: str
    control: dict
    telemetry: dict
```

**Steps:**
1. Configure exactly one `SharedLoadpointBinding` for either Generic or Sigenergy EVAC. Do not implement a multi-loadpoint registry.
2. Add a private two-profile section to the PowerSync integration Options Flow with two required, non-empty `display_name` fields and a deterministic mapping from each profile ID to the configured HA connected-vehicle entity value. Reopening Options must permit renaming without changing the stable profile IDs, charger binding, or already attributed history.
3. During private setup/rename, persist each name in its logical `vehicle_charging_configs` record as `display_name`; do not create a second name field or change any Android app contract. Enforce distinct normalized names so the app’s vehicle list and Smart Schedule selector are unambiguous.
4. Read the configured HA connected-vehicle entity on every control/evaluation cycle. Map its declared state/value to one of the two existing logical `vehicle_id` profiles; unknown/unavailable/unmapped state means no profile may initiate a physical command.
5. Store the binding and active-profile association in private runtime/storage state. Keep existing `vehicle_charging_configs` and Android-app payload fields intact except for the existing `display_name` value.
6. Reuse existing per-vehicle configurations for planning. Replace only the unsafe first-config fallback in `_get_vehicle_charger_params()` with resolution through the selected logical profile plus the shared physical-control binding.
7. Publish both named profiles through the existing app vehicle/configuration contract: each must have its own stable `id`/`vehicle_id` and its persisted `display_name`; never use `generic_ev` or `sigenergy_charger` as an app-visible profile identity.
8. Make a deliberate one-time configuration conversion for this HA instance; no general legacy migration or cross-backend conversion is required.

**Acceptance tests:**
- The Options Flow rejects blank or duplicate normalized names, persists both accepted names, and allows either to be renamed without changing the profile's stable ID, binding, or past session attribution.
- The connected-vehicle entity maps to profile A or B and only that profile may own/control the charger.
- Unknown/unavailable entity state prevents a new physical Start/current command.
- Both profiles retain independent existing schedule/mode configuration, resolve to one shared physical command target, and return their configured `display_name` unchanged through vehicle discovery and config endpoints.
- Generic and EVAC are mutually exclusive deployment choices.

### Task 6: Scope ownership and dynamic runtime state to the shared charger

**Objective:** Make one physical loadpoint impossible to control through competing logical profile IDs.

**Files:**
- Modify: `custom_components/powersync_nir/automations/ev_ownership.py`
- Modify: `custom_components/powersync_nir/automations/actions.py`
- Modify: `custom_components/powersync_nir/automations/ev_charging_session.py`
- Modify: `custom_components/powersync_nir/automations/ev_charging_planner.py`
- Test: `tests/test_private_shared_loadpoints.py`

**Steps:**
1. Change lease key construction in `ev_ownership.py` from logical `vehicle_id` to canonical `loadpoint_id`.
2. Include the active logical `vehicle_id` in lease metadata for display and energy attribution.
3. Key `_dynamic_ev_state[entry_id]` by loadpoint. Store `active_profile_id` in each state record.
4. Key physical `ChargingSessionManager` activity by loadpoint; create one logical attribution record linked to the physical session.
5. Update canonicalization functions:
   - `_canonical_auto_schedule_vehicle_id()`;
   - `_resolve_dynamic_loadpoint_id()`;
   - `_ev_action_loadpoint_id()`;
   - `_get_vehicle_charger_params()`;
   - API/manual parameter builders in `__init__.py`.
6. Ensure every start, stop, rate command and ownership lookup passes both `profile_id` and `loadpoint_id`, never inferring one from the other.
7. Make “parallel charging” mean separate physical loadpoints only. Retire the Solar-Surplus-only guard as a global exclusion mechanism.

**Acceptance tests:**
- Schedule on profile A blocks a physical start/current command from profile B on the same loadpoint.
- An approved profile switch while idle changes attribution without charger commands.
- A switch while physically charging performs a defined handoff: stop/settle old controller, update association, then apply new policy; no simultaneous loops.
- Site EV load is counted once and session energy belongs only to the selected profile.

### Task 7: Enforce shared-loadpoint exclusion in existing Generic/EVAC command paths

**Objective:** Prevent per-profile commands from bypassing the one shared physical charger with the smallest feasible change; do not introduce a new adapter framework unless the baseline audit proves the existing dispatch cannot be safely centralised.

**Files:**
- Modify: `custom_components/powersync_nir/automations/actions.py`
- Modify: `custom_components/powersync_nir/automations/ev_charging_planner.py`
- Modify: `custom_components/powersync_nir/automations/sigenergy_charger_config.py` only if EVAC resolution requires it
- Test: `tests/test_private_shared_loadpoints.py`, relevant existing Generic/Sigenergy tests

**Steps:**
1. Use the Phase-0 v2.12.1363 audit to trace all Generic and EVAC start/stop/current writes.
2. Add one shared-loadpoint resolver/guard used immediately before existing command dispatch. It must resolve the HA-selected profile, obtain the shared ownership lock, and return the existing Generic/EVAC command parameters.
3. Keep the existing Generic switch/amps/status/power and EVAC command implementations intact wherever possible; remove only profile-local configuration resolution that can target the shared charger without the guard.
4. Add a small backend-neutral helper only if the existing command functions cannot share the guard without duplicated or divergent logic. Do not extract a broad `LoadpointAdapter` hierarchy for unsupported backends.
5. Prove no start, stop, or current write can reach the one physical target without the guard.

**Acceptance tests:**
- Two logical profiles bound to the shared charger never invoke conflicting start/stop/current writes.
- The existing Generic and EVAC control behaviour remains unchanged when only one profile is configured.

---

## Phase 2: Add minimal shared-charger external-session reconciliation

> **Execution order decision:** Task 8 is implemented before completing Phase 1 Task 6. A safe charging-profile handoff requires fresh physical observation and stop-settle proof; Task 8 is the plan's single authority for that evidence. This reorders implementation only—Task 6 acceptance remains required before Task 7 begins.

### Task 8: Define observation, origin classification, and reconciliation state

**Objective:** Establish one safe authority for external physical-session state.

**Files:**
- Create: `custom_components/powersync_nir/automations/external_session_reconciler.py`
- Modify: `custom_components/powersync_nir/automations/ev_ownership.py`
- Test: `tests/test_external_session_reconciler.py`

**Design:**
```python
@dataclass(frozen=True)
class SharedLoadpointObservation:
    binding_id: str
    connected: bool | None
    charging: bool | None
    power_kw: float | None
    observed_at: datetime | None
    evidence: str  # fresh_power, charger_state, command_echo

@dataclass
class ReconciliationState:
    origin: str  # external, powersync, settling, unknown
    physical_active: bool | None
    active_profile_id: str | None
    stop_outcome: dict | None
    observed_session_token: str | None
```

**Steps:**
1. Implement fresh Generic or Sigenergy EVAC observation for the one configured shared charger; do not create adapters or semantics for excluded backends.
2. Classify `external`, `powersync`, `settling`, or `unknown` from fresh observation, command ledger, shared-charger lock, and the HA connected-vehicle entity.
3. Persist reconciliation state for the one binding only.
4. Introduce stop lifecycle states: `pending`, `confirmed`, `failed`, `indeterminate`.
5. Reject stale/missing telemetry as evidence of either an active session or a confirmed stop.
6. Keep physical observation and logical ownership separate; ownership is policy, not proof of energy flow.

**Acceptance tests:**
- Fresh positive Generic power with no matching PowerSync command is external.
- Power following a PowerSync start is PowerSync-controlled.
- Delayed positive power after a Stop remains settling, not a new external session.
- Unavailable/stale power produces unknown and no command.

### Task 9: Feed one reconciled external state into existing mode decisions

**Objective:** Let existing Solar Surplus, Smart Schedule, Scheduled Charging, and Price-Level policy decide whether the HA-selected profile is planned/allowed, then apply that result to the observed shared charger without redesigning energy planning.

**Files:**
- Modify: `custom_components/powersync_nir/__init__.py`
- Modify: `custom_components/powersync_nir/automations/observed_tesla_sessions.py`
- Modify: `custom_components/powersync_nir/automations/ev_charging_planner.py`
- Modify: `custom_components/powersync_nir/automations/actions.py`
- Test: `tests/test_external_session_reconciler.py`

**Steps:**
1. At the start of `auto_evaluate_automations()`, reconcile the one configured shared charger.
2. Do not replace the Tesla observer or rework unrelated backends; keep their existing paths outside the private-fork scope.
3. Evaluate the existing charging modes for the HA-selected profile using their current scheduling, pricing, forecasting, and power-management logic.
4. If an external session is active under `override`, use the resulting existing mode decision: adopt/control it only when a mode already allows/plans charging; otherwise issue one safe stop. Under `yield`, send no command.
5. Execute at most one command sequence for the shared charger per evaluation cycle through the shared guard.
6. Write one command ledger event and one session record per physical action/session.

**Acceptance tests:**
- No mode probes hardware independently after reconciliation.
- Cross-mode decisions for two profiles on one loadpoint resolve to one command.
- A failure to read fresh telemetry produces visible unknown state rather than false adoption/stop.

### Task 10: Apply existing override/yield policy consistently to the shared charger

**Objective:** Extend the existing modes’ external-session handling to Generic or Sigenergy EVAC without adding a new charging-planning policy.

**Files:**
- Modify: `custom_components/powersync_nir/automations/actions.py`
- Modify: `custom_components/powersync_nir/automations/ev_charging_planner.py`
- Modify: `custom_components/powersync_nir/automations/ev_ownership.py`
- Test: `tests/test_external_session_reconciler.py`
- Test: `tests/test_ev_price_level_ownership.py`
- Test: `tests/test_ev_ocpp_actions.py`

**Steps:**
1. Reuse the existing Generic Solar Surplus adoption/stop logic where possible, routing it through shared reconciliation rather than duplicating mode logic.
2. Make Smart Schedule, Scheduled Charging, and Price-Level query the reconciled Generic/EVAC physical state only to apply their existing allow/stop decision; do not change their window, price, forecast, optimiser, or target calculations.
3. Under `override`, an unplanned external session is stopped. If any existing mode already plans or permits charging for the HA-selected profile, that mode adopts/continues it using its normal current/stop logic.
4. Under `yield`, external ownership suppresses automatic commands.
5. With all modes disabled, `override` stops an active external session and waits/retries for readback; `yield` observes only.
6. Treat every external start identically. There is no manual-start exception or separate user-intent detection; intentional manual charging must be initiated through PowerSync.

**Acceptance matrix:**

| Selected backend | Solar Surplus | Smart Schedule | Scheduled | Price-Level | All modes off |
|---|---:|---:|---:|---:|---:|
| Generic **or** Sigenergy EVAC | existing decision + override/yield reconciliation | existing decision + override/yield reconciliation | existing decision + override/yield reconciliation | existing decision + override/yield reconciliation | override stop / yield observe |

Tesla, Sigenergy EVDC, OCPP, Zaptec, and other charger backends are out of scope; do not add compatibility work for them.

### Task 9: Add session-history and UI diagnostics

**Objective:** Make takeover decisions auditable without inspecting source/logs.

**Files:**
- Modify: `custom_components/powersync_nir/automations/ev_charging_session.py`
- Modify: `custom_components/powersync_nir/__init__.py`
- Modify: frontend/API files that expose EV automation status
- Test: relevant API/session tests

**Expose per loadpoint:**
- physical loadpoint name/backend;
- active selected profile;
- latest observation time and evidence;
- origin: PowerSync/external/settling/unknown;
- policy: override/yield;
- desired action and responsible mode;
- command and fresh readback outcome;
- clear reason when control cannot be safely applied.

**Acceptance tests:**
- One external physical session is not double-recorded when adopted by PowerSync.
- UI/API explains “awaiting fresh readback” rather than claiming stopped.
- Shared Generic/Sigenergy loadpoint reports the selected profile and active controller.

---

## Phase 3: Focused verification and deployment

### Task 12: Build the relevant recovery test matrix

**Objective:** Validate the user’s single shared charger, two profiles, externally maintained HA vehicle-selection entity, and HA restart behaviour without general migration/multi-user coverage.

**Files:**
- Modify: `tests/test_ev_ownership_runtime.py`
- Modify: `tests/test_ev_vehicle_status.py`
- Test: `tests/test_private_shared_loadpoints.py`
- Test: `tests/test_external_session_reconciler.py`

**Required cases:**
1. HA connected-vehicle entity selects either profile and an unknown state blocks new physical commands.
2. Two profiles resolve to one Generic **or** EVAC physical command target with no competing commands.
3. HA restart during external charge re-observes fresh evidence before action.
4. HA restart during stop-pending does not assume stopped.
5. Stale telemetry, unavailable status, invalid current range, and no configured stop entity all fail closed.
6. Existing mode decision remains authoritative: planned/allowed charge continues; unplanned external charge under override stops.

### Task 13: Run focused regression suites

**Objective:** Verify new architecture does not regress existing charging flows.

**Commands:**
```bash
/home/nir/PowerSync/.venv/bin/python -m pytest -q \
  tests/test_android_app_contract.py \
  tests/test_android_app_multi_vehicle_contract.py \
  tests/test_private_shared_loadpoints.py \
  tests/test_external_session_reconciler.py \
  tests/test_ev_price_level_ownership.py \
  tests/test_ev_ownership_runtime.py \
  tests/test_ev_vehicle_status.py
```

Run the broader suite only for files touched by the private fork and the Android protocol contract. Do not spend implementation effort repairing excluded charger backends; record unrelated baseline/environment failures separately.

### Task 14: Controlled Home Assistant staging validation

**Objective:** Verify actual Generic **or** Sigenergy EVAC physical control only after unit-level proof and Android app contract verification.

**Preconditions:** test window; ability to manually stop charging; fresh backup of deployed custom component/config; Android app protocol baseline captured.

**Scenarios:**
1. HA connected-vehicle entity selects profile A, external start, override/no modes: one Stop and confirmed zero power.
2. Same profile under `yield`: no command.
3. Smart Schedule profile A starts/controls/ends one physical session using unchanged planning rules.
4. Changing the HA entity to profile B prevents profile A from issuing a later physical command and allows profile B’s existing plan to govern the charger.
5. Verify recorder `call_service`, current entity, physical power, reconciler status, session attribution, and Android app operation for every scenario.

---

## Upstream update agent: design and operating model

### Principle

Use a **three-way git integration workflow**, not an LLM directly overwriting a deployed component. Upstream is always imported into a disposable worktree; local features are maintained as small commit series; the agent resolves conflicts in that candidate worktree, runs tests, and then automatically merges and deploys a verified compatible candidate. It stops for human review only when the upstream change cannot be safely reconciled with private invariants, supersedes a private feature with a materially different design, or is irrelevant because the private fork already solves the same problem.

### Repository layout on the Ubuntu server

```text
~/src/powersync-private/             # private fork clone; main checked out
~/src/powersync-private-upstream/    # optional clean upstream mirror/worktree
~/src/powersync-update-worktrees/    # disposable candidate worktrees
~/powersync-update-reports/          # dated Markdown + JSON summaries
~/powersync-update-state.json        # last reviewed upstream commit/tag, approvals
```

Keep deployment separate from git working trees. Make the GitHub fork **private** at creation; never mirror or publish it publicly. Configure HACS on the user’s HA to follow the private fork’s private deploy branch using an authenticated GitHub/HACS access path. The update agent advances that branch automatically only after candidate validation and post-deployment health checks.

### Task 13: Add machine-readable local-change inventory

**Files:**
- Create: `docs/private-fork/local-change-inventory.md`
- Create: `scripts/private-fork/validate_local_architecture.py`
- Create: `scripts/private-fork/run_private_tests.sh`

**Inventory sections:**
- connected-profile entity and shared-charger binding;
- shared-charger command guard;
- reconciliation lifecycle/policy;
- shared-charger ownership/session history;
- Android app protocol contracts and private tests;
- upstream coupling points and known conflict-prone files.

The validator should assert private invariants such as: no first-profile fallback; all selected-backend physical commands pass through the shared-charger guard; existing mode planning remains unchanged; reconciliation never changes a mode’s calculated allow/stop decision; Android app contract tests pass.

### Task 14: Build a read-only upstream-delta classifier

**Files:**
- Create: `scripts/private-fork/collect_upstream_delta.py`
- Create: `scripts/private-fork/classify_delta.py`
- Create: `docs/private-fork/upstream-update-policy.md`

**Inputs:** last reviewed upstream SHA/tag, latest upstream tag/commit, `git log`, `git diff --name-status`, changed test names, release notes.

**Classifications and action:**
1. **No overlap:** upstream changes do not touch private modules or their direct tests. Automatically rebase/merge, test, tag, deploy, and verify.
2. **Mechanical overlap:** same file, separate hunks. Automatically resolve in the candidate, run expanded tests, then merge/deploy on success.
3. **Compatible semantic overlap:** touches adapter, ownership, actions, planner, session, config migration, or private tests, but the agent can preserve every private invariant and demonstrate this with tests. Automatically implement the compatible resolution, run the full relevant suite, then merge/deploy.
4. **Private feature already covers the upstream change:** do not import redundant code. Record the upstream commit as reviewed/ignored with a concise equivalence rationale; retain the private implementation and continue processing later upstream changes.
5. **Incompatible semantic conflict:** upstream replaces or changes a private behavioural contract, cannot satisfy the private invariants/tests, or requires an unverified physical-control decision. Do not merge/deploy; preserve the candidate worktree and alert with an exact conflict report.
6. **Safety-critical deployment failure:** candidate tests may pass, but staging/post-deployment validation fails, the integration does not load, or expected entities/control capability are absent. Automatically roll back to the prior private release, mark the update failed, and alert.

Classification must be deterministic first (paths/symbols/tests), with Hermes used to explain changes and implement a test-backed compatible resolution—not to invent test results. “Conflict” means an unsatisfied private behavioural invariant or failed verification, not merely a shared file or merge hunk.

### Task 15: Create a dedicated Hermes update profile and skill

**Files:**
- Create private Hermes profile: `powersync-maintainer`
- Create skill: `powersync-private-updates`
- Create reference files under the skill: update checklist, report template, conflict checklist
- Create project `AGENTS.md` in the private fork

**Profile requirements:**
- deploy the `powersync-maintainer` Hermes profile on the always-on Ubuntu server where Hermes is already installed; its working directory is the private fork;
- terminal + file + web/GitHub tools, plus one tightly scoped deployment script permission that may update/restart only the PowerSync integration after candidate gates pass; no general Home Assistant control tools;
- credentials scoped to the private GitHub repository; enforce private visibility and reject a public remote/repository before every push;
- prompt instructions that allow merging to the private deploy branch and deployment only after the defined test/staging gates; prohibit force-push, branch deletion, public-repository changes, and secret output;
- use a strong coding model; allow subagents for independent code review/test analysis and semantic-conflict adjudication.

**Skill procedure:**
1. Fetch upstream tags/commits.
2. Read state file and collect delta.
3. Classify impact.
4. Create a disposable candidate worktree and branch.
5. Rebase/cherry-pick no-overlap changes. For any overlap, implement the compatible resolution while preserving the local architecture and tests; omit only redundant upstream changes already covered by the private feature.
6. Run the Android-app protocol contract suite after the architecture validator and before the targeted/broad pytest suites.
7. If all gates pass, merge the candidate to the private deploy branch, push, create a private release tag, update through HACS/approved deployment mechanism, and run post-deployment checks: integration loaded, expected entities and shared-charger binding exist, Android-app smoke checks pass, and no new PowerSync errors.
8. If deployment verification fails, restore the prior release immediately, verify rollback, and alert.
9. Write a report with exact base/candidate SHAs, imported/ignored commits, changed files, contract/test and deployment results, current deployed version, and any unresolved conflict. Alert only for failures, rollback, or genuinely incompatible changes; otherwise send a brief success record.

### Task 16: Schedule the Hermes autonomous upstream-maintenance job

**Recommended schedule:** every 3 days on the always-on Ubuntu server, with a short jitter. It may also run on demand after a critical upstream release.

**Job prompt must require:**
- latest upstream tag/commit identification;
- comparison from `last_reviewed_upstream` and `last_deployed_private_release`;
- deterministic classification and preservation of private invariants;
- automatic merge/tag/deploy only after all specified checks pass;
- automatic rollback plus alert on a failed post-deployment check;
- report written to `~/powersync-update-reports/`;
- a concise success notification containing upstream range, imported/ignored commits, deployed private version, and test status; an immediate detailed notification only for conflicts, failed tests, or rollback.

**Autonomous workflow:**
1. Hermes prepares and tests a candidate.
2. For no-overlap, mechanical, or compatible semantic updates, it merges to the private deploy branch, tags/releases it, deploys it, and validates the deployed integration.
3. For a redundant upstream fix already covered by the private fork, it records the commit as reviewed/ignored and moves on without deployment.
4. Only an incompatible conflict, a failed verification, or a rollback requires user attention. The agent preserves the candidate branch/worktree and its report for later review.
5. A later run must resume from recorded upstream/deployment state, not repeat already reviewed commits.

### Task 17: Validate the update agent with simulated upstream changes

**Objective:** Prove the updater respects boundaries before real releases.

**Scenarios:**
1. Documentation-only upstream change → automatically merge/tag/deploy/report.
2. Upstream test-only change outside private files → automatically merge/tag/deploy/report after the required test suite.
3. Upstream modification to `actions.py` external-session code that preserves private invariants → agent creates a compatible candidate, proves it with reconciler tests, then automatically merge/deploys.
4. Upstream external-session fix already implemented by the private reconciler → agent records it as redundant/ignored and advances reviewed-upstream state without code replacement.
5. Upstream modification to config migration or ownership that breaks a private invariant → candidate retained, deployment untouched, detailed conflict alert.
6. Simulated failed test or post-deployment health check → no candidate promotion, or automatic rollback if already deployed; verify the prior private release is restored.
7. Resume after an interrupted run → state file preserves last reviewed, last integrated, last deployed, and ignored-upstream SHA ranges correctly.

---

## Merge and commit strategy

Keep commits narrowly scoped and ordered so future rebases are resolvable:

1. `test: lock Android app two-profile and name contract`
2. `feat: configure two logical profile names in private Options Flow`
3. `test: specify shared charger and external-session behaviour`
4. `feat: bind connected-profile entity to one shared Generic or EVAC charger`
5. `feat: scope EV ownership and sessions by shared charger`
6. `fix: guard existing generic and evac command paths by shared charger`
7. `feat: reconcile external shared-charger sessions before existing mode actions`
8. `fix: apply override and yield policy across existing EV modes`
9. `feat: expose shared-charger reconciliation diagnostics`
10. `docs: add private-fork updater policy and local-change inventory`
11. `chore: add automated upstream review workflow`

Avoid a long-lived giant divergence commit. Rebase each focused feature series onto current `upstream/main` after its tests pass.

---

## Decisions fixed before implementation

1. **Connected profile:** an externally maintained HA entity is authoritative. It maps to one of the two logical EV profiles. Under `override`, unknown, unavailable, or unmapped state makes every active charge unplanned and requires a safe Stop with readback confirmation; under `yield`, PowerSync observes only. Such a state never permits a new physical Start/current command.
2. **Charger scope:** choose one configured backend for this installation: Generic **or** Sigenergy EVAC. Do not support Tesla, Sigenergy EVDC, OCPP, Zaptec, or other chargers.
3. **All-modes-off override:** it is inherent in `override`; no extra per-loadpoint option is added.
4. **External/manual starts:** every externally started session is treated identically. Under `override`, it is stopped unless an existing PowerSync mode already plans/allows charging; manual charging must be initiated through PowerSync.
5. **Power-management behaviour:** preserve existing PowerSync calculation and planning. Reuse its multiple-EV profiles and existing mode decisions; add only shared-charger binding, observation, and command exclusion.
6. **Android app:** feasibility is established for two non-Tesla app-visible records. Use two named logical profiles with stable IDs and the existing `display_name` field; names are configured/renamed in the private PowerSync integration Options Flow. Retain app-compatible profile-level Smart Schedule and configuration. Solar Surplus policy, Price-Level, and Scheduled Charging policy remain shared settings because the released app exposes no per-profile screen for them.
7. **Private distribution:** the fork remains private. HACS follows the authenticated private deploy branch.
8. **Updater:** the dedicated `powersync-maintainer` Hermes profile runs on the always-on Ubuntu server every three days and automatically integrates/deploys verified compatible upstream changes.

---

## Completion criteria

The fork is ready for routine use only when all are true:

- The Android app multi-profile feasibility result is documented; the selected implementation remains fully compatible with the installed app build and its contract suite.
- Two logical EV profiles can use one selected Generic **or** Sigenergy EVAC charger without conflicting commands or double-counted energy; the HA connected-vehicle entity determines attribution and command eligibility.
- One active physical session is associated with the entity-selected profile and survives/reconciles across HA restarts.
- Fresh external sessions follow existing Solar Surplus, Smart Schedule, Scheduled Charging, and Price-Level decisions under `yield`/`override`; an unplanned external session under override/no mode is stopped.
- Every Stop is retained pending fresh physical confirmation; stale telemetry never produces a false conclusion.
- Focused private tests, Android protocol contracts, and the controlled physical staging matrix pass.
- The scheduled Ubuntu-hosted Hermes maintainer automatically integrates, tags, deploys, and verifies compatible upstream changes; it alerts only on an incompatible conflict, failed verification, or rollback.
