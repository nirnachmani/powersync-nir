<!-- release: v2.12.1649-nir.2 -->

## v2.12.1649-nir.2 — simplify maintainer scope
- Rework maintainer instructions into one relevance, equivalence, minimal-port and fork-compatibility decision process. Trial maintenance without subagents; fix regressions introduced by an update and avoid unrelated pre-existing issues.
- Remove contradictory merge and testing directions, keep approved AI explanation providers, preserve safety gates and explain blockers in plain language. No integration runtime behavior changes.

<!-- release: v2.12.1649-nir.1 -->

## v2.12.1649-nir.1 — reviewed upstream through v2.12.1649
- Preserve available solar in optimizer dispatch and prefer solar over redundant grid top-ups in fallback plans. Parse Solcast cache data off the Home Assistant event loop.
- Periodically checkpoint energy and cost totals during continuous telemetry. Clean up expired force charge and discharge listeners during recovery.
- Retire deleted EV schedules from persistent storage while preserving sibling profiles and shared physical sessions. Refresh EV battery-preservation intent and distinguish accepted charging policy from actual charging in responses.
- Restore the dashboard manual power-limit slider, improve energy-flow contrast, and identify measured solar charging in plan history.
- Relevant upstream changes were ported or adapted while preserving the private shared-EV and no-paywall boundaries; unavailable vendor-specific and entitlement-only changes were excluded. Architecture and focused private compatibility gates passed. Source release only: no Home Assistant installation, restart, or physical control was performed.

<!-- release: v2.12.1616-nir.4 -->

## v2.12.1616-nir.4 — maintainer autonomy and reporting
- Clarify that a failed release check blocks publication, not investigation: the maintainer must diagnose and resolve ordinary issues autonomously without weakening safety checks.
- Escalate significant functional choices and genuine operational interruptions with context; start email reports with a plain-language explanation of the affected feature, consequences and whether a decision is needed. No integration runtime behavior changes.

<!-- release: v2.12.1616-nir.3 -->

## v2.12.1616-nir.3 — shared EV stop and handoff
- Keep the outgoing Generic Charger or Sigenergy EVAC owner and session fenced while an actual stop is unverified. Release only the matching owner after a qualifying post-stop observation, including mode changes, logical-vehicle handoffs and stops without an immediate successor. This fixes a stop path that could reacquire and strand Smart Schedule ownership.
- Preserve existing charging-mode decisions, priorities and Android routes. An unresolved stop raises a Home Assistant persistent warning after two minutes; observed continued charging and unavailable evidence are distinguished. Already-idle command-neutral handoffs remain separate from a physical stop.
- A confirmed EVAC connection rejection before any stop write may be retried at most twice, at least 30 seconds apart; timeouts and uncertain writes are not blindly retried. A reported HA storage failure does not prevent an authorized stop and raises a warning. HA Store can suppress or defer some failures, so restart recovery cannot be guaranteed after an unsuccessful save; a crash before a dispatch timestamp is saved can also leave a stop fenced for manual attention.
- Generic post-stop verification requires a new HA-reported low-power value; missing or delayed telemetry can delay release. This is an observation of low power, not proof of an open contactor. Source release only: no Home Assistant installation, restart or charger command was performed.

<!-- release: v2.12.1616-nir.2 -->

## v2.12.1616-nir.2 — correct hourly Amber Smart Schedule forecasts
- Smart Schedule now converts Amber's short import and feed-in forecast intervals into duration-weighted local-hour prices rather than taking the first interval in a misaligned hour. Current-hour forecasts use the remaining covered portion; incomplete or conflicting channel coverage uses the existing 30c/8c estimates.
- The Smart Schedule remains hourly and retains its existing live-price checks. More accurate EV plans can change the EV demand passed to the battery optimizer; the shared Amber feed, optimizer price model, Flow Power and Android/API contracts are unchanged. Existing planner limitations around the repeated daylight-saving hour and the final partial departure hour are not addressed by this correction.
- Source publication only: no Home Assistant installation, restart or charger command was performed.

<!-- release: v2.12.1616-nir.1 -->

## v2.12.1616-nir.1 — reviewed upstream through v2.12.1616
- Solar forecasts remain visible during fallback planning; Solcast quota exhaustion uses Open-Meteo when available and recovers after the daily reset. The no-paywall optimizer credits actually stored solar toward later protected exports and retains measured provenance through unchanged-SoC solves.
- The dashboard highlights active flows, fits midnight labels, displays the full 48-hour battery plan, and distinguishes measured battery flow from a conditional plan in monitoring mode.
- Failed Generic/Sigenergy shared-EV stop requests publish HA events and persistent warnings keyed by the canonical physical loadpoint. A fresh, newer idle observation clears the warning; a later accepted start rearms a new failure episode without asserting that the prior stop was confirmed. Private selector, lease, session, and Android routes remain guarded.
- Tesla, GloBird, AGL, GoodWe, and optimizer-entitlement-only outcomes were excluded. Architecture, optimizer-continuity, Android-contract, and focused private compatibility gates passed. This is source publication only: no Home Assistant installation, restart, or physical control was performed.

