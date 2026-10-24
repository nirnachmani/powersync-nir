"""HA-facing namespace contract for the restored PowerSync component."""

from __future__ import annotations

from pathlib import Path
import difflib
import hashlib
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "power_sync"
BASELINE = "v2.12.1363"
BASELINE_COMMIT = "85f99ea62a174cd9153d5ff2ce71023dda2c9a5c"
OPTIMIZATION = Path("custom_components/power_sync/optimization")
COORDINATOR = OPTIMIZATION / "coordinator.py"
BATTERY_OPTIMIZER = OPTIMIZATION / "battery_optimizer.py"
# These separately approved plan-explanation modules do not contain optimizer
# control code and therefore do not belong to this baseline corpus.
EXPLANATION_ONLY_MODULES = {
    OPTIMIZATION / "ai_summary.py",
    OPTIMIZATION / "chatgpt_auth.py",
}

# Amber forecast confidence is an explicitly reviewed, opt-in optimizer
# extension. Keep its source exact rather than admitting arbitrary new modules.
_AMBER_FORECAST_CONFIDENCE_MODULE = (
    OPTIMIZATION / "price_forecast_confidence.py"
)
_AMBER_FORECAST_CONFIDENCE_SHA256 = (
    "17b159de46f810f27d74c24078f88bc5642edf82f39a1bb680b0d35145f414a3"
)


def _expected_battery_optimizer_source() -> str:
    """Return the immutable baseline plus this reviewed solar-only hunk."""
    baseline = _git_show(BASELINE_COMMIT, BATTERY_OPTIMIZER)
    expected = baseline.replace(
        '''            Known-free stored energy can make a lower-FIT export slot
            profitable without making grid-import-to-export passthrough safe.
            Preserve that distinction while allowing forecast solar to refill
            the battery for a later premium export window.
            """
            return (
                p_mode[t] in (None, "self_use")
                and not p_block_charge[t]
                and not _priority_export_slot(t)
                and getattr(self, "_acquisition_cost_known_zero", False)
                and _profitable_export_slot(t)
                and p_price_valid_slots[t]
                and not future_self_consumption_values[t]
                and p_solar[t] > p_load[t] + 1e-9
            )
''',
        '''            Known-free or already-profitable stored energy can make a
            lower-FIT export slot profitable without making
            grid-import-to-export passthrough safe. Preserve that distinction
            while allowing forecast solar to refill the battery for a later
            premium export window.
            """
            return (
                p_mode[t] in (None, "self_use")
                and not p_block_charge[t]
                and not _priority_export_slot(t)
                and (
                    getattr(self, "_acquisition_cost_known_zero", False)
                    or (
                        acquisition_cost_kwh > 0
                        and any(
                            p_allow_export[future]
                            and (
                                _priority_export_slot(future)
                                or p_export[future] + p_export_bonus[future]
                                > p_import[future] + 1e-9
                            )
                            for future in range(t + 1, p_n)
                        )
                    )
                )
                and _profitable_export_slot(t)
                and p_export[t] + p_export_bonus[t] < p_import[t] - 1e-9
                and p_price_valid_slots[t]
                and not future_self_consumption_values[t]
                and p_solar[t] > p_load[t] + 1e-9
            )
''',
        1,
    )
    assert expected != baseline
    return expected


