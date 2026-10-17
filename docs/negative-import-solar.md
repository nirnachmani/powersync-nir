# Stop solar during negative import prices

Available from PowerSync v2.12.1418 for Home Assistant. This is a narrowed
port of upstream `24fcc7d` with the configuration documentation completed by
upstream `a6120d0`.

The policy is **off by default**. It stops PV generation when the customer's
current retail import price is below zero, allowing existing household loads and
permitted battery charging to use paid grid imports. Zero export is a different
operation: it can leave solar supplying the house and battery.

Existing battery dispatch, grid-charging permissions, state-of-charge limits,
electrical limits, and EV settings remain authoritative. The feature does not
create extra loads or override those limits. Stopping solar can forgo export
income; this is an explicit import-price policy.

## Configuration fields

| Setting | Use |
| --- | --- |
| Stop solar when the import price is negative | Opt in to stopping generation below zero retail import price. Off by default. |
| PV production controls (optional with Sigenergy) | Select verified PV-only switches or production-limit numbers, or leave empty to use Sigenergy's native PV limit. |
| These controls cover all solar generation | Enable only when every PV source is controlled, allowing the optimiser to plan without solar in negative-price intervals. |
| Controlled solar production power sensor (optional) | Select power from the controlled PV sources so fresh readings can confirm a production stop. |
| Retail import price sensor (optional) | Supply a timestamped retail import interval instead of the configured Amber interval. |
| Grid connected sensor | Required fresh proof of utility-grid connection. |

Configure these fields under **Curtailment settings**.

## Controls and inverter coverage

Explicit Home Assistant **PV production controls** are vendor-neutral. Multiple
controls can cover multiple inverters. A switch must mean **on = PV enabled,
off = PV stopped**. A number must limit **PV generation**, accept zero, and
publish readable minimum and maximum values. Do not select an export limit,
grid/islanding switch, battery dispatch setting, whole-hybrid shutdown switch,
or general load relay.

When no production entity is selected on a configured Sigenergy system,
PowerSync uses the Sigenergy PV maximum-power limit register `40036`. Remote EMS
must already be enabled in a mode where the register is effective (3–6).
PowerSync does not change EMS mode, battery dispatch, grid export limits, or
third-party AC solar. It restores the exact original PV limit even if EMS mode
changes while the stop is active.

No other inverter-native production control is included in this private port.
Other systems require explicitly selected PV-only Home Assistant entities.

## Price and grid validity

The configured Amber coordinator supplies finite, timestamped **current retail
import intervals**. Feed-in prices are not used. Forecast intervals, expired
intervals, failed updates, non-finite values, and wholesale observations cannot
authorize a new stop.

Alternatively, **Retail import price sensor** must provide `startTime`/`endTime`
or `valid_from`/`valid_to` timezone-aware attributes. Supported units are
`c/kWh`, `¢/kWh`, `p/kWh`, `$/kWh`, `AUD/kWh`, `EUR/kWh`, `GBP/kWh`, `€/kWh`,
and `£/kWh`. Currency-per-kWh values are converted to minor units.

A selected grid-connected entity must provide a fresh observation no older than
90 seconds. A binary sensor uses `on`; a sensor may report `Active`, `Connected`,
`SystemGridConnected`, or `On-Grid`. Lost or stale grid status restores owned PV
controls.

## Recovery and evidence

PowerSync saves an exact durable restore record before the first write. At zero
or a positive price, missing or expired price, disabled policy, changed controls,
monitoring handoff, or unload, it restores only settings it still owns. Lost
replies, failed restores, and restarts retain the recovery obligation. External
changes are preserved and suspend automatic stopping for the current
negative-price window.

Monitoring Mode blocks commands unless **Allow curtailment control in Monitoring
Mode** is enabled. Permission transitions settle owned recovery before control is
relinquished.

The **Solar Production Control** sensor separates command attempt,
acknowledgement, device readback, and physical convergence. A zero limit confirms
a setting, not generation. A fresh controlled-PV observation must transition
from above 100 W to at most 100 W to prove physical effect. Missing observations
and zero PV before the command remain unconfirmed.

Enable **These controls cover all solar generation** only when every PV source is
covered. Once device control is confirmed, the optimiser projects zero PV for
negative import slots. Mixed or unconfirmed sites keep their solar forecast.
Deliberate suppression is excluded from forecast learning and near-term solar
derating.

The implementation and tests use simulated controls only; no live inverter
command or physical production stop was performed.