<!-- release: v2.12.1581-nir.3 -->

## v2.12.1581-nir.3 — show saved Smart Schedule price ceilings correctly
- EV Charging Options now reads logical EV A/B grid-price ceilings from Home Assistant's loaded schedule store. The previous form inspected HA Store's transient write buffer, so it displayed the 25 c/kWh default even when a custom ceiling (such as 32 c/kWh) had been saved. A price-only save need not reload the integration because it changes the schedule store rather than config-entry options.
- Existing saved prices, app/API settings and charging policy are unchanged. Source publication only: no Home Assistant installation, restart or physical charger command was performed.

<!-- release: v2.12.1581-nir.2 -->

## v2.12.1581-nir.2 — per-EV Smart Schedule grid-price ceiling in Options
- PowerSync Options → EV Charging now displays separate maximum Smart Schedule grid-import prices for logical EV A and B, prefilled from each EV's saved Smart Schedule settings (25 c/kWh if unset). Changing one does not enable that EV or alter its sibling's settings.
- Options and the existing app/API edit the same per-EV schedule record; the saved ceiling is restored after reload/restart. A newly lowered ceiling also governs execution while an older plan is cached. Saving errors are shown rather than falsely reporting a complete save.
- Source publication only: no Home Assistant installation, restart, or charger command was performed.

<!-- release: v2.12.1581-nir.1 -->

## v2.12.1581-nir.1 — reviewed upstream through v2.12.1581
- The generated energy-flow card can read canonical EV loadpoint status. A shared Generic/Sigenergy EVAC charger appears as the selected logical vehicle only, without duplicate physical rows or a guessed vehicle when selection is unknown; stale or unavailable API data falls back to configured entities.
- Battery mode and dashboard labels identify the recorded command source instead of claiming every active force command was manual. The no-paywall optimiser reconciles stored battery provenance only from measured, ready SoC telemetry and attempts cost and provenance saves even when shutdown cleanup fails.
- Manual Sigenergy force charge/discharge supports validated custom minutes or a finish time in Home Assistant's timezone. Invalid timing is rejected before export ownership, timer or hardware changes. Tesla-only EV/recovery and optimiser-entitlement paths remain excluded.
- Architecture, optimiser-continuity, Android contract, shared-loadpoint and focused private gates passed. Source release only: no Home Assistant installation, restart or physical commands were attempted.

<!-- release: v2.12.1572-nir.3 -->

## v2.12.1572-nir.3 — recheck fork HACS identity after refresh
- Revalidate the HACS repository ID, current fork release URL, and tag after the awaited HACS entity refresh and again after the GitHub fallback lookup. If the repository changes during either wait, do not call `update.install` or restart HA. This completes the fork-only scheduled update boundary introduced in v2.12.1572-nir.2; no manual HACS behaviour is changed.
- Source release only; no HA installation, restart, or physical control was performed.

<!-- release: v2.12.1572-nir.2 -->

## v2.12.1572-nir.2 — fork-only scheduled HACS updates
- Restrict the optional scheduled updater to the HACS update entity registered for `nirnachmani/powersync-nir`, checking both its GitHub repository ID and HACS-generated release URL, even when an old upstream entity remains or the fork entity is renamed. The GitHub fallback now checks the fork's releases, accepts only newer `-nir.<serial>` tags, and pins the validated tag in `update.install` so HACS cannot switch versions between check and action. Unknown/upstream-only tags fail closed; a newer fork release supersedes an older pending download before restart.
- Update the maintainer policy and private-architecture inventory to trace a newly exposed setting through existing side-effecting code, including repository identity and install/physical-command boundaries. Manual HACS updates are unchanged. Source release only: no HA installation, restart, or device control was performed.

<!-- release: v2.12.1572-nir.1 -->

## v2.12.1572-nir.1 — reviewed upstream through v2.12.1572
- The approved upstream live solar-forecast correction is now opt-in, including default-off on upgrade. Dashboard settings use themed dialogs and retain the private selected-logical-EV panel and command guard; solar-versus-grid charging windows now show their distinct site costs without importing the unused Zerohero premium-cap display.
- Existing AI explanations gain an automatic interval option. Shared Sigenergy EVAC observations, unplugged price-level holds, and legacy departure clearing retain private physical ownership and logical-profile attribution. The optimizer retains measured solar through export replans and excludes cached EV demand when EV integration is disabled without deleting either logical vehicle's plan.
- Upstream Tesla-only and optimiser-entitlement hunks were not imported. Private architecture, optimizer continuity, Android-app contract, and shared-loadpoint gates passed in the maintainer checkout. This is source publication only; Home Assistant installation/restart, storage edits, charger and inverter commands were not attempted.

