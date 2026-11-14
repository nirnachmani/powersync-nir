# Local decision diagnostics

Decision logging is enabled by default. In PowerSync's integration options, choose **Advanced settings → Decision logging** to turn it on or off. Saving reloads PowerSync. When off, the writer and local diagnostic solver capture are not started; existing logs are left in place and are not pruned until logging is enabled again. Other HA logging and independently enabled developer regression capture are unchanged. The logger records future decisions only; it cannot reconstruct inputs that were not recorded in the past.

## Storage and privacy

Records are local JSON Lines on the configured Home Assistant network share at `/share/NAS_Backup/power_sync_diagnostics/`: `ev-YYYY-MM-DD.jsonl` and `optimizer-YYYY-MM-DD.jsonl`. Files from earlier versions remain under `/config/power_sync_diagnostics/`; they are not moved or deleted. The filename date uses the Home Assistant timezone; timestamps are UTC. Cleanup keeps the current local calendar date and the previous seven dates. Consequently the retained interval varies with the time of day and daylight-saving transitions. Cleanup runs at startup and periodically while idle.

The share must be mounted as `/share/NAS_Backup`; otherwise diagnostics are dropped and a warning is logged, with no fallback to local storage. Network filesystem writes and retention cleanup use a dedicated daemon worker, separate from Home Assistant's shared executor. If NAS I/O stalls, the control path continues and the bounded diagnostics queue can drop records; logging resumes when the share and worker recover. An in-flight network write may complete after a timeout, so a warning does not prove that particular write was absent. A blocked kernel operation cannot be cancelled by Python, but it does not prevent integration unload indefinitely or require spawning further disk workers.

Data can contain energy consumption, price forecasts, charging schedules and battery states. Treat the NAS directory as private. The logger uses explicitly allowed fields, logical profile IDs and an opaque entry alias; it does not deliberately include tokens, VINs or exact location. Records are sent to the configured NAS share, not to a support service.

## Reading records

Use `timestamp_utc`, `session_id`, `sequence` and, when present, `trace_id` to order and correlate records. Sequences are scoped to one writer session. `command_handler_result` describes a function return, not physical confirmation. `stop_observation` and `shared_observation` record later telemetry separately; null or missing is not zero. `reported_state` and `reported_action` are stored software state, not proof of physical effect. `diagnostic_gap`, warnings and counters indicate missing observations; a crash or continuing disk failure can prevent a final gap record from being written.

For a charging stop, follow `smart_schedule_policy`, `price_level_result`, `scheduled_policy` or `solar_rate_decision`, then ownership, `dynamic_stop_requested`, `command_handler_*` and `stop_observation`. A trace ID joins the relevant dynamic stop and its later observation where the pending stop carries one. For a solar-export hold, use `solar_export_budget` and `solar_export_slot`, then the same trace's `solver_capture` and optimizer action records. Funding-capacity arrays are separate estimates for solar and grid; they are not additive promises that both sources can simultaneously fill the battery. `sigenergy_curtailment_*` and `solar_production_state` represent different controls.

## Storage measurement

A 576-slot synthetic solver fixture persisted a single 186,644-byte optimizer record. At an illustrative 288 such captures per day (one every five minutes), that single record type would occupy approximately 53.8 MB per day or 430 MB over eight days, excluding other optimizer and EV events and filesystem overhead. This is arithmetic on one fixture, not a measurement of actual site frequency or growth; extra event-triggered solves could increase it. There is no silent size cap.

## Current limitations

Coverage is aimed at the supported Generic and Sigenergy EVAC paths and the optimizer, but individual records do not include every input, freshness indicator or command/readback across every branch. Not all EV and optimizer events share a cross-stream cycle ID; correlate their timestamps and available trace IDs. Solver capture is not a source-bound replay artifact. File-write failures and queue loss are reported by warnings and gap records when possible; if startup fails or the disk remains unwritable, there may be no file record of that failure. Actual disk growth and impact on the live system have not been measured.
