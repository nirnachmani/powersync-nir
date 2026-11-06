"""Unresolved-stop notifications are separate from command-result warnings."""
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = spec_from_file_location("unverified_action_events", Path(__file__).parents[1] / "custom_components/power_sync/action_events.py")
action_events = module_from_spec(spec)
spec.loader.exec_module(action_events)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_warns_only_at_two_minutes_and_once_per_episode(monkeypatch):
    notification = Mock()
    monkeypatch.setattr(action_events, "_notification", notification)
    hass = SimpleNamespace(data={})
    entry = SimpleNamespace(entry_id="entry")
    def update(seconds):
        action_events.update_unverified_stop_alert(
            hass, entry, "generic_ev", now=T0 + timedelta(seconds=seconds),
            first_stop_at=T0, episode_id="episode-a", status="unresolved",
            observation=None,
        )
    update(119)
    notification.assert_not_called()
    update(120)
    update(180)
    assert notification.call_count == 1
    assert "telemetry" in notification.call_args.kwargs["reason"].lower()


def test_verified_before_deadline_cannot_be_rearmed_by_stale_retry(monkeypatch):
    notices = Mock()
    monkeypatch.setattr(action_events, "_notification", notices)
    hass, entry = SimpleNamespace(data={}), SimpleNamespace(entry_id="entry")
    def update(status, now, observation=None):
        action_events.update_unverified_stop_alert(
            hass, entry, "generic_ev", now=now, first_stop_at=T0,
            episode_id="a", status=status, observation=observation)
    update("verified", T0 + timedelta(seconds=60),
           {"episode_id": "a", "observed_at": T0 + timedelta(seconds=59), "charging": False})
    update("unresolved", T0 + timedelta(seconds=130))
    notices.assert_not_called()


def test_observed_charging_and_episode_isolation(monkeypatch):
    notices = Mock()
    monkeypatch.setattr(action_events, "_notification", notices)
    hass, entry = SimpleNamespace(data={}), SimpleNamespace(entry_id="entry")
    def update(episode, loadpoint="generic_ev", **overrides):
        params = dict(now=T0 + timedelta(seconds=120), first_stop_at=T0,
                      episode_id=episode, status="unresolved", observation=None)
        params.update(overrides)
        action_events.update_unverified_stop_alert(hass, entry, loadpoint, **params)
    obs = {"episode_id": "a", "observed_at": T0 + timedelta(seconds=30), "charging": True}
    update("a", observation=obs)
    assert "reported charging" in notices.call_args.kwargs["reason"]
    first_id = notices.call_args.kwargs["notification_id"]
    update("a", first_stop_at=T0 + timedelta(seconds=100))  # retry doesn't reset
    assert notices.call_count == 1
    update("b")
    second_id = notices.call_args.kwargs["notification_id"]
    update("a", loadpoint="sigenergy_charger")
    third_id = notices.call_args.kwargs["notification_id"]
    assert len({first_id, second_id, third_id}) == 3


def test_only_matching_verified_post_stop_idle_clears_matching_warning(monkeypatch):
    notices = Mock()
    monkeypatch.setattr(action_events, "_notification", notices)
    hass, entry = SimpleNamespace(data={}), SimpleNamespace(entry_id="entry")
    def update(episode, status="unresolved", observation=None):
        action_events.update_unverified_stop_alert(
            hass, entry, "generic_ev", now=T0 + timedelta(seconds=150),
            first_stop_at=T0, episode_id=episode, status=status, observation=observation)
    update("old")
    old_id = notices.call_args.kwargs["notification_id"]
    update("new")
    new_id = notices.call_args.kwargs["notification_id"]
    for obs in [None,
                {"episode_id": "old", "observed_at": T0, "charging": False},
                {"episode_id": "old", "observed_at": T0 + timedelta(seconds=151), "charging": False},
                {"episode_id": "new", "observed_at": T0 + timedelta(seconds=140), "charging": False},
                {"episode_id": "old", "observed_at": T0 + timedelta(seconds=140), "charging": True},
                {"episode_id": "old", "observed_at": T0 + timedelta(seconds=140), "charging": None}]:
        update("old", "verified", obs)
    assert notices.call_count == 2
    idle = {"episode_id": "old", "observed_at": T0 + timedelta(seconds=140), "charging": False}
    update("old", "unresolved", idle)
    assert notices.call_count == 2
    update("old", "verified", idle)
    assert notices.call_count == 3
    assert notices.call_args.kwargs["clear"] is True
    assert notices.call_args.kwargs["notification_id"] == old_id != new_id
    update("old", "verified", idle)
    update("old")
    assert notices.call_count == 3


@pytest.mark.parametrize("observation", [
    {"episode_id": "other", "observed_at": T0 + timedelta(seconds=1), "charging": True},
    {"episode_id": "a", "observed_at": T0, "charging": True},
    {"episode_id": "a", "observed_at": T0 + timedelta(seconds=121), "charging": True},
    {"episode_id": "a", "observed_at": T0 + timedelta(seconds=1), "charging": None},
])
def test_unusable_telemetry_does_not_claim_charging(monkeypatch, observation):
    notices = Mock()
    monkeypatch.setattr(action_events, "_notification", notices)
    action_events.update_unverified_stop_alert(
        SimpleNamespace(data={}), SimpleNamespace(entry_id="entry"), "generic_ev",
        now=T0 + timedelta(seconds=120), first_stop_at=T0,
        episode_id="a", status="unresolved", observation=observation)
    assert "telemetry" in notices.call_args.kwargs["reason"].lower()
    assert "reported charging" not in notices.call_args.kwargs["reason"]


def test_future_first_stop_is_rejected_without_latching(monkeypatch):
    notices = Mock(return_value=True)
    monkeypatch.setattr(action_events, "_notification", notices)
    hass, entry = SimpleNamespace(data={}), SimpleNamespace(entry_id="entry")
    for first in (T0 + timedelta(days=1), T0 - timedelta(minutes=3)):
        action_events.update_unverified_stop_alert(
            hass, entry, "ev", now=T0, first_stop_at=first, episode_id="a",
            status="unresolved", observation=None)
    assert notices.call_count == 1


def test_notification_failures_are_retried(monkeypatch):
    notices = Mock(side_effect=[False, True, False, True])
    monkeypatch.setattr(action_events, "_notification", notices)
    hass, entry = SimpleNamespace(data={}), SimpleNamespace(entry_id="entry")
    def update(status, obs=None):
        action_events.update_unverified_stop_alert(
            hass, entry, "ev", now=T0 + timedelta(minutes=3), first_stop_at=T0,
            episode_id="a", status=status, observation=obs)
    update("unresolved")
    update("unresolved")
    obs = {"episode_id": "a", "observed_at": T0 + timedelta(minutes=1), "charging": False}
    update("verified", obs)
    update("verified", obs)
    update("verified", obs)
    assert notices.call_count == 4
    assert [c.kwargs.get("clear", False) for c in notices.call_args_list] == [False, False, True, True]


def test_restored_episode_deduplicates_and_clears_only_its_notification(monkeypatch):
    import sys
    from types import ModuleType

    registry = {}
    calls = []
    pn = ModuleType("homeassistant.components.persistent_notification")
    def create(hass, message, *, title, notification_id):
        calls.append(("create", notification_id))
        registry[notification_id] = {"message": message, "title": title}
    def dismiss(hass, notification_id):
        calls.append(("dismiss", notification_id))
        registry.pop(notification_id, None)
    pn.async_create, pn.async_dismiss = create, dismiss
    ha = ModuleType("homeassistant")
    components = ModuleType("homeassistant.components")
    components.persistent_notification = pn
    ha.components = components
    monkeypatch.setitem(sys.modules, "homeassistant", ha)
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(sys.modules, "homeassistant.components.persistent_notification", pn)
    entry = SimpleNamespace(entry_id="entry")
    hass = SimpleNamespace(data={})
    old, new = {}, {}
    def update(hass, episode, state, status="unresolved", observation=None):
        action_events.update_unverified_stop_alert(
            hass, entry, "ev", now=T0 + timedelta(minutes=3), first_stop_at=T0,
            episode_id=episode, status=status, observation=observation, episode_state=state)
    update(hass, "old", old)
    update(hass, "new", new)
    old_id, new_id = calls[0][1], calls[1][1]
    restored = dict(old)
    restarted = SimpleNamespace(data={})
    update(restarted, "old", restored)
    assert len(calls) == 2
    obs = {"episode_id": "old", "observed_at": T0 + timedelta(minutes=1), "charging": False}
    update(restarted, "old", restored, "verified", obs)
    update(restarted, "old", restored)
    assert calls[-1] == ("dismiss", old_id)
    assert len(calls) == 3 and set(registry) == {new_id}


def test_invalid_timezone_offset_is_rejected(monkeypatch):
    from datetime import tzinfo
    class NoOffset(tzinfo):
        def utcoffset(self, dt):
            return None
    notices = Mock(return_value=True)
    monkeypatch.setattr(action_events, "_notification", notices)
    hass, entry = SimpleNamespace(data={}), SimpleNamespace(entry_id="entry")
    action_events.update_unverified_stop_alert(
        hass, entry, "ev", now=T0, first_stop_at=T0.replace(tzinfo=NoOffset()),
        episode_id="a", status="unresolved", observation=None)
    assert not hass.data and not notices.called


def test_restored_state_cannot_be_reused_for_another_episode(monkeypatch):
    notices = Mock(return_value=True)
    monkeypatch.setattr(action_events, "_notification", notices)
    entry = SimpleNamespace(entry_id="entry")
    old = {}
    action_events.update_unverified_stop_alert(
        SimpleNamespace(data={}), entry, "ev", now=T0 + timedelta(minutes=3),
        first_stop_at=T0, episode_id="old", status="unresolved", observation=None, episode_state=old)
    obs = {"episode_id": "new", "observed_at": T0 + timedelta(minutes=1), "charging": False}
    action_events.update_unverified_stop_alert(
        SimpleNamespace(data={}), entry, "ev", now=T0 + timedelta(minutes=3),
        first_stop_at=T0, episode_id="new", status="verified", observation=obs, episode_state=old)
    assert notices.call_count == 1


def test_notification_returns_failure_when_ha_raises(monkeypatch):
    import sys
    from types import ModuleType
    ha, components = ModuleType("homeassistant"), ModuleType("homeassistant.components")
    components.persistent_notification = SimpleNamespace(
        async_create=Mock(side_effect=RuntimeError("offline")),
        async_dismiss=Mock(side_effect=RuntimeError("offline")))
    ha.components = components
    monkeypatch.setitem(sys.modules, "homeassistant", ha)
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    hass = SimpleNamespace(data={})
    assert action_events._notification(hass, "entry", "ev", reason="x") is False
    assert action_events._notification(hass, "entry", "ev", reason=None, clear=True) is False