<!-- release: v2.12.1517-nir.5 -->

## v2.12.1517-nir.5 — clarify upstream-maintenance decision boundary
- The maintainer skill now directs applicable inherited upstream feature updates to be ported as upstream intended, including settings and changed upgrade defaults. It no longer treats an upstream product decision as a reason to ask for approval or invent a fork-specific migration; user input is reserved for a concrete conflict with this fork's intentional changes that cannot be safely adapted.
- Skill-policy and version-metadata release only. No PowerSync runtime behavior or HA configuration changed; there is no reason to install this version in HA for the maintainer-policy update.

<!-- release: v2.12.1517-nir.4 -->

## v2.12.1517-nir.4 — align PowerSync maintainer policy
- Consolidate the tracked maintainer skill with the server's branch-reconciliation and merge-ledger rules and the fork's hunk-by-hunk divergence safeguard. Make upstream relevance explicitly outcome-first: identify the issue fixed or enhancement delivered, then port compatible behavior or adapt it to private invariants, while recording redundancy and excluding entitlement code.
- Document exact tracked/profile skill synchronisation so future server-only edits cannot silently diverge. No PowerSync runtime behavior or HA configuration is changed by this source release; updating HA through HACS is unnecessary for the maintainer-policy change.

<!-- release: v2.12.1517-nir.3 -->

## v2.12.1517-nir.3 — Sigenergy zero-export event-loop correction
- Mark the Sigenergy export-limit state-change listener as a Home Assistant event-loop callback. Previously the synchronous handler ran in an executor, where scheduling the guarded zero-export repair raised a thread-safety error before any Modbus work began. The existing `dc_zero` ownership, retry bounds, register readback and restore semantics are unchanged.
- A regression using Home Assistant's actual state-change event helper reproduced the thread-safety error before the correction and passed afterward; the Sigenergy test suite passed. Publication makes the fix installable through HACS; no Home Assistant installation, restart or inverter write is part of this source release.

<!-- release: v2.12.1517-nir.2 -->

## v2.12.1517-nir.2 — HACS-only PowerSync updates
- Retire PowerSync's notification-only `update.power_sync_update` platform, which checked the original upstream repository but could not install updates. HACS's install-capable update entity for the configured repository is now the only PowerSync update source; on integration setup, remove only the old PowerSync-owned update registry entry, leaving HACS update entities untouched.
- The separate scheduled auto-update feature is unchanged and remains opt-in; this release does not fix its upstream-release fallback or enable unattended installation/restarts. Existing `power_sync` configuration and Android routes are unchanged. Source release only; no Home Assistant installation, restart, or physical device command was performed.

<!-- release: v2.12.1517-nir.1 -->

## v2.12.1517-nir.1 — reviewed upstream through v2.12.1517
- Amber optimiser ignores timestamped price intervals outside its forecast horizon instead of rebasing them onto the current slot (adapted from upstream `9b5a62e6`); the exact no-paywall continuity gate and upstream pricing regressions passed.
- Sigenergy site energy estimates now include configured daily/monthly supply costs and keep local-day/month totals separate at midnight (vendor-neutral part of `ccf8f688`). GloBird ZeroHero bonus and credit logic was excluded.
- Solar Surplus offers an HA switch sharing the app's stored setting; disabling it still uses the private selected-logical-EV stop and physical ownership guard (`97c37ec4`). Existing Android POST behavior and routes remain compatible.
- The maintainer ledger now handles merge-branch upstream commits without replaying prior outcomes. The published Sigenergy export-limit ownership/repair fixes from the previous release were retained when reconciling the private branches.
- Private architecture, optimiser continuity, Android contract, shared-loadpoint and reconciliation gates passed. This is a source release only: no Home Assistant installation/restart, storage edit, or charger command was performed.

<!-- release: v2.12.1492-nir.5 -->

## v2.12.1492-nir.5 — Sigenergy export-limit ownership and fast zero repair
- The existing five-minute Sigenergy DC-curtailment handler remains the sole price/EV decision-maker. It grants zero-export ownership only after a confirmed write. A rise in the polled export-limit entity then triggers a guarded register-40038 read and zero repair only while that ownership is current; the event listener does not calculate tariff freshness or EV headroom independently. Fast attempts are limited to three in a rolling five minutes with at least ten seconds between attempts.
- Manual Force Discharge takes priority for its duration; ending it successfully invokes the existing DC check once. Unrelated Force Charge cleanup preserves a held zero. Standalone native handoff and optional export-cap actions are one-shot; durable Controls cap edits preserve current zero without overriding manual force. In-flight Modbus writes recheck ownership; ambiguous zero-write acknowledgements are reconciled on a later policy check. Disabling DC control fences scheduled writes during restore, while disabling only battery curtailment does not release DC zero. A same-endpoint AC Sigenergy controller cannot independently command this plant register.
- The owner is entry-local. After a restart, an already-zero physical limit without identifiable provenance is not automatically lifted on a profitable-price check; durable cross-restart recovery is not part of this release. Local focused regressions and the private architecture/optimizer gates passed. Source release only: no Home Assistant installation, restart or live inverter command was performed.

