# Wind OT Incident Demo

A small, self-contained example of **OT incident monitoring for a wind site**: a simulated site with three wind turbines sends data over **Modbus TCP**, and a monitor detects incidents, prioritises them and documents them in an incident log and report with runbooks and a root-cause template.

You can understand the whole project from this page; running it is optional.

---

## 1. Why I built it

OT incident engineers keep wind farms, substations and their control systems running safely, securely and reliably. Most of the job is:

1. **Detect** what really matters (not just missing data, but also data that looks right and isn't).
2. **Prioritise** by impact (safety, security, loss of production or visibility).
3. **Communicate** with the right people (control room, cybersecurity, suppliers).
4. **Document** so others can continue and the root cause can be found.

This demo shows that loop in a simplified, runnable form.

---

## 2. How it works

```
  sim_site.py                                     ot_monitor.py
  ┌──────────────────────────────┐    Modbus    ┌──────────────────────────────────┐
  │ Simulated wind site          │     TCP      │ OT incident monitor ("OT Guard") │
  │  WTG01  WTG02  WTG03         │ <──────────> │  polls every 1 s                 │
  │  behind one gateway          │  port 5020   │  checks 4 rules                  │
  │  scripted faults over time   │              │  opens / clears incidents        │
  └──────────────────────────────┘              │  writes incident_log.csv         │
                                                │  and incident_report.md          │
                                                └──────────────────────────────────┘
```

- **WTG** = wind turbine generator (WTG01 = turbine 1).
- Each turbine reports **active power (kW), rotor speed (rpm), gearbox temperature (°C), status and a heartbeat counter**, and has a **curtailment setpoint**: the maximum power it is allowed to produce.
- Values are stored in Modbus registers. Measurements are *input registers* (read-only); the setpoint is a *holding register* (writable). Temperature and speed are scaled ×10 because Modbus registers hold integers.

### Register map (per turbine, block of 10 registers)

| Register | Type | Content |
|---|---|---|
| base + 0 | Input | Active power [kW] |
| base + 1 | Input | Rotor speed [0.1 rpm] |
| base + 2 | Input | Gearbox temperature [0.1 °C] |
| base + 3 | Input | Status (1 = running, 0 = stopped) |
| base + 4 | Input | Heartbeat counter (+1 every cycle) |
| base + 0 | Holding | Curtailment setpoint [kW], approved value 3,600 |

base = 0 for WTG01, 10 for WTG02, 20 for WTG03.

---

## 3. The four detection rules

| Rule | Detects | Condition | Priority | Why |
|---|---|---|---|---|
| COMM_LOSS | Gateway or network down | No valid answer for 3 polls in a row | **P1** | Loss of visibility of the whole site |
| STALE_DATA | Frozen device | Heartbeat unchanged for 5 polls | P2 | Values look valid but are not updating; operators would trust wrong data |
| GEARBOX_TEMP | Process alarm | Gearbox temperature > 85 °C (clears below 82 °C) | P2 | Equipment risk; hand over to control room and service after checking the measurement |
| CONFIG_CHANGE | Possible security event | Live setpoint ≠ approved configuration | **P1** | Unexplained change; treat as security incident until proven otherwise |

**Avoiding alarm noise**
- *Debounce*: wait for several polls before alarming (3 for communication loss, 5 for stale data), so one lost message doesn't raise an alarm.
- *Hysteresis*: the temperature alarm opens above 85 °C but only clears below 82 °C, so it doesn't flicker on and off.
- *One incident, not repeated alarms*: each condition opens one incident with an ID until it clears.

---

## 4. The scripted scenario

The simulated site injects four faults, one for each rule (times after the simulator starts):

| Time | Injected fault | Expected incident |
|---|---|---|
| 20 s | WTG02 gearbox starts overheating (+1 °C per second) | GEARBOX_TEMP, P2 |
| 45 s | WTG03 controller freezes: all values stop updating but still look normal | STALE_DATA, P2 |
| 70 s | WTG01 curtailment setpoint changed from 3,600 to 1,200 kW by an unknown source | CONFIG_CHANGE, P1 |
| 95–110 s | Gateway stops answering for 15 s | COMM_LOSS, P1 (opens, then clears automatically) |

---

## 5. Example result (real run)

### Console output (excerpt)

```
Monitoring 127.0.0.1:5020 for 130 s ...
    0 s | WTG01 2180 kW 12.0 rpm  64.4 C | WTG02 2350 kW 12.2 rpm  64.9 C | WTG03 1167 kW 10.6 rpm  59.9 C
   ...
   32 s | WTG01 1033 kW 10.4 rpm  59.7 C | WTG02  304 kW  9.4 rpm  84.7 C | WTG03  329 kW  9.4 rpm  56.6 C
  >>> OPEN  INC-001 P2 GEARBOX_TEMP  WTG02  gearbox 86.8 C > 85.0 C
  >>> OPEN  INC-002 P2 STALE_DATA    WTG03  heartbeat frozen at 89 for 5 polls
   33 s | WTG01  801 kW 10.1 rpm  58.2 C | WTG02  393 kW  9.5 rpm  86.8 C | WTG03  329 kW  9.4 rpm  56.6 C
   ...
  >>> OPEN  INC-003 P1 CONFIG_CHANGE WTG01  curtailment setpoint 1200 kW, approved 3600 kW, no approved change
   ...
   78 s | WTG01 1129 kW 10.5 rpm  59.9 C | WTG02 2253 kW 12.1 rpm 104.8 C | WTG03  329 kW  9.4 rpm  56.6 C
  >>> OPEN  INC-004 P1 COMM_LOSS     SITE   no answer from gateway for 3 polls
  <<< CLEAR INC-004 COMM_LOSS SITE
   93 s | WTG01 1200 kW 10.6 rpm  59.7 C | WTG02 2480 kW 12.4 rpm 105.2 C | WTG03  329 kW  9.4 rpm  56.6 C
   ...
4 incidents. Wrote incident_log.csv and incident_report.md
```

(The monitor was started about 16 s after the simulator, so events appear about 16 s earlier than in the scenario table.)

### Incident log (incident_log.csv)

| id | priority | type | asset | opened | closed | detail |
|---|---|---|---|---|---|---|
| INC-001 | P2 | GEARBOX_TEMP | WTG02 | 15:46:37 | | gearbox 86.8 C > 85.0 C |
| INC-002 | P2 | STALE_DATA | WTG03 | 15:46:37 | | heartbeat frozen at 89 for 5 polls |
| INC-003 | P1 | CONFIG_CHANGE | WTG01 | 15:46:58 | | curtailment setpoint 1200 kW, approved 3600 kW, no approved change |
| INC-004 | P1 | COMM_LOSS | SITE | 15:47:28 | 15:47:37 | no answer from gateway for 3 polls |

### How to read the result

- **The frozen turbine looks normal.** From about 29 s, WTG03 shows 329 kW, 9.4 rpm and 56.6 °C on every line. Those are plausible values; only the frozen heartbeat reveals that the controller has stopped updating.
- **The setpoint change was invisible at first.** WTG01 was producing less than 1,200 kW anyway because the wind was low. Only later (from 93 s) does it sit flat at exactly 1,200 kW while the wind is higher: lost production caused by an unauthorised change. Comparing live values with the approved configuration catches it immediately.
- **Communication loss opens and closes.** The data lines stop during the outage; the incident opens after 3 failed polls and clears automatically when the gateway answers again. The log shows how long the site was not visible (9 s, plus the detection delay).
- **Three incidents stay open.** Their causes are still present at the end of the run. These are what would be handed over to the next person on duty.

---

## 6. The incident report

`incident_report.md` is written at the end of every run and contains:

1. **Incident table**: ID, priority, type, asset, opened, closed, detail. Used for shift handover.
2. **A runbook for each incident type that occurred**, for example for CONFIG_CHANGE:
   1. Treat as a potential security incident until proven otherwise: inform cybersecurity (SOC) immediately.
   2. Check change management: is there an approved change or planned supplier activity?
   3. Identify the source: which account, engineering station or remote connection wrote the value.
   4. Restore the approved value only after agreement with the control room and cybersecurity; preserve logs.
   5. Evidence: SCADA audit trail, remote-access logs, firewall logs, time of change.
3. **A root-cause analysis template**: what happened, impact, timeline, root cause (5 whys), preventive actions with owner and due date.

---

## 7. Files

| File | Purpose |
|---|---|
| `sim_site.py` | Simulated wind site and Modbus TCP server (Python standard library only) |
| `ot_monitor.py` | Incident monitor: polling, detection rules, incident handling, log and report |
| `approved_config.json` | Approved setpoints (stand-in for change management) |
| `incident_log.csv`, `incident_report.md` | Output of the last run |

---

## 8. How to run it (optional)

Requires Python 3.10+ and `pymodbus` for the monitor.

```
python -m pip install pymodbus
python sim_site.py                     # terminal 1: start the simulated site
python ot_monitor.py --seconds 130     # terminal 2: start the monitor straight after
```

Start both within a few seconds of each other, because the faults are timed from when the simulator starts. The monitor stops by itself after 130 s; stop the simulator with Ctrl+C. Run `python sim_site.py --normal` for a site without faults.

---

## 9. Design notes and limitations

- **Simulated data.** Values come from simplified formulas, for example power rising with the cube of wind speed and capped at a 3.6 MW rating, plus noise. Thresholds such as 85 °C are illustrative, not vendor values.
- **Modbus TCP** was chosen because it is simple and widely used. Real wind sites also use IEC 60870-5-104 towards control centres and grid operators, IEC 61850 in substations, OPC UA and vendor SCADA. The detection logic would be the same.
- **Modbus has no authentication or encryption**, which is why configuration monitoring, network segmentation and controlled remote access matter in OT.
- **Timestamps** come from the monitor's own clock. A real system should use source timestamps and synchronised time (NTP/PTP) so incident timelines are correct.
- **The simulated turbine has no self-protection**: WTG02 keeps heating up past 100 °C, whereas a real turbine controller would curtail or stop.

### Possible next steps

- Sort P1 incidents first and record who acknowledged each incident and when.
- Notify the on-duty engineer automatically for P1 incidents.
- Correlate alarms (e.g. suppress stale-data alarms while the whole site has lost communication).
- Add IEC 60870-5-104 or OPC UA data sources and monitor the monitor itself (watchdog).

---

*Built by Mohamed Abdo as a learning and demonstration project.*