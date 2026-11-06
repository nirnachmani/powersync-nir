"""Public HA EV action events; adapted from upstream f1ab528fcf.

Command results never imply physical confirmation. Observation cannot dispatch control.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)
EVENT_EV_COMMAND = "power_sync_ev_command"
EVENT_EV_STOP_FAILED = "power_sync_ev_stop_failed"


def fire_action_event(hass: Any, event_type: str, payload: dict[str, Any]) -> None:
    """Publish without allowing an observer failure to interrupt control cleanup."""
    fire = getattr(getattr(hass, "bus", None), "async_fire", None)
    if fire is None:
        return
    try:
        fire(event_type, {"schema_version": 1, **payload})
    except Exception:
        _LOGGER.exception("Could not publish %s", event_type)


def _notification(hass: Any, entry_id: str, vehicle_id: str, *, reason: str | None,
                  clear: bool = False, notification_id: str | None = None) -> bool:
    try:
        from homeassistant.components import persistent_notification
        notification_id = notification_id or f"power_sync_ev_stop_{entry_id}_{vehicle_id}"
        if clear:
            persistent_notification.async_dismiss(hass, notification_id)
        else:
            persistent_notification.async_create(
                hass,
                f"PowerSync could not confirm that EV charging stopped for {vehicle_id}. "
                f"{reason or 'The stop request failed.'} Check the vehicle/charger and its "
                "actual charging power. Continued charging may drain the home battery.",
                title="PowerSync: EV stop needs attention",
                notification_id=notification_id,
            )
        return True
    except ImportError:
        _LOGGER.debug("Persistent notifications are unavailable")
    except Exception:
        _LOGGER.exception("Could not update EV stop notification")
    return False


def update_unverified_stop_alert(
    hass: Any, config_entry: Any, loadpoint_id: str, *, now: datetime,
    first_stop_at: datetime, episode_id: str, status: str,
    observation: dict[str, Any] | None, episode_state: dict[str, Any] | None = None,
) -> None:
    """Warn once per physical stop episode; caller supplies authoritative identity.

    Observation, when present, has episode_id, observed_at and charging fields.
    Only a matching post-stop idle observation and verified status can dismiss.
    The episode ID and original timestamp must remain stable across retries.
    A caller may persist and restore episode_state, a mutable JSON-compatible
    dict, after each call. It is bound to the entry, loadpoint and episode.
    """
    try:
        if (not loadpoint_id or not episode_id or status not in ("unresolved", "verified")
                or now.utcoffset() is None or first_stop_at.utcoffset() is None
                or first_stop_at > now):
            return
    except (AttributeError, TypeError, ValueError, OverflowError):
        return
    alerts = (hass.data.setdefault("power_sync", {})
              .setdefault(config_entry.entry_id, {})
              .setdefault("ev_unverified_stop_alerts", {}))
    key = (loadpoint_id, episode_id)
    identity_fields = {"entry_id": config_entry.entry_id, "loadpoint_id": loadpoint_id,
                       "episode_id": episode_id}
    state = alerts.get(key)
    if state is None:
        state = episode_state if episode_state is not None else {}
        if not state:
            state.update(identity_fields, first_stop_at=first_stop_at.isoformat(),
                         warned=False, cleared=False)
        try:
            if (any(state.get(k) != v for k, v in identity_fields.items())
                    or not isinstance(state.get("warned"), bool)
                    or not isinstance(state.get("cleared"), bool)):
                return
            restored_at = datetime.fromisoformat(state["first_stop_at"])
            if restored_at.utcoffset() is None or restored_at > now:
                return
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        alerts[key] = state
    elif episode_state is not None and episode_state is not state:
        # Keep a newly supplied persistence target synchronized with live state.
        episode_state.clear()
        episode_state.update(state)
        alerts[key] = state = episode_state
    first_stop_at = datetime.fromisoformat(state["first_stop_at"])
    valid_observation = False
    if observation and observation.get("episode_id") == episode_id:
        observed_at = observation.get("observed_at")
        try:
            if isinstance(observed_at, datetime) and observed_at.utcoffset() is not None:
                valid_observation = first_stop_at < observed_at <= now
        except (TypeError, ValueError, OverflowError):
            pass
    identity = json.dumps([config_entry.entry_id, loadpoint_id, episode_id], ensure_ascii=True)
    notification_id = "power_sync_ev_unverified_stop_" + hashlib.sha256(identity.encode()).hexdigest()
    if status == "verified":
        if (valid_observation and observation is not None
                and observation.get("charging") is False and not state["cleared"]):
            if state["warned"]:
                if not _notification(hass, config_entry.entry_id, loadpoint_id, reason=None,
                                     clear=True, notification_id=notification_id):
                    return
            state["cleared"] = True
        return
    if state["warned"] or state["cleared"] or (now - first_stop_at).total_seconds() < 120:
        return
    reason = ("Post-stop telemetry reported charging."
              if valid_observation and observation is not None and observation.get("charging") is True
              else "Post-stop telemetry is unavailable or does not confirm a stopped state.")
    if _notification(hass, config_entry.entry_id, loadpoint_id, reason=reason,
                     notification_id=notification_id):
        state["warned"] = True


def publish_ev_command(hass: Any, config_entry: Any, vehicle_id: str,
                       command: dict[str, Any], *, physical_confirmation: bool = False,
                       record_type: str = "command") -> None:
    """Publish a recorded result; latch one warning per unresolved physical loadpoint."""
    payload = {
        "entry_id": config_entry.entry_id,
        "vehicle_id": vehicle_id,
        "command": command["command"],
        "timestamp": command["at"],
        "source": command["source"],
        "success": command["success"],
        "reason": command.get("reason"),
        "physical_confirmation": physical_confirmation,
        "record_type": "observation" if physical_confirmation else record_type,
        "observed_at": command.get("settled_at") if physical_confirmation else command.get("observed_at"),
    }
    fire_action_event(hass, EVENT_EV_COMMAND, payload)
    if command["source"] != "powersync":
        return
    name = str(command["command"])
    is_stop = name == "stop" or name.startswith("stop_")
    is_start = name == "start" or name.startswith("start_")
    if not is_stop and not is_start:
        return
    entry = hass.data.setdefault("power_sync", {}).setdefault(config_entry.entry_id, {})
    alerts = entry.setdefault("ev_stop_alerts", {})
    if is_start:
        # A successful start begins a new failure episode on the same physical
        # loadpoint, but cannot clear an unconfirmed previous stop warning.
        if command["success"] and vehicle_id in alerts:
            alerts[vehicle_id]["rearmed"] = True
        return
    if physical_confirmation and command["success"]:
        if alerts.pop(vehicle_id, None) is not None:
            _notification(hass, config_entry.entry_id, vehicle_id, reason=None, clear=True)
    elif not command["success"] and (vehicle_id not in alerts or alerts[vehicle_id].get("rearmed")):
        alerts[vehicle_id] = payload
        fire_action_event(hass, EVENT_EV_STOP_FAILED, payload)
        _notification(hass, config_entry.entry_id, vehicle_id, reason=payload["reason"])


def observe_ev_stop(hass: Any, config_entry: Any, vehicle_id: str,
                    command: dict[str, Any], observed_at: datetime | None,
                    *, charging: bool) -> None:
    """Use only telemetry newer than a stop; ignore delayed or future samples."""
    if command.get("source") != "powersync":
        return
    name = str(command.get("command", ""))
    if not (name == "stop" or name.startswith("stop_")) or command.get("settled_at"):
        return
    try:
        stopped_at = datetime.fromisoformat(command["at"])
        if observed_at is None or stopped_at.tzinfo is None or observed_at.tzinfo is None:
            return
        age = (observed_at - stopped_at).total_seconds()
        if age <= 0 or (observed_at - datetime.now(timezone.utc)).total_seconds() > 60:
            return
    except (ValueError, TypeError, KeyError):
        return
    if charging:
        if age < 90 or (datetime.now(timezone.utc) - observed_at).total_seconds() > 120:
            return
        publish_ev_command(hass, config_entry, vehicle_id, {
            **command, "success": False, "observed_at": observed_at.isoformat(),
            "reason": "Vehicle telemetry still reports charging at least 90 seconds after the stop request",
        })
    else:
        command["settled_at"] = observed_at.isoformat()
        publish_ev_command(hass, config_entry, vehicle_id, {
            **command, "command": "stop_observed", "success": True,
            "reason": "Stopped state confirmed by newer vehicle telemetry",
        }, physical_confirmation=True)
