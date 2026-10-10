"""Behavior tests for pure shared-loadpoint observation reconciliation."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "custom_components"
    / "powersync_nir"
    / "automations"
    / "external_session_reconciler.py"
)
SPEC = importlib.util.spec_from_file_location("powersync_external_session_reconciler_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


UTC = timezone.utc
NOW = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)


def test_fresh_positive_generic_power_without_powersync_command_is_external() -> None:
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=7.2,
        observed_at=NOW,
        now=NOW,
    )

    state = module.reconcile_shared_external_session(observation)

    assert state.physical_active is True
    assert state.origin == "external"


def test_fresh_positive_generic_power_with_powersync_command_is_powersync() -> None:
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=7.2,
        observed_at=NOW,
        now=NOW,
    )

    state = module.reconcile_shared_external_session(
        observation,
        powersync_command_observed=True,
    )

    assert state.physical_active is True
    assert state.origin == "powersync"


@pytest.mark.parametrize(
    ("power_kw", "observed_at"),
    [
        (7.2, NOW - timedelta(seconds=91)),
        (None, NOW),
    ],
)
def test_stale_or_missing_power_makes_pending_stop_indeterminate(
    power_kw: float | None,
    observed_at: datetime,
) -> None:
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=power_kw,
        observed_at=observed_at,
        now=NOW,
    )
    previous = module.ReconciliationState(
        origin="powersync",
        physical_active=True,
        stop_outcome={"status": "pending"},
    )

    state = module.reconcile_shared_external_session(observation, previous=previous)

    assert state.physical_active is None
    assert state.origin == "unknown"
    assert state.stop_outcome == {"status": "indeterminate"}


def test_fresh_zero_power_confirms_pending_stop() -> None:
    observation = module.generic_power_observation(
        binding_id="garage",
        power_kw=0.0,
        observed_at=NOW,
        now=NOW,
    )
    previous = module.ReconciliationState(
        origin="powersync",
        physical_active=True,
        stop_outcome={"status": "pending"},
    )

    state = module.reconcile_shared_external_session(observation, previous=previous)

    assert state.physical_active is False
    assert state.stop_outcome == {"status": "confirmed"}
