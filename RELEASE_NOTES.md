<!-- release: v2.12.1492-nir.2 -->

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