def _expected_optimizer_coordinator_source() -> str:
    """Return baseline coordinator plus the one reviewed shared-LP guard."""
    baseline = _git_show(BASELINE_COMMIT, COORDINATOR)
    expected = baseline.replace(
        """            from ..automations.ev_charging_planner import (
                get_auto_schedule_executor,
                is_smart_schedule_grid_price_allowed,
            )
            from ..const import DOMAIN
""",
        """            from ..automations.ev_charging_planner import (
                get_auto_schedule_executor,
                is_smart_schedule_grid_price_allowed,
            )
            from ..automations.shared_loadpoint import (
                PROFILE_A_ID,
                PROFILE_B_ID,
                binding_for_entry,
                canonical_shared_loadpoint_id,
                resolve_active_shared_profile,
            )
            from ..const import DOMAIN
""",
        1,
    ).replace(
        """            now = dt_util.now()
            plans = []
            policy_diagnostics: dict[str, dict[str, Any]] = {}
            for vehicle_id, state in (getattr(executor, "_state", {}) or {}).items():
""",
        """            now = dt_util.now()
            plans = []
            policy_diagnostics: dict[str, dict[str, Any]] = {}
            shared_binding = binding_for_entry(executor.config_entry)
            selected_shared_profile = (
                resolve_active_shared_profile(
                    getattr(self, "hass", None), executor.config_entry
                )
                if shared_binding is not None
                else None
            )
            shared_physical_loadpoint = (
                canonical_shared_loadpoint_id(
                    executor.config_entry, PROFILE_A_ID
                )
                if shared_binding is not None
                else None
            )
            for vehicle_id, state in (getattr(executor, "_state", {}) or {}).items():
                if (
                    shared_binding is not None
                    and (
                        vehicle_id == shared_physical_loadpoint
                        or (
                            vehicle_id in (PROFILE_A_ID, PROFILE_B_ID)
                            and vehicle_id != selected_shared_profile
                        )
                    )
                ):
                    # The planner normally clears this at its availability
                    # boundary. Keep this narrow read-side guard for restored
                    # or selector-race state so two logical profiles cannot
                    # reach the LP as one physical Generic/EVAC loadpoint.
                    continue
""",
        1,
    ).replace(
        """            if by_vehicle:
                api_response["ev_charging_by_vehicle_w"] = {
                    vehicle_id: list(series[:n_sched_pts])
                    for vehicle_id, series in by_vehicle.items()
                }
            elif self._ev_coordinator and data.get("ev"):
""",
        """            if by_vehicle:
                api_response["ev_charging_by_vehicle_w"] = {
                    vehicle_id: list(series[:n_sched_pts])
                    for vehicle_id, series in by_vehicle.items()
                }

                from ..automations.shared_logical_ev_chart import (
                    shared_logical_optimizer_chart_payload_for_coordinator,
                )

                logical_demand = shared_logical_optimizer_chart_payload_for_coordinator(
                    coordinator=self,
                    schedule_response=api_response,
                    series_by_vehicle_w=by_vehicle,
                    plan_snapshot_id=plan_snapshot_id,
                )
                if logical_demand is not None:
                    api_response["logical_ev_planned_demand"] = logical_demand
            elif self._ev_coordinator and data.get("ev"):
""",
        1,
    )
    assert expected != baseline
    return expected


# Exact, path/symbol-specific exception for reviewed Amber, signed-export,
# display-flow, forecast/status, manual-state, and persisted battery-spec
# provenance ports. The baseline-to-shared-LP transform above remains
# mandatory; this digest permits only those bounded coordinator hunks and
# cannot waive an unrelated optimizer change.
_AMBER_COORDINATOR_DIFF_SHA256 = "721fd3d8a5db88106eeeae48e23c960ad0c5e008b73cd838cb3407809c9d30dd"

# Exact allowance for reviewed 24fcc7d solar projection/learning/derating
# hunks, d54e87e6's missing DOMAIN import, 52465064's final solar-credit
# handoff, 3b207aa7's Sigenergy low-target refresh, and 2572e5db's
# Amber current-interval precedence, b0c1570c's failed fallback retry,
# 79cfe227's Sigenergy site export cap, 5c74c936's measured-charge-before-
# provenance settlement, f3a443a8's read-only reserve visibility API
# projection, and ec0d6fa8's current-slot export-reserve decision and
# hardware-source provenance hunks adapted to the private force/restore paths.
# The source is the reviewed provenance cohort; no off-grid, entitlement,
# or unrelated vendor hunk is admitted by this exact digest.
_NEGATIVE_IMPORT_SOLAR_SOURCE = "5ddd156708d1b5b05f1a67be87d1fb0ea99653c7"
_NEGATIVE_IMPORT_SOLAR_DIFF_SHA256 = (
    "1793df84bc2bb8f9afdbac1c291b7b393a5a5adfce20da1a9d6160778ea53940"
)

