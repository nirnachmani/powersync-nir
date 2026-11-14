# Local decision diagnostics

Decision logging is enabled by default when the integration entry starts. No separate activation setting is provided. It records future decisions only; it cannot reconstruct inputs that were not recorded in the past.

## Storage and privacy

Records are local JSON Lines under the Home Assistant configuration directory in `power_sync_diagnostics/`: `ev-YYYY-MM-DD.jsonl` and `optimizer-YYYY-MM-DD.jsonl`. The filename date uses the Home Assistant timezone; timestamps are UTC. Cleanup keeps the current local calendar date and the previous seven dates. Consequently the retained interval varies with the time of day and daylight-saving transitions. Cleanup runs at startup and periodically while idle.

Data can contain energy consumption, price forecasts, charging schedules and battery states. Treat the directory as private. The logger uses explicitly allowed fields, logical profile IDs and an opaque entry alias; it does not deliberately export tokens, VINs or exact location. It does not transmit files remotely.

## Reading records

Use `timestamp_utc`, `session_id`, `sequence` and, when present, `trace_id` to order and correlate records. Sequences are scoped to one writer session. `command_handler_result` describes a function return, not physical confirmation. `stop_observation` and `shared_observation` record later telemetry separately; null or missing is not zero. `reported_state` and `reported_action` are stored software state, not proof of physical effect. `diagnostic_gap`, warnings and counters indicate missing observations; a crash or continuing disk failure can prevent a final gap record from being written.

For a charging stop, follow `smart_schedule_policy`, `price_level_result`, `scheduled_policy` or `solar_rate_decision`, then ownership, `dynamic_stop_requested`, `command_handler_*` and `stop_observation`. A trace ID joins the relevant dynamic stop and its later observation where the pending stop carries one. For a solar-export hold, use `solar_export_budget` and `solar_export_slot`, then the same trace's `solver_capture` and optimizer action records. Funding-capacity arrays are separate estimates for solar and grid; they are not additive promises that both sources can simultaneously fill the battery. `sigenergy_curtailment_*` and `solar_production_state` represent different controls.

## Storage measurement

A 576-slot synthetic solver fixture persisted a single 186,644-byte optimizer record. At an illustrative 288 such captures per day (one every five minutes), that single record type would occupy approximately 53.8 MB per day or 430 MB over eight days, excluding other optimizer and EV events and filesystem overhead. This is arithmetic on one fixture, not a measurement of actual site frequency or growth; extra event-triggered solves could increase it. There is no silent size cap.

## Current limitations

Coverage is aimed at the supported Generic and Sigenergy EVAC paths and the optimizer, but individual records do not include every input, freshness indicator or command/readback across every branch. Not all EV and optimizer events share a cross-stream cycle ID; correlate their timestamps and available trace IDs. Solver capture is not a source-bound replay artifact. File-write failures and queue loss are reported by warnings and gap records when possible; if startup fails or the disk remains unwritable, there may be no file record of that failure. Actual disk growth and impact on the live system have not been measured.
