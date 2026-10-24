"""Dashboard Smart Schedule rows follow charger configuration, not stale storage."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _render_smart_schedule(data: dict) -> dict:
    result = subprocess.run(
        ["node", "-e", r"""
const fs = require('fs');
const vm = require('vm');
const registry = {};
const context = {
  HTMLElement: class { attachShadow() { this.shadowRoot = {}; } },
  customElements: {
    get(name) { return registry[name]; },
    define(name, klass) { registry[name] = klass; },
  },
  window: {},
  ResizeObserver: class {},
  requestAnimationFrame() {},
};
vm.runInNewContext(fs.readFileSync(
  'custom_components/power_sync/frontend/power-sync-strategy.js', 'utf8'), context);
const panel = new registry['power-sync-ev-panel']();
panel._data = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(JSON.stringify({card: panel._smartScheduleCard(), summary: panel._modeSummary()}));
"""],
        input=json.dumps(data), text=True, capture_output=True, cwd=ROOT, check=True,
    )
    return json.loads(result.stdout)


def test_disabled_sigenergy_plan_is_hidden_but_idle_generic_row_remains():
    data = {
        "status": {"loadpoints": [], "enabled_charger_backends": {"generic": True, "sigenergy": False}},
        "autoStatus": {"settings": {
            "generic_ev": {"enabled": False, "display_name": "Generic car"},
            "sigenergy_charger": {"enabled": False, "display_name": "Stale Sigenergy"},
        }},
    }
    rendered = _render_smart_schedule(data)
    assert "Generic car" in rendered["card"]
    assert "Stale Sigenergy" not in rendered["card"]


def test_switching_configured_backend_reveals_saved_sigenergy_plan():
    rendered = _render_smart_schedule({
        "status": {"loadpoints": [], "enabled_charger_backends": {"generic": False, "sigenergy": True}},
        "autoStatus": {"settings": {
            "generic_ev": {"enabled": False, "display_name": "Old Generic"},
            "sigenergy_charger": {"enabled": False, "display_name": "Sigenergy EVAC"},
        }},
    })
    assert "Old Generic" not in rendered["card"]
    assert "Sigenergy EVAC" in rendered["card"]


def test_future_logical_profiles_are_not_filtered_as_backends():
    rendered = _render_smart_schedule({
        "status": {"loadpoints": [], "enabled_charger_backends": {"generic": True, "sigenergy": False}},
        "autoStatus": {"settings": {
            "shared_ev_profile_a": {"enabled": False, "display_name": "Current car"},
            "shared_ev_profile_b": {"enabled": False, "display_name": "Future car"},
            "sigenergy_charger": {"enabled": False, "display_name": "Old Sigenergy"},
        }},
    })
    assert "Current car" in rendered["card"]
    assert "Future car" in rendered["card"]
    assert "Old Sigenergy" not in rendered["card"]


def test_inconsistent_enabled_schedule_is_not_silently_hidden():
    rendered = _render_smart_schedule({
        "status": {"loadpoints": [], "enabled_charger_backends": {"generic": True, "sigenergy": False}},
        "autoStatus": {"settings": {
            "sigenergy_charger": {"enabled": True, "display_name": "Check unexpected plan"},
        }},
    })
    assert "Check unexpected plan" in rendered["card"]
    assert "Smart Schedule" in rendered["summary"]


def test_missing_backend_flags_keep_legacy_rows_visible():
    rendered = _render_smart_schedule({
        "status": {"loadpoints": []},
        "autoStatus": {"settings": {
            "generic_ev": {"enabled": False, "display_name": "Generic car"},
            "sigenergy_charger": {"enabled": False, "display_name": "Sigenergy car"},
        }},
    })
    assert "Generic car" in rendered["card"]
    assert "Sigenergy car" in rendered["card"]


def test_bound_generic_charger_hides_old_ev_schedule_not_logical_profiles():
    rendered = _render_smart_schedule({
        "status": {"shared_loadpoint_active": True,
                   "enabled_charger_backends": {"generic": True, "sigenergy": False},
                   "loadpoints": [{"loadpoint_id": "generic_ev", "vehicle_id": "shared_ev_profile_a",
                                    "vehicle_name": "Tank"}]},
        "autoStatus": {"settings": {
            "generic_ev": {"enabled": False, "display_name": "Unused generic EV"},
            "shared_ev_profile_a": {"enabled": False, "display_name": "Tank"},
            "shared_ev_profile_b": {"enabled": False, "display_name": "Future EV"},
        }},
    })
    assert "Unused generic EV" not in rendered["card"]
    assert "Tank" in rendered["card"]
    assert "Future EV" in rendered["card"]
    assert rendered["card"].count('<div class="smart-row">') == 2


def test_enabled_old_plan_is_warned_about_not_offered_as_an_ev():
    rendered = _render_smart_schedule({
        "status": {"shared_loadpoint_active": True, "loadpoints": [],
                   "enabled_charger_backends": {"generic": True, "sigenergy": False}},
        "autoStatus": {"settings": {
            "generic_ev": {"enabled": True, "display_name": "Unused generic EV"},
            "shared_ev_profile_a": {"enabled": False, "display_name": "Tank"},
        }},
    })
    assert "Unused generic EV" not in rendered["card"]
    assert "legacy" in rendered["card"].lower()


def test_bound_generic_hides_only_its_own_retired_ev_schedule():
    rendered = _render_smart_schedule({
        "status": {"shared_loadpoint_active": True,
                   "shared_loadpoint_id": "generic_ev",
                   "enabled_charger_backends": {"generic": True, "sigenergy": True},
                   "loadpoints": []},
        "autoStatus": {"settings": {
            "generic_ev": {"enabled": False, "display_name": "Parked generic EV"},
            "sigenergy_charger": {"enabled": False, "display_name": "Separate Sigenergy"},
            "shared_ev_profile_a": {"enabled": False, "display_name": "Tank"},
        }},
    })
    assert "Parked generic EV" not in rendered["card"]
    assert "Separate Sigenergy" in rendered["card"]
