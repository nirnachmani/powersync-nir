<!-- release: v2.12.1478-nir.2 -->

## PowerSync Nir fork
- Hide disabled Generic/Sigenergy charger backends' unused Smart Schedule rows in the dashboard. Keep their saved settings so switching the selected physical backend later restores its plan; never hide a contradictory enabled plan.
- Preserve existing Generic EV settings, logical EV profiles, optimizer/charger control, and the Android API response. The loadpoint-status endpoint gains additive backend-configuration flags for dashboard presentation.
- Based on selectively reviewed upstream v2.12.1478. This release does not deploy to Home Assistant; apply it through the HACS custom repository when a safe update window is available.
