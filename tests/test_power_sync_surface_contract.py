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
LOAD_ESTIMATOR = OPTIMIZATION / "load_estimator.py"
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

# Exact upstream ad8b870e bounded HA Store writer; not an optimizer control module.
_BOUNDED_ACCOUNTING_STORE_MODULE = OPTIMIZATION / "coalescing_store.py"
_BOUNDED_ACCOUNTING_STORE_SHA256 = (
    "792662bdf59bc0e6971c99cb2b203fd5ec25b40c44e1d959e04b7251733e9c39"
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

# Exact generic slot-cap adaptation of upstream 2c875c9b. The prior private
# optimizer contract is checked independently before allowing this delta.
_MANAGED_EV_HEADROOM_SOURCE = "fb4684ff9ac2b582b6e32543fcf07523d9dfb84d"
_MANAGED_EV_HEADROOM_DIFF_SHA256 = (
    "4627a4eeb4353c6f305da989d0f4ef053c68dd5a3cf7a79f062d2223b3294fde"
)

# Exact generic total-grid leveling adaptation of upstream b50a2cba. The
# preceding 2c875c9b source is checked separately; no Tesla actuator follows.
# Also includes only the two reviewed vendor-neutral acknowledgement log lines
# from upstream 9595199b, opt-in solar correction 6f944b49, and measured
# solar provenance through export replans cc49c3d0;
# this exact digest admits no other source change.
_TOTAL_GRID_IMPORT_SOURCE = "11a227e4921164e207d19ee3244d0890bf77cd8c"
_TOTAL_GRID_IMPORT_DIFF_SHA256 = (
    "728003bfc97ff32c4028422226672ca2202ea242fd4d5f93191ed9edba9c5087"
)

# Exact upstream 9c3eef13 EV-integration toggle guard applied before the
# private selected-logical-profile filter. Preserve the previous coordinator
# digest independently and admit only this reviewed four-line source delta.
_EV_PLAN_TOGGLE_SOURCE = "f3099045aa04907f38f726ee12e59afe3965a59b"
_EV_PLAN_TOGGLE_DIFF_SHA256 = (
    "47b7cb350e25757a1c93e83b3ce0ad1f5851beff9e6bcad7cd427ccc14ed35bb"
)

# Reviewed 4cb9124e telemetry-only provenance reconciliation and passive
# shutdown persistence, adapted without the adjacent licensing recovery path.
# Preserve the preceding no-paywall source exactly before admitting this delta.
_PROVENANCE_LIFECYCLE_SOURCE = "b1bcf8ce3d7873bb07d9b9b98f9ab321caa0f669"
_PROVENANCE_LIFECYCLE_DIFF_SHA256 = (
    "a0caf3b3e504162a5ca10cbdd0bf1cb70e556847817c313138b9a2e6c6b76249"
)

# Exact coordinator delta from upstream ad8b870e: four delayed stores and import.
# Preserve the preceding no-paywall source check as a separate assertion.
_BOUNDED_ACCOUNTING_STORE_SOURCE = "5af1b092036a2cd0630128d7035ee8019245e155"
_BOUNDED_ACCOUNTING_STORE_DIFF_SHA256 = (
    "b6eec943580454010b21627a2e419db0717c32f31ef4c871b919276f19c359a2"
)

# Exact upstream 73981018 stale-SoC deferral, preserving the fork's measured
# solar-export debit and all preceding no-paywall coordinator checks.
_STALE_SOC_DEFERRAL_SOURCE = "306dc3606397c3bde66476bc80095f48e101f68e"
_STALE_SOC_DEFERRAL_DIFF_SHA256 = (
    "55d5e99469ce14044315219e1f43fdd815e8d3415db42be9dd7a7032f1500604"
)

# Upstream 1941e867: expose forecast inputs for the chart only on greedy
# fallback; preserve the exact reviewed no-paywall optimizer source beneath it.
_SOLAR_FALLBACK_SOURCE = "4ce4b3c14ea563e87c1de8cec31e3e459b916f40"
_SOLAR_FALLBACK_DIFF_SHA256 = (
    "f899eef7b42b051f5b8572864fde4293bb59ad211be0414bb2fa6ac811203b6f"
)

# Upstream 6ae4d9d5's quota-aware forecast selection and status, reviewed on
# the exact preceding private source. The fork deliberately has no upstream
# no_solar_installed feature; its absence remains part of this exact digest.
_SOLAR_QUOTA_SOURCE = "3bf78c571f03e7ff7c2ba2b488c1ecb562d8d563"
_SOLAR_QUOTA_COORDINATOR_DIFF_SHA256 = (
    "30228543c9cd8c3b47d4709c95ac9031255fe53d119f3ff9b1fb154a7dc6c889"
)
_SOLAR_QUOTA_ESTIMATOR_DIFF_SHA256 = (
    "1be6f5406ecdf42b7dca291f08c93b36ffa7a96f84023743c0e0ae4afb8320f2"
)

# Upstream e524451b: keep measured battery provenance pending through stale-SoC
# optimizer runs, retaining the fork's solar-export debit. Anchor this exact
# reviewed delta to the preceding private coordinator, not the upstream source.
_PENDING_SOC_SOURCE = "3c8dc3e23362c22d70e4a0ec2a30b3542564c847"
_PENDING_SOC_DIFF_SHA256 = (
    "fee74206fff6a8eb6d075e5c16fa97fdbb94c7b3f775e0f5e0d1e0cdf2acb2a7"
)

# Upstream fbdd9f7d EV-preservation transition refresh, adapted without its
# licensing hooks against the exact private pending-SoC successor.
_EV_PRESERVE_SOURCE = "8228643d9525477723b6f206bc3a6900648c6b36"
_EV_PRESERVE_DIFF_SHA256 = (
    "0754d6aa88cf0826690c7e44f86f3d4a178945c5b5357092306a472b2c2f2fd3"
)

# Upstream cddd6a13: exact passive measured-cost listener delta, after the
# previously published solar and shared-loadpoint safeguards.
_MEASURED_COST_SOURCE = "34fb3bfaaf3b5f1bdccc3460db93b63ed2702edf"
_MEASURED_COST_DIFF_SHA256 = "458200be2286b87870c9d5652084e16cd0e06b4e9cafb8c14c7b3ef02d34012f"


def _measured_cost_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_MEASURED_COST_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_34fb3bfa", tofile="measured_cost_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _MEASURED_COST_DIFF_SHA256


# Upstream 813ad249: only the reviewed hypothetical-curtailment cap removal,
# anchored after the existing EV-preservation lineage.
_AVAILABLE_SOLAR_SOURCE = "60d4075f8ae2f2a0c487606ebfdd3168c98fa16c"
_AVAILABLE_SOLAR_DIFF_SHA256 = "911eb13edbebef3f36cda57cd6fac26c18f03b1dc95af84a9ffdcc91f5c74f78"

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
# final solar credits constrain discretionary exports, and cc49c3d0 funds
# active export from measured opening solar. No broader delta is admitted.
_DISABLE_IDLE_DEADLINE_SOURCE = "25f388110c1159fbaf08d614e77af6ef4dc32f03"
_DISABLE_IDLE_DEADLINE_DIFF_SHA256 = (
    "8fd4ca651f22488562539ee2da272603038693d0f508bcb0510835c34281bc39"
)

# Upstream e7375697, reviewed against the exact private 905545c3 source:
# protected generic exports credit only earlier physically stored solar. The
# prior measured-opening priority budget and no-paywall optimizer stay intact.
_PROTECTED_SOLAR_EXPORT_SOURCE = "905545c3dbcc51226feb4aa558b47c7e01500c1a"
_PROTECTED_SOLAR_EXPORT_DIFF_SHA256 = (
    "5d1809951bddc75220b0de80cb224e5d55fa8229dde4e927d0a7173147247ee3"
)

# Upstream 6fc7f0a5: exact fallback solar ordering and SOC projection delta.
_SOLAR_FALLBACK_DISPATCH_SOURCE = "cce8559018b5b7c2608c05dd0cfdf269efa8a3f3"
_SOLAR_FALLBACK_DISPATCH_SHA256 = "326fb596511c1f43b54e7af20e279d9f87095a2dcd1bb6b6297f326ceefaaf61"

# Upstream 5de3b03a: disjoint EV surplus selector columns only, based on the
# candidate before this port. The predecessor remains separately validated.
_EV_SELECTOR_SOURCE = "21b70acf925356a998b17a497a922742ceb6e4f3"
_EV_SELECTOR_SHA256 = "5511ed0edbf401190f8ebbb5c721d5e180e46ec0def555c613b99eb4002f29d3"

# Upstream 9c156fe7: cycle timing and opt-in benchmark instrumentation.
_SOLVER_TRACE_SOURCE = "c0cf4bae0cf455c0a9f40c03e71eb5024f5b9fa4"
_SOLVER_TRACE_SHA256 = "649e38c37f78997af52008c351cb2c1752e63d427664fb77c0be79df6af29565"

# Upstream f55a783e: bulk model loading and validated tie-break incumbents.
_BULK_SOLVER_SOURCE = "322bb058df5d6c56c0e3977f431649821fee4e92"
_BULK_SOLVER_SHA256 = "2dec933b1166b4b9753c924033433ba86e319d8c862690522b718f4419a6217f"

# Upstream 7371f0c9: higher-value fallback exports within the cap.
_FALLBACK_EXPORT_SOURCE = "55d65a6e6a36d48b79613ea18278998b18394022"
_FALLBACK_EXPORT_SHA256 = "ffc0c26454a2aa38558cd80901d661e62148f4c0d2aad2f6463a4f02c7714af4"

# Upstream 246de0cf: bound export timing preference under Cost Neutral.
_BOUNDED_TIME_SOURCE = "9e3248b711b7791a8a63d1e4111e77defb6cedb5"
_BOUNDED_TIME_SHA256 = "24fec92d4332f7298139ee3f7bb1eadb8c236ff23ad33d60e72e4410eb0f9221"

# Exact upstream 52465064 plan-schema delta. Legacy no-solar callers remain
# supported; this digest does not waive changes elsewhere in cost_neutral.py.
COST_NEUTRAL = OPTIMIZATION / "cost_neutral.py"
_FINAL_SOLAR_CREDIT_SOURCE = "608042abefd68d5de6edbc2fb5f4aafb107c1e58"
_FINAL_SOLAR_CREDIT_DIFF_SHA256 = (
    "a00a1d81861473f06fa6f9cc6414c6af858b1b9e9bdb5f54b03d3ed315ebc9f0"
)


# Upstream a10bb059 moves cached Solcast parsing off the HA loop. The
# predecessor remains separately checked against the quota-selection lineage.
_SOLCAST_EXECUTOR_SOURCE = "0f3da17ce62776065d95b2db8fd4e910ba23bfd1"
_SOLCAST_EXECUTOR_DIFF_SHA256 = "95b9ee9ae13e025912bc411cbf95080e93962811b71aa6b6f915455832a77bca"


def _solcast_executor_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_SOLCAST_EXECUTOR_SOURCE, LOAD_ESTIMATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_0f3da17c", tofile="solcast_executor_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _SOLCAST_EXECUTOR_DIFF_SHA256


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


def _managed_ev_headroom_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_MANAGED_EV_HEADROOM_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_fb4684ff", tofile="managed_ev_headroom_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _MANAGED_EV_HEADROOM_DIFF_SHA256


def _total_grid_import_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_TOTAL_GRID_IMPORT_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_11a227e4", tofile="total_grid_import_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _TOTAL_GRID_IMPORT_DIFF_SHA256


def _ev_plan_toggle_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_EV_PLAN_TOGGLE_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_f3099045", tofile="ev_plan_toggle_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _EV_PLAN_TOGGLE_DIFF_SHA256


def _provenance_lifecycle_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_PROVENANCE_LIFECYCLE_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_b1bcf8ce", tofile="provenance_lifecycle_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _PROVENANCE_LIFECYCLE_DIFF_SHA256


def _bounded_accounting_store_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_BOUNDED_ACCOUNTING_STORE_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_5af1b092", tofile="bounded_store_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _BOUNDED_ACCOUNTING_STORE_DIFF_SHA256


def _stale_soc_deferral_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_STALE_SOC_DEFERRAL_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_306dc360", tofile="stale_soc_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _STALE_SOC_DEFERRAL_DIFF_SHA256


def _solar_fallback_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_SOLAR_FALLBACK_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_4ce4b3c1", tofile="solar_fallback_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _SOLAR_FALLBACK_DIFF_SHA256


def _solar_quota_diff_is_allowlisted(path: Path, actual: str) -> bool:
    assert path in (COORDINATOR, LOAD_ESTIMATOR)
    expected = _git_show(_SOLAR_QUOTA_SOURCE, path)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile=f"private_{_SOLAR_QUOTA_SOURCE[:8]}",
        tofile=f"solar_quota_{path.stem}_candidate", lineterm="",
    ))
    digest = (
        _SOLAR_QUOTA_COORDINATOR_DIFF_SHA256 if path == COORDINATOR
        else _SOLAR_QUOTA_ESTIMATOR_DIFF_SHA256
    )
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == digest