<!-- release: v2.12.1492-nir.4 -->

## v2.12.1492-nir.4 — Sigenergy zero-export drift correction
- When SAPN/Grid Service raises the Sigenergy plant export-limit register during active PowerSync DC curtailment, a change in the Sigen HA number now triggers one guarded native-register check and zero-export reassertion rather than waiting for the next periodic check. A successful write requires a zero register readback; retries are bounded and retain the original normal-export restore target.
- The fast path requires a current price in its applicable slot, the existing uneconomic-export decision, enabled native DC control, and no solar-surplus EV headroom, force/export ownership, or conflicting monitoring mode. It does nothing for profitable or stale prices, normal export operation, an absent number entity, or a legitimate release; the five-minute check remains the fallback. It does not suppress DNSP commands or guarantee uninterrupted zero if the inverter gives them priority.
- Source release only: no Home Assistant installation/restart or physical inverter command was performed during development.

## v2.12.1492-nir.3 — shared EV Scheduled and Price-Level commands
- Scheduled Charging and its external-session stop now resolve the currently selected logical EV before issuing Generic Charger or Sigenergy EVAC commands. The coordinator's direct start/stop paths do the same. Unavailable or unmapped selection issues no shared command; retired physical IDs remain rejected at the command boundary.
- Price-Level Charging now tracks A/B by logical identity, uses only the selected EV's SoC for recovery/opportunity decisions, and routes starts/stops through that profile. A selector change mid-decision cannot authorise the other EV. External-session adoption seeds the same logical state, avoiding a duplicate start; a sibling's decision cannot clear the old home-battery hold until a fresh idle observation confirms that the origin EV no longer owns the charger.
- Scheduled Charging retries the new selected EV after an A/B handoff within the same charging window instead of treating A's global charging flag as proof that B has started. Smart Schedule's existing physical-command path was verified for both A/B and Generic/EVAC. The nonshared/Tesla paths retain their prior selection. Focused charging-path and private architecture gates passed. Source publication only: no Home Assistant installation, restart, setting change, or charger action.

## v2.12.1492-nir.2 — Solar Surplus logical-EV selection
- With a shared Generic Charger or Sigenergy EVAC, Solar Surplus now considers only the currently selected logical EV for that physical charger. A retained, enabled legacy charger record can no longer win the first priority slot and have its start rejected by the shared safety guard. An unknown selector starts neither logical EV; saved legacy records are not deleted or changed.
- Focused A/B and Generic/EVAC selection regressions plus private compatibility gates passed. This release is source publication only; it does not install or restart Home Assistant or operate the charger.

## v2.12.1492-nir.1 — reviewed upstream through v2.12.1492
- Optimizer logs distinguish acceptance of a requested charge command from measured charging (reviewed part of upstream `9595199b`); the Powerwall-only SOC logic was excluded.
- After selecting Amber, a stale GloBird pricing device can be removed without permitting removal of an active provider or changing legacy pack cleanup (adapted from `731f0403`).
- The dashboard displays today's recorded import/export prices alongside the tariff model, with historical spikes and blank future hours (from `8d2e37f4`).
- Private architecture, optimizer continuity, Android app-contract, shared-loadpoint and reconciliation gates passed. This release is source publication only; it does not install or restart Home Assistant or operate the charger.

## Previously released: v2.12.1478-nir.5

## PowerSync Nir fork
- Both logical EVs now display the physical Generic Charger entities configured in integration options. Physical switch/current/status/power settings (or selected Sigenergy EVAC transport) remain owned by the integration, not separate per-EV app records; conflicting app edits are rejected and stale vehicle overrides cannot drive shared commands.
- Logical EV A and B usable capacities can be edited or explicitly cleared in integration options. They use the same per-EV vehicle records as the app/dashboard; an omitted field preserves its existing capacity. The old charger-wide Generic capacity no longer applies to bound logical EVs.
- Charging-schedule preview and Price-Level projection use each logical EV's own capacity instead of treating a Generic-backed logical EV as an anonymous charger.
- The fork's maintainer inventory and repository instructions now identify this split as an intentional upstream divergence requiring hunk-by-hunk review.
- Local private regression gates and focused capacity/app/preview tests passed. This release does not install or restart Home Assistant and does not operate the charger; update through HACS in an idle, backed-up window.
