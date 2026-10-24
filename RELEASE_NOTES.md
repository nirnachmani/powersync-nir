<!-- release: v2.12.1478-nir.3 -->

## PowerSync Nir fork
- When a shared Generic Charger or Sigenergy EVAC binding is active, project the selected logical EV's name, SoC and capacity into loadpoint status, widgets and HA sensor attributes without duplicating physical power or rewriting history. An unknown selector retains unassigned charger activity but offers no EV controls.
- Route dashboard and app command/Boost requests through the selected logical EV, rejecting stale physical IDs, missing/default IDs and unselected profiles. Keep the physical charger ID solely for runtime, metering and ownership.
- Hide the parked charger-as-EV record in vehicle settings and the dashboard Smart Schedule while keeping its stored configuration and history unchanged. Reject stale edits; an enabled parked plan is reported but cannot execute or reserve charging capacity. Do not copy settings or change enabled modes.
- Focused Android-contract, shared-EV, dashboard and planner tests and the private regression gates pass. The closed app's exact Quick Charge screen call site has not been verified; this release has not been installed or tested against the live charger. Apply through HACS only in a separately approved idle/rollback window.