def _pending_soc_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_PENDING_SOC_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_3c8dc3e2", tofile="pending_soc_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _PENDING_SOC_DIFF_SHA256


def _ev_preserve_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_EV_PRESERVE_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_8228643d", tofile="ev_preserve_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _EV_PRESERVE_DIFF_SHA256


def _available_solar_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_AVAILABLE_SOLAR_SOURCE, COORDINATOR)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_60d4075f", tofile="available_solar_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _AVAILABLE_SOLAR_DIFF_SHA256


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


def _solar_fallback_dispatch_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_SOLAR_FALLBACK_DISPATCH_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="private_cce85590",
        tofile="solar_fallback_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _SOLAR_FALLBACK_DISPATCH_SHA256


def _ev_selector_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_EV_SELECTOR_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="private_21b70acf",
        tofile="selector_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _EV_SELECTOR_SHA256


def _solver_trace_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_SOLVER_TRACE_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="private_c0cf4bae",
        tofile="solver_trace_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _SOLVER_TRACE_SHA256


def _bulk_solver_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_BULK_SOLVER_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="private_322bb058",
        tofile="bulk_solver_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _BULK_SOLVER_SHA256


def _fallback_export_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_FALLBACK_EXPORT_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="private_55d65a6e",
        tofile="fallback_export_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _FALLBACK_EXPORT_SHA256


