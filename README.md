# Wind OT Incident Demo

A small, honest demo of what an OT incident engineer does: monitor a (simulated) wind site over an industrial protocol, detect incidents, prioritise them, and produce an incident log, runbooks and an RCA template.

```
sim_site.py   ── Modbus TCP (port 5020) ──>   ot_monitor.py
3 turbines behind one gateway                 polls every second, opens/clears incidents
scripted faults                               writes incident_log.csv + incident_report.md
```

## Run it (2 terminals)

```
python3.13 -m pip install pymodbus
python3.13 sim_site.py                 # terminal 1: simulated wind site with scripted faults
python3.13 ot_monitor.py --seconds 130 # terminal 2: the monitor
```

## What happens (scripted scenario)

| Site time | Injected fault | Detected as | Priority |
|---|---|---|---|
| 20 s | WTG02 gearbox temperature starts rising | GEARBOX_TEMP (> 85 °C) | P2 |
| 45 s | WTG03 controller freezes: values stop updating but still look valid | STALE_DATA (heartbeat frozen 5 polls) | P2 |
| 70 s | WTG01 curtailment setpoint changed from 3600 to 1200 kW by an unknown source | CONFIG_CHANGE (differs from approved config) | P1, security |
| 95–110 s | Site gateway stops answering | COMM_LOSS (3 failed polls), cleared on recovery | P1 |

## Design choices worth explaining

- **Stale data is more dangerous than no data**: WTG03 keeps showing 287 kW and 56.2 °C, which looks plausible. Only the heartbeat reveals the device is frozen.
- **Process alarm vs OT fault**: a hot gearbox is handed to the control room/service team, but the OT engineer first checks the measurement is real.
- **Security events come from comparing live values with the approved configuration** (change management). An unexplained change is treated as a security incident until proven otherwise, and cybersecurity is informed immediately.
- **Debounce rules** (3 failed polls, 5 frozen polls, 3 °C hysteresis) avoid alarm floods from single glitches.
- Every incident has an ID, priority, open/close time and a runbook; the report ends with an RCA template.

## Limitations

Modbus TCP is used because it is simple and common; real wind sites also use IEC 60870-5-104 (to control centres/TSO), IEC 61850 (substations), OPC UA and vendor SCADA. The site is simulated; thresholds are illustrative.