# Exact, path-specific exception for the reviewed Cost Neutral reachable-
# deadline fix. The normal optimizer baseline contract stays intact: only the
# complete b20bffb2 source delta is admitted.
_COST_NEUTRAL_REACHABLE_DEADLINE_DIFF_SHA256 = (
    "1a31032e30981313684b5a6b0d37f800519f8b76669836de22056873c3aa0298"
)

# Exact, path-specific candidate allowance for upstream 2cc05e2b adapted on
# top of the reviewed private e3c17217 optimizer source. It may neither admit
# a broader optimizer change nor alter the private shared-loadpoint boundary.
_PROJECTED_MODE_ALIGNMENT_SOURCE = "e3c172173565eb7fefd5b2fdee280722b65dd66d"
_PROJECTED_MODE_ALIGNMENT_DIFF_SHA256 = (
    "1a956ec2ccfa2e498a3ac67ad85664a544e06bef3641a24df29f7cebeb1d5ec8"
)

# Exact, path/symbol-specific candidate allowance for upstream 2a53f413 adapted
# on top of the reviewed private projected-mode source. It may neither admit a
# broader optimizer change nor alter the private shared-loadpoint boundary.
_NATIVE_SOLAR_CLIPPED_EXPORT_SOURCE = "8eac5f535f17f68324c98924ab40ce60c27bf5c0"
_NATIVE_SOLAR_CLIPPED_EXPORT_DIFF_SHA256 = (
    "303f33c1f73f95d5eb960c785e2852443c362a77b84aa7dfa68271ff6fe8750f"
)

# Exact allowance for upstream 2ff8c9d2 and 52465064 on top of the fully
# reviewed private optimizer source. Disable Idle projects the runtime action;
# final solar credits constrain discretionary exports. No broader delta is admitted.
_DISABLE_IDLE_DEADLINE_SOURCE = "25f388110c1159fbaf08d614e77af6ef4dc32f03"
_DISABLE_IDLE_DEADLINE_DIFF_SHA256 = (
    "575a2dec4bc5a82eb5f766af1419ccc200ea76eaddfc09459bd5ed1ac847d3cd"
)

# Exact upstream 52465064 plan-schema delta. Legacy no-solar callers remain
# supported; this digest does not waive changes elsewhere in cost_neutral.py.
COST_NEUTRAL = OPTIMIZATION / "cost_neutral.py"
_FINAL_SOLAR_CREDIT_SOURCE = "608042abefd68d5de6edbc2fb5f4aafb107c1e58"
_FINAL_SOLAR_CREDIT_DIFF_SHA256 = (
    "a00a1d81861473f06fa6f9cc6414c6af858b1b9e9bdb5f54b03d3ed315ebc9f0"
)


def _final_solar_credit_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_FINAL_SOLAR_CREDIT_SOURCE, COST_NEUTRAL)
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(), actual.splitlines(),
            fromfile="private_608042ab", tofile="final_solar_credit_candidate",
            lineterm="",
        )
    )
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _FINAL_SOLAR_CREDIT_DIFF_SHA256


def _amber_coordinator_diff_is_allowlisted(expected: str, actual: str) -> bool:
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="shared_lp_baseline",
            tofile="amber_spike_candidate",
            lineterm="",
        )
    )
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _AMBER_COORDINATOR_DIFF_SHA256