def _bounded_time_diff_is_allowlisted(actual: str) -> bool:
    expected = _git_show(_BOUNDED_TIME_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="private_9e3248b7",
        tofile="bounded_time_candidate", lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _BOUNDED_TIME_SHA256


def _protected_solar_export_diff_is_allowlisted(actual: str) -> bool:
    """Only the reviewed no-paywall protected-export source delta is allowed."""
    expected = _git_show(_PROTECTED_SOLAR_EXPORT_SOURCE, BATTERY_OPTIMIZER)
    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(), actual.splitlines(),
        fromfile="private_905545c3", tofile="protected_solar_export_candidate",
        lineterm="",
    ))
    return hashlib.sha256(diff.encode("utf-8")).hexdigest() == _PROTECTED_SOLAR_EXPORT_DIFF_SHA256


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
        and Path(relative_name) != _BOUNDED_ACCOUNTING_STORE_MODULE
    )
    restored_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / OPTIMIZATION).rglob("*.py")
        if path.relative_to(ROOT) not in EXPLANATION_ONLY_MODULES
        and path.relative_to(ROOT) != _AMBER_FORECAST_CONFIDENCE_MODULE
        and path.relative_to(ROOT) != _BOUNDED_ACCOUNTING_STORE_MODULE
    )

    assert restored_files == baseline_files
    assert hashlib.sha256(
        (ROOT / _AMBER_FORECAST_CONFIDENCE_MODULE).read_bytes()
    ).hexdigest() == _AMBER_FORECAST_CONFIDENCE_SHA256
    assert hashlib.sha256(
        (ROOT / _BOUNDED_ACCOUNTING_STORE_MODULE).read_bytes()
    ).hexdigest() == _BOUNDED_ACCOUNTING_STORE_SHA256
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
            assert _negative_import_solar_diff_is_allowlisted(
                _git_show(_MANAGED_EV_HEADROOM_SOURCE, COORDINATOR)
            )
            assert _managed_ev_headroom_diff_is_allowlisted(
                _git_show(_TOTAL_GRID_IMPORT_SOURCE, COORDINATOR)
            )
            assert _total_grid_import_diff_is_allowlisted(
                _git_show(_EV_PLAN_TOGGLE_SOURCE, COORDINATOR)
            )
            assert _ev_plan_toggle_diff_is_allowlisted(
                _git_show(_PROVENANCE_LIFECYCLE_SOURCE, COORDINATOR)
            )
            assert _provenance_lifecycle_diff_is_allowlisted(
                _git_show(_BOUNDED_ACCOUNTING_STORE_SOURCE, COORDINATOR)
            )
            assert _bounded_accounting_store_diff_is_allowlisted(
                _git_show(_STALE_SOC_DEFERRAL_SOURCE, COORDINATOR)
            )
            assert _stale_soc_deferral_diff_is_allowlisted(
                _git_show(_SOLAR_FALLBACK_SOURCE, COORDINATOR)
            )
            assert _solar_fallback_diff_is_allowlisted(
                _git_show(_SOLAR_QUOTA_SOURCE, COORDINATOR)
            )
            assert _solar_quota_diff_is_allowlisted(
                COORDINATOR, _git_show(_PENDING_SOC_SOURCE, COORDINATOR)
            )
            assert _pending_soc_diff_is_allowlisted(
                _git_show(_EV_PRESERVE_SOURCE, COORDINATOR)
            )
            assert _ev_preserve_diff_is_allowlisted(
                _git_show(_AVAILABLE_SOLAR_SOURCE, COORDINATOR)
            )
            assert _available_solar_diff_is_allowlisted(_git_show(_MEASURED_COST_SOURCE, COORDINATOR))
            assert _measured_cost_diff_is_allowlisted(actual)
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
            assert _disable_idle_deadline_diff_is_allowlisted(
                _git_show(_PROTECTED_SOLAR_EXPORT_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _protected_solar_export_diff_is_allowlisted(
                _git_show(_SOLAR_FALLBACK_DISPATCH_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _solar_fallback_dispatch_diff_is_allowlisted(
                _git_show(_EV_SELECTOR_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _ev_selector_diff_is_allowlisted(
                _git_show(_SOLVER_TRACE_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _solver_trace_diff_is_allowlisted(
                _git_show(_BULK_SOLVER_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _bulk_solver_diff_is_allowlisted(
                _git_show(_FALLBACK_EXPORT_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _fallback_export_diff_is_allowlisted(
                _git_show(_BOUNDED_TIME_SOURCE, BATTERY_OPTIMIZER)
            )
            assert _bounded_time_diff_is_allowlisted(actual)
        elif relative_path == COST_NEUTRAL:
            assert _final_solar_credit_diff_is_allowlisted(actual)
        elif relative_path == LOAD_ESTIMATOR:
            assert _solar_quota_diff_is_allowlisted(
                LOAD_ESTIMATOR, _git_show(_SOLCAST_EXECUTOR_SOURCE, LOAD_ESTIMATOR)
            )
            assert _solcast_executor_diff_is_allowlisted(actual)
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
    prior = _git_show(_MANAGED_EV_HEADROOM_SOURCE, COORDINATOR)

    assert _negative_import_solar_diff_is_allowlisted(prior)
    headroom = _git_show(_TOTAL_GRID_IMPORT_SOURCE, COORDINATOR)
    assert _managed_ev_headroom_diff_is_allowlisted(headroom)
    assert not _managed_ev_headroom_diff_is_allowlisted(
        headroom.replace("- load_w - ev_w + solar_w", "- load_w + solar_w", 1)
    )
    assert _total_grid_import_diff_is_allowlisted(
        _git_show(_EV_PLAN_TOGGLE_SOURCE, COORDINATOR)
    )
    assert _ev_plan_toggle_diff_is_allowlisted(
        _git_show(_PROVENANCE_LIFECYCLE_SOURCE, COORDINATOR)
    )
    assert _provenance_lifecycle_diff_is_allowlisted(
        _git_show(_BOUNDED_ACCOUNTING_STORE_SOURCE, COORDINATOR)
    )
    assert _bounded_accounting_store_diff_is_allowlisted(
        _git_show(_STALE_SOC_DEFERRAL_SOURCE, COORDINATOR)
    )
    assert _stale_soc_deferral_diff_is_allowlisted(
        _git_show(_SOLAR_FALLBACK_SOURCE, COORDINATOR)
    )
    assert _solar_fallback_diff_is_allowlisted(
        _git_show(_SOLAR_QUOTA_SOURCE, COORDINATOR)
    )
    assert _solar_quota_diff_is_allowlisted(
        COORDINATOR, _git_show(_PENDING_SOC_SOURCE, COORDINATOR)
    )
    pending = _git_show(_EV_PRESERVE_SOURCE, COORDINATOR)
    assert _pending_soc_diff_is_allowlisted(pending)
    assert not _pending_soc_diff_is_allowlisted(
        pending.replace('reason in ("measured_interval", "optimizer_run")',
                       'reason == "measured_interval"', 1)
    )
    assert not _pending_soc_diff_is_allowlisted(
        pending.replace('or solar_export > 1e-9', '', 1)
    )
    ev_preserve = _git_show(_AVAILABLE_SOLAR_SOURCE, COORDINATOR)
    assert _ev_preserve_diff_is_allowlisted(ev_preserve)
    retry_call = 'await self._release_scheduled_ev_no_discharge_mode("optimizer disabled retry")'
    assert retry_call in ev_preserve
    assert not _ev_preserve_diff_is_allowlisted(ev_preserve.replace(retry_call, 'pass', 1))
    assert not _ev_preserve_diff_is_allowlisted(
        ev_preserve.replace('execution_trigger="ev_preservation"',
                       'execution_trigger="other"', 1)
    )
    assert not _ev_preserve_diff_is_allowlisted(
        ev_preserve.replace('if not getattr(self, "_ev_preserve_refresh_executing", False):',
                       'if True:', 1)
    )
    assert not _ev_preserve_diff_is_allowlisted(
        ev_preserve.replace('self._scheduled_ev_no_discharge_uncertain = True',
                       'self._scheduled_ev_no_discharge_uncertain = False', 1)
    )
    assert not _ev_preserve_diff_is_allowlisted(
        ev_preserve.replace('if active == applied and not (uncertain and not active):',
                       'if active == applied:', 1)
    )
    predecessor = _git_show(_MEASURED_COST_SOURCE, COORDINATOR)
    assert _available_solar_diff_is_allowlisted(predecessor)
    assert not _available_solar_diff_is_allowlisted(predecessor.replace(
        "enabled=bool(production and production.can_project()),", "enabled=True,", 1
    ))
    assert _measured_cost_diff_is_allowlisted(actual)
    assert not _measured_cost_diff_is_allowlisted(actual.replace(
        "self._track_actual_cost(force=True)", "self._track_actual_cost(force=False)", 1
    ))
    assert not _measured_cost_diff_is_allowlisted(actual.replace(
        "self._cost_tracking_stopping = True", "self._cost_tracking_stopping = False", 1
    ))
    assert not _solar_fallback_diff_is_allowlisted(
        _git_show(_SOLAR_QUOTA_SOURCE, COORDINATOR).replace(
            'getattr(self, "_ev_integration_enabled", False)', 'True', 1
        )
    )
    assert not _solar_fallback_diff_is_allowlisted(
        _git_show(_SOLAR_QUOTA_SOURCE, COORDINATOR).replace(
            'self._cost_store = CoalescingStore(', 'self._cost_store = Store(', 1
        )
    )
    assert not _total_grid_import_diff_is_allowlisted(
        _git_show(_EV_PLAN_TOGGLE_SOURCE, COORDINATOR).replace("middle - base", "middle", 1)
    )
    assert not _negative_import_solar_diff_is_allowlisted(
        prior.replace("from ..const import (\n    DOMAIN,", "from ..const import (", 1)
    )
    assert not _negative_import_solar_diff_is_allowlisted(
        prior.replace(
            "enabled=bool(production and production.can_project()),",
            "enabled=True,",
            1,
        )
    )


def test_solar_quota_allowlists_reject_nearby_unreviewed_changes():
    """Both forecast selection and optimizer status stay predecessor-anchored."""
    for path, source, mutation in (
        (COORDINATOR, 'reason == "solcast_quota_exhausted"', 'reason != "solcast_quota_exhausted"'),
        (LOAD_ESTIMATOR, 'return any(quotas)', 'return all(quotas)'),
    ):
        actual = (
            _git_show(_PENDING_SOC_SOURCE, COORDINATOR)
            if path == COORDINATOR
            else _git_show(_SOLCAST_EXECUTOR_SOURCE, LOAD_ESTIMATOR)
        )
        assert _solar_quota_diff_is_allowlisted(path, actual)
        assert source in actual
        assert not _solar_quota_diff_is_allowlisted(path, actual.replace(source, mutation, 1))


def test_solcast_executor_allowlist_rejects_unreviewed_changes():
    actual = (ROOT / LOAD_ESTIMATOR).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert _solcast_executor_diff_is_allowlisted(actual)
    for source, mutation in (
        ('snapshot = [dict(period) for period in cached]', 'snapshot = list(cached)'),
        ('return any(quotas)', 'return all(quotas)'),
    ):
        assert source in actual
        assert not _solcast_executor_diff_is_allowlisted(actual.replace(source, mutation, 1))


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
    actual = _git_show(_PROTECTED_SOLAR_EXPORT_SOURCE, BATTERY_OPTIMIZER)

    assert _disable_idle_deadline_diff_is_allowlisted(actual)
    assert not _disable_idle_deadline_diff_is_allowlisted(
        actual.replace("not disable_idle", "disable_idle", 1)
    )


def test_protected_solar_export_allowlist_rejects_source_mutations():
    """No nearby change to source credit or private priority budget slips in."""
    actual = _git_show(_SOLAR_FALLBACK_DISPATCH_SOURCE, BATTERY_OPTIMIZER)
    assert _protected_solar_export_diff_is_allowlisted(actual)
    for before, after in (
        ("future_stored_energy_var(t)] = -1.0", "future_stored_energy_var(t)] = 0.0"),
        ("initial_solar_output_kwh if t in initial_solar_slots", "0.0 if t in initial_solar_slots"),
    ):
        assert before in actual
        assert not _protected_solar_export_diff_is_allowlisted(actual.replace(before, after, 1))


def test_solar_fallback_dispatch_allowlist_rejects_mutations():
    actual = _git_show(_EV_SELECTOR_SOURCE, BATTERY_OPTIMIZER)
    assert _solar_fallback_dispatch_diff_is_allowlisted(actual)
    for before, after in (
        ("if not solar_only or solar[t] > load[t]", "if not solar_only or solar[t] >= load[t]"),
        ("output_headroom_kwh[future_idx]", "0.0"),
    ):
        assert before in actual
        assert not _solar_fallback_dispatch_diff_is_allowlisted(actual.replace(before, after, 1))


def test_ev_selector_allowlist_rejects_mutations():
    actual = _git_show(_SOLVER_TRACE_SOURCE, BATTERY_OPTIMIZER)
    assert _ev_selector_diff_is_allowlisted(actual)
    before = "cost_neutral_surplus_sign_offset = next_offset"
    assert before in actual
    assert not _ev_selector_diff_is_allowlisted(actual.replace(before, before + " + 1", 1))


def test_solver_trace_allowlist_rejects_mutations():
    actual = _git_show(_BULK_SOLVER_SOURCE, BATTERY_OPTIMIZER)
    assert _solver_trace_diff_is_allowlisted(actual)
    before = 'h.setOptionValue("time_limit", float(time_limit))'
    assert before in actual
    assert not _solver_trace_diff_is_allowlisted(actual.replace(before, before + "  # changed", 1))


def test_bulk_solver_allowlist_rejects_mutations():
    actual = _git_show(_FALLBACK_EXPORT_SOURCE, BATTERY_OPTIMIZER)
    assert _bulk_solver_diff_is_allowlisted(actual)
    before = 'economic_limit = float(result.fun) + 1e-6'
    assert before in actual
    assert not _bulk_solver_diff_is_allowlisted(actual.replace(before, before + ' + 1', 1))


def test_fallback_export_allowlist_rejects_mutations():
    actual = _git_show(_BOUNDED_TIME_SOURCE, BATTERY_OPTIMIZER)
    assert _fallback_export_diff_is_allowlisted(actual)
    before = 'prefer_higher_prices=True,'
    assert before in actual
    assert not _fallback_export_diff_is_allowlisted(actual.replace(before, 'prefer_higher_prices=False,', 1))


def test_bounded_time_allowlist_rejects_mutations():
    actual = (ROOT / BATTERY_OPTIMIZER).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert _bounded_time_diff_is_allowlisted(actual)
    before = 'export_eps /= max(1, p_n)'
    assert before in actual
    assert not _bounded_time_diff_is_allowlisted(actual.replace(before, 'export_eps *= max(1, p_n)', 1))


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
