# Incident report – simulated wind site

Generated 2026-11-24 10:23

| ID | Prio | Type | Asset | Opened | Closed | Detail |
|---|---|---|---|---|---|---|
| INC-001 | P2 | GEARBOX_TEMP | WTG02 | 10:22:01 | OPEN | gearbox 85.7 C > 85.0 C |
| INC-002 | P2 | STALE_DATA | WTG03 | 10:22:02 | OPEN | heartbeat frozen at 89 for 5 polls |
| INC-003 | P1 | CONFIG_CHANGE | WTG01 | 10:22:23 | OPEN | curtailment setpoint 1200 kW, approved 3600 kW, no approved change |
| INC-004 | P1 | COMM_LOSS | SITE | 10:22:52 | 10:23:03 | no answer from gateway for 3 polls |

## Runbooks for the incident types seen

### GEARBOX_TEMP (P2)
1. Inform the control room: process alarm, not an OT fault, but confirm the measurement is real
2. Cross-check with related signals (power, rotor speed, cooling) to rule out a sensor fault
3. Follow the asset owner's procedure (curtail or stop turbine); hand over to the service team
4. Evidence: trend before the alarm, maintenance history

### STALE_DATA (P2)
1. Value looks valid but is frozen: compare heartbeat/timestamp with other turbines
2. Check turbine controller and its communication module; check whether the turbine is still producing
3. Flag the data as bad quality to operators and the historian so decisions are not based on it
4. Restart of communication module only via the agreed procedure and with control room approval
5. Evidence: last good timestamp, controller logs, firmware/recent changes

### CONFIG_CHANGE (P1)
1. Treat as a potential security incident until proven otherwise: inform cybersecurity (SOC) immediately
2. Check change management: is there an approved change or a planned activity by a supplier?
3. Identify the source: which account, which engineering station or remote connection wrote the value
4. Restore the approved value only after agreement with the control room and cybersecurity; preserve logs
5. Evidence: SCADA audit trail, remote-access logs, firewall logs, time of change

### COMM_LOSS (P1)
1. Confirm scope: one turbine, the whole park, or several sites? (one gateway vs network)
2. Check with the control room whether they also lost data; check whether the site still produces (local control keeps running)
3. Remote diagnostics: ping and port check to the gateway, check firewall/VPN tunnel and switch status, check gateway/server services and event logs
4. If not resolved remotely: dispatch field technician or supplier; keep control room updated
5. Evidence for RCA: timestamps of first failure and recovery, network logs, gateway logs, recent changes

## Root cause analysis template

- What happened, when, and which assets were affected?
- Impact: lost production, lost visibility, safety or security impact?
- Timeline: detection, response, recovery (from the incident log)
- Root cause (5 whys) and contributing factors
- Preventive actions, owner and due date
