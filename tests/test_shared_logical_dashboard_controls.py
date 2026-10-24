"""Dashboard commands use the selected EV, never the shared charger's old EV ID."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def _exercise(data):
    script = r"""
const fs = require('fs');
const vm = require('vm');
const registry = {};
const context = {
  HTMLElement: class { attachShadow() { this.shadowRoot = {}; } },
  customElements: { get(name) { return registry[name]; }, define(name, klass) { registry[name] = klass; } },
  window: {}, ResizeObserver: class {}, requestAnimationFrame() {},
};
vm.runInNewContext(fs.readFileSync('custom_components/power_sync/frontend/power-sync-strategy.js', 'utf8'), context);
const panel = new registry['power-sync-ev-panel']();
panel._data = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [];
panel._runCommand = async (key, path, payload) => { calls.push({key, path, payload}); };
(async () => {
  panel._syncSelectedLoadpoint();
  const options = panel._loadpoints().map(lp => ({id: lp.vehicle_id, name: panel._loadpointLabel(lp)}));
  await panel._startPolicy();
  await panel._stopLoadpoint();
  await panel._boostLoadpoint();
  console.log(JSON.stringify({options, calls}));
})().catch(error => { console.error(error); process.exit(1); });
"""
    result = subprocess.run(
        ["node", "-e", script], input=json.dumps(data), text=True,
        capture_output=True, cwd=ROOT, check=True,
    )
    return json.loads(result.stdout)


def test_selected_tank_dashboard_commands_address_logical_ev():
    result = _exercise({"status": {
        "shared_loadpoint_active": True, "selected_vehicle_id": "shared_ev_profile_a",
        "loadpoints": [{"loadpoint_id": "generic_ev", "vehicle_id": "shared_ev_profile_a",
                        "vehicle_name": "GWM Tank 500", "connected": True}],
    }})
    assert result["options"] == [{"id": "shared_ev_profile_a", "name": "GWM Tank 500"}]
    assert [call["path"] for call in result["calls"][:2]] == [
        "power_sync/ev/vehicles/shared_ev_profile_a/command",
        "power_sync/ev/vehicles/shared_ev_profile_a/command",
    ]
    assert result["calls"][2]["payload"]["vehicle_id"] == "shared_ev_profile_a"


def test_unknown_selector_has_no_dashboard_vehicle_commands():
    result = _exercise({"status": {
        "shared_loadpoint_active": True, "selected_vehicle_id": None,
        "loadpoints": [{"loadpoint_id": "generic_ev", "vehicle_id": None,
                        "vehicle_name": None, "shared_loadpoint": True,
                        "connected": True, "current_power_kw": 3.2}],
    }})
    assert result == {"options": [], "calls": []}


def test_unbound_dashboard_keeps_existing_physical_command_id():
    result = _exercise({"status": {
        "loadpoints": [{"loadpoint_id": "generic_ev", "vehicle_id": "generic_ev",
                        "vehicle_name": "EV", "connected": True}],
    }})
    assert result["options"] == [{"id": "generic_ev", "name": "EV"}]
    assert result["calls"][0]["path"] == "power_sync/ev/vehicles/generic_ev/command"
