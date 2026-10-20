<!-- release: v2.12.1447-nir.1 -->

## PowerSync Nir private fork

- Preserve two logical EV profiles sharing one selected Generic Charger or Sigenergy EVAC physical loadpoint, guarded external-session reconciliation, and existing Android API routes.
- Import `DOMAIN` for solar planning (adapted from upstream `d54e87e6`).
- Include the configured daily supply charge in Amber metered usage totals, including live edits and zero (upstream `125085d7`).
- Credit final solar exports in Cost Neutral's discretionary battery-export budget (reviewed no-paywall hunks from upstream `52465064`).
- Accept covering 5-, 15-, and 30-minute Amber current-price intervals (Amber portion of upstream `b2781034`; Tesla tariff code excluded).
- Respect small Sigenergy battery export targets during hardware refresh (upstream `3b207aa7`).
- Exclude upstream optimiser licensing and unrelated vendor backends; this private fork remains noncommercial.

Source maintenance only. HACS installation and Home Assistant deployment are separate user actions.