def _negative_import_solar_diff_is_allowlisted(actual: str) -> bool:
    """Accept only the reviewed 24fcc7d optimiser subset."""
    expected = _git_show(_NEGATIVE_IMPORT_SOLAR_SOURCE, COORDINATOR)
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="private_5ddd1567",
            tofile="negative_import_solar_candidate",
            lineterm="",
        )
    )
    return (
        hashlib.sha256(diff.encode("utf-8")).hexdigest()
        == _NEGATIVE_IMPORT_SOLAR_DIFF_SHA256
    )


def _cost_neutral_reachable_deadline_diff_is_allowlisted(
    expected: str, actual: str
) -> bool:
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="solar_refill_baseline",
            tofile="cost_neutral_reachable_deadline_candidate",
            lineterm="",
        )
    )
    return (
        hashlib.sha256(diff.encode("utf-8")).hexdigest()
        == _COST_NEUTRAL_REACHABLE_DEADLINE_DIFF_SHA256
    )


def _projected_mode_alignment_diff_is_allowlisted(actual: str) -> bool:
    """Accept only the reviewed 2cc05e2b semantic adaptation at this path."""
    expected = _git_show(_PROJECTED_MODE_ALIGNMENT_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="private_e3c17217",
            tofile="projected_mode_alignment_candidate",
            lineterm="",
        )
    )
    return (
        hashlib.sha256(diff.encode("utf-8")).hexdigest()
        == _PROJECTED_MODE_ALIGNMENT_DIFF_SHA256
    )


def _native_solar_clipped_export_diff_is_allowlisted(actual: str) -> bool:
    """Accept only the reviewed 2a53f413 semantic adaptation at this path."""
    expected = _git_show(_NATIVE_SOLAR_CLIPPED_EXPORT_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="private_8eac5f53",
            tofile="native_solar_clipped_export_candidate",
            lineterm="",
        )
    )
    return (
        hashlib.sha256(diff.encode("utf-8")).hexdigest()
        == _NATIVE_SOLAR_CLIPPED_EXPORT_DIFF_SHA256
    )


def _disable_idle_deadline_diff_is_allowlisted(actual: str) -> bool:
    """Accept only the reviewed upstream 2ff8c9d2 optimizer hunk."""
    expected = _git_show(_DISABLE_IDLE_DEADLINE_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="private_25f38811",
            tofile="disable_idle_deadline_candidate",
            lineterm="",
        )
    )
    return (
        hashlib.sha256(diff.encode("utf-8")).hexdigest()
        == _DISABLE_IDLE_DEADLINE_DIFF_SHA256
    )


