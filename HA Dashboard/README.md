# Home Assistant Dashboard for PowerSync

A dynamic Lovelace dashboard that automatically shows only the cards relevant to your setup. Uses a **dashboard strategy** — a JS module that checks which PowerSync entities exist and builds the dashboard accordingly.

## Features

The dashboard uses the PowerSync cloud app's look in your Home Assistant light or dark theme. Two full-width cards sit at the top:

- **Right now** - Battery activity, charge level, export floor, and live solar, home, battery and grid power
- **Optimizer plan** - The last 12 hours measured and the next 24 hours planned, with prices, charge level, battery actions, car charging and upcoming charge/export windows

Below them, one to three columns show only relevant cards: battery controls, energy flow, plan explanation, Amber tariff/prices, today's costs and energy, car charging, optimizer settings, forecasts, battery health, lifetime energy, solar curtailment, solar strings and additional battery integration details. The car charging card retains the selected logical A/B vehicle controls on a shared physical charger; unknown selection cannot issue a command.

Select **Customize layout** to move or hide cards. The layout is saved in your browser separately for one, two and three columns; **Reset layout** restores the default. The board design falls back to the classic dashboard if its module cannot load.

## Requirements

### HACS Frontend Integrations

Install from HACS (Frontend) when using the optional legacy card:

1. **[button-card](https://github.com/custom-cards/button-card)** - For the Solar curtailment card

The board's other charts, controls, and energy flow scene are built into PowerSync.

## Installation

### Automatic (Recommended)

The dashboard is **auto-created** when PowerSync starts. After installing the integration, a **"PowerSync"** dashboard appears in your sidebar automatically — no manual setup required.

If you previously created a dashboard manually, the auto-created "PowerSync" dashboard will appear alongside it. You can delete your old manual dashboard from **Settings > Dashboards**.

### YAML Mode Dashboards

If your Lovelace is configured in YAML mode (not storage mode), you need to manually register the strategy resource in your `configuration.yaml`:

```yaml
lovelace:
  resources:
    - url: /power_sync/frontend/power-sync-strategy.js
      type: module
```

Then create a dashboard with this config:

```yaml
strategy:
  type: custom:power-sync-strategy
views: []
```

## Configuration Options

The strategy accepts optional configuration:

```yaml
strategy:
  type: custom:power-sync-strategy
  entity_prefix: "power_sync"  # Override entity prefix detection
views: []
```

### Entity Prefix

The strategy auto-detects whether your entities use the `power_sync_` prefix (modern installs) or bare names (legacy). Override with `entity_prefix` if needed:
- `"power_sync_"` — entities like `sensor.power_sync_current_import_price`
- `""` — entities like `sensor.current_import_price`

## Troubleshooting

### Cards showing "Custom element doesn't exist"

A legacy card needs a HACS frontend dependency. Install **button-card** for Solar curtailment, then refresh your browser. Check the board's **Missing frontend cards** card for detected dependencies.

### Dashboard is blank

1. Check **Developer Tools > Lovelace Resources** for `power-sync-strategy.js`
2. If missing, restart Home Assistant to trigger auto-registration
3. For YAML mode, add the resource manually (see above)

### Strategy not found error

Clear browser cache and hard refresh (Ctrl+Shift+R / Cmd+Shift+R).

### Dashboard shows the old layout

The board loads `power-sync-dashboard.js` next to the strategy. If it cannot load, the classic layout appears and a warning is logged in the browser console. Hard refresh and verify the file exists in `custom_components/power_sync/frontend/`.

### Battery control buttons not working

Tap a control a second time to confirm. If it still does not respond:

1. Ensure the PowerSync integration is installed and configured
2. Verify select entities exist: `select.power_sync_force_charge_duration` and `select.power_sync_force_discharge_duration`
3. If missing, restart Home Assistant

### Charts showing no data

- Ensure the PowerSync integration is properly configured
- Wait for the integration to collect some data (may take 5-10 minutes)
- Trigger a sync via the "Sync Now" service or wait for automatic sync

### Seeing wrong sections or missing sections

The strategy checks `hass.states` at render time. If entities are temporarily unavailable during startup, refresh the dashboard once HA is fully loaded.

## Amber Price Models

PowerSync supports three pricing models: **Predicted** (default), **High** (conservative), and **Low** (aggressive).

See the [main README](../README.md#price-models) for full details on each model.

To change the price model:
1. Go to **Settings > Devices & Services > PowerSync**
2. Click **Configure**
3. Select your preferred **Price Model**
4. Click **Submit**