def _git(*args: str) -> str:
    """Run git with a direct failure for a checkout missing the baseline tag."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pytest.fail(
            "optimizer continuity baseline requires a non-shallow checkout containing tag "
            f"{BASELINE}",
            pytrace=False,
        )
    if completed.returncode:
        pytest.fail(
            "optimizer continuity baseline requires a non-shallow checkout containing "
            f"tag {BASELINE} at {BASELINE_COMMIT}; git {' '.join(args)!r} failed: "
            f"{completed.stderr.strip() or completed.stdout.strip()}",
            pytrace=False,
        )
    return completed.stdout.replace("\r\n", "\n")


def _git_show(revision: str, relative_path: Path) -> str:
    """Read a tracked baseline source file with normalized newlines."""
    return _git("show", f"{revision}:{relative_path.as_posix()}")


def test_core_optimizer_sources_match_the_pre_rename_baseline():
    """Domain restoration must not alter grid/PV/battery optimizer behavior."""
    assert _git("rev-parse", f"{BASELINE}^{{}}").strip() == BASELINE_COMMIT

    baseline_files = sorted(
        relative_name
        for relative_name in _git(
            "ls-tree", "-r", "--name-only", BASELINE, "--", OPTIMIZATION.as_posix()
        ).splitlines()
        if Path(relative_name) not in EXPLANATION_ONLY_MODULES
        and Path(relative_name) != _AMBER_FORECAST_CONFIDENCE_MODULE
    )
    restored_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / OPTIMIZATION).rglob("*.py")
        if path.relative_to(ROOT) not in EXPLANATION_ONLY_MODULES
        and path.relative_to(ROOT) != _AMBER_FORECAST_CONFIDENCE_MODULE
    )

    assert restored_files == baseline_files
    assert hashlib.sha256(
        (ROOT / _AMBER_FORECAST_CONFIDENCE_MODULE).read_bytes()
    ).hexdigest() == _AMBER_FORECAST_CONFIDENCE_SHA256
    for relative_name in baseline_files:
        relative_path = Path(relative_name)
        actual = (ROOT / relative_path).read_text(encoding="utf-8").replace(
            "\r\n", "\n"
        )
        expected = (
            _expected_optimizer_coordinator_source()
            if relative_path == COORDINATOR
            else _expected_battery_optimizer_source()
            if relative_path == BATTERY_OPTIMIZER
            else _git_show(BASELINE_COMMIT, relative_path)
        )
        if relative_path == COORDINATOR:
            source = _git_show(_NEGATIVE_IMPORT_SOLAR_SOURCE, COORDINATOR)
            assert _amber_coordinator_diff_is_allowlisted(expected, source)
            assert _negative_import_solar_diff_is_allowlisted(actual)
        elif relative_path == BATTERY_OPTIMIZER:
            # Preserve proof that e3c17217 itself contains only the earlier,
            # reviewed solar-refill and reachable-deadline changes before
            # allowing the exact projected-mode candidate delta.
            assert _cost_neutral_reachable_deadline_diff_is_allowlisted(
                expected,
                _git_show(_PROJECTED_MODE_ALIGNMENT_SOURCE, BATTERY_OPTIMIZER),
            )
            assert _projected_mode_alignment_diff_is_allowlisted(
                _git_show(_NATIVE_SOLAR_CLIPPED_EXPORT_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _native_solar_clipped_export_diff_is_allowlisted(
                _git_show(_DISABLE_IDLE_DEADLINE_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _disable_idle_deadline_diff_is_allowlisted(actual)
        elif relative_path == COST_NEUTRAL:
            assert _final_solar_credit_diff_is_allowlisted(actual)
        else:
            assert actual == expected


def test_amber_optimizer_allowlist_rejects_an_unreviewed_coordinator_change():
    """The exception is exact; a nearby optimizer edit must fail closed."""
    expected = _expected_optimizer_coordinator_source()
    actual = _git_show(_NEGATIVE_IMPORT_SOLAR_SOURCE, COORDINATOR)

    assert _amber_coordinator_diff_is_allowlisted(expected, actual)
    assert not _amber_coordinator_diff_is_allowlisted(
        expected,
        actual.replace(
            "return protected\n\n    def _provider_priced_reference_prices",
            "return protected\n        # unreviewed optimizer change\n\n    def _provider_priced_reference_prices",
            1,
        ),
    )


def test_negative_import_solar_allowlist_rejects_a_nearby_policy_mutation():
    """The 24fcc7d/d54e87e6 allowance is exact and fails closed."""
    actual = (ROOT / COORDINATOR).read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    )

    assert _negative_import_solar_diff_is_allowlisted(actual)
    assert not _negative_import_solar_diff_is_allowlisted(
        actual.replace("from ..const import (\n    DOMAIN,", "from ..const import (", 1)
    )
    assert not _negative_import_solar_diff_is_allowlisted(
        actual.replace(
            "enabled=bool(production and production.can_project()),",
            "enabled=True,",
            1,
        )
    )


def test_solar_only_refill_allowlist_rejects_a_nearby_predicate_mutation():
    """The solar-refill exception is an exact reviewed source variant."""
    expected = _expected_battery_optimizer_source()
    actual = _git_show(_PROJECTED_MODE_ALIGNMENT_SOURCE, BATTERY_OPTIMIZER)

    assert _cost_neutral_reachable_deadline_diff_is_allowlisted(expected, actual)
    assert not _cost_neutral_reachable_deadline_diff_is_allowlisted(
        expected,
        actual.replace(
            "acquisition_cost_kwh > 0",
            "acquisition_cost_kwh >= 0",
            1,
        ),
    )


def test_cost_neutral_deadline_allowlist_rejects_a_nearby_mode_mutation():
    """The b20bffb2 exception is exact rather than a general optimizer waiver."""
    expected = _expected_battery_optimizer_source()
    actual = _git_show(_PROJECTED_MODE_ALIGNMENT_SOURCE, BATTERY_OPTIMIZER)

    assert _cost_neutral_reachable_deadline_diff_is_allowlisted(expected, actual)
    assert not _cost_neutral_reachable_deadline_diff_is_allowlisted(
        expected,
        actual.replace(
            "b_ub.append(1.0)",
            "b_ub.append(0.0)",
            1,
        ),
    )


def test_projected_mode_alignment_allowlist_rejects_a_nearby_flow_mutation():
    """The 2cc05e2b bridge remains an exact path/symbol-specific allowance."""
    actual = _git_show(_NATIVE_SOLAR_CLIPPED_EXPORT_SOURCE, BATTERY_OPTIMIZER)

    assert _projected_mode_alignment_diff_is_allowlisted(actual)
    assert not _projected_mode_alignment_diff_is_allowlisted(
        actual.replace(
            'if action in ("export", "solar_export"):',
            'if action == "export":',
            1,
        )
    )


def test_native_solar_clipped_export_allowlist_rejects_a_nearby_flow_mutation():
    """The 2a53f413 allowance fails closed outside its exact bounded hunk."""
    actual = _git_show(_DISABLE_IDLE_DEADLINE_SOURCE, BATTERY_OPTIMIZER)

    assert _native_solar_clipped_export_diff_is_allowlisted(actual)
    assert not _native_solar_clipped_export_diff_is_allowlisted(
        actual.replace(
            "native_solar_surplus_kw = max(0.0, solar[t] - load[t])",
            "native_solar_surplus_kw = 0.0",
            1,
        )
    )


def test_disable_idle_deadline_allowlist_rejects_a_nearby_policy_mutation():
    """The 2ff8c9d2 allowance fails closed outside its exact reviewed hunk."""
    actual = (ROOT / BATTERY_OPTIMIZER).read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    )

    assert _disable_idle_deadline_diff_is_allowlisted(actual)
    assert not _disable_idle_deadline_diff_is_allowlisted(
        actual.replace("not disable_idle", "disable_idle", 1)
    )


def test_final_solar_credit_allowlist_rejects_a_nearby_policy_mutation():
    actual = (ROOT / COST_NEUTRAL).read_text(encoding="utf-8")
    assert _final_solar_credit_diff_is_allowlisted(actual)
    assert not _final_solar_credit_diff_is_allowlisted(
        actual.replace("nonnegative=False", "nonnegative=True", 1)
    )


def test_dashboard_assets_are_served_from_restored_power_sync_namespace():
    """Existing Lovelace resources must keep their original public URLs."""
    init_source = (COMPONENT / "__init__.py").read_text()
    strategy_source = (COMPONENT / "frontend" / "power-sync-strategy.js").read_text()

    assert (COMPONENT / "frontend" / "power-sync-strategy.js").is_file()
    assert (COMPONENT / "frontend" / "power-sync-energy-flow.js").is_file()
    assert 'StaticPathConfig("/power_sync/frontend", frontend_dir, True)' in init_source
    assert 'hass.http.register_static_path("/power_sync/frontend", frontend_dir, True)' in init_source
    assert '"/power_sync/frontend/power-sync-strategy.js"' in init_source
    assert '"/power_sync/frontend/power-sync-energy-flow.js"' in init_source
    assert "service: 'power_sync.force_charge'" in strategy_source
    assert "service: 'power_sync.force_discharge'" in strategy_source
    assert "powersync_nir" not in init_source
    assert "powersync_nir" not in strategy_source
