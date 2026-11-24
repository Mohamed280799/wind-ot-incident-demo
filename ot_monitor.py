"""OT incident monitor for the simulated wind site (the "OT Guard" side).

Polls the site gateway over Modbus TCP, detects incidents, opens and closes them with a
priority, and writes an incident log and a report with a runbook for each incident type.

    python ot_monitor.py --seconds 130            # against sim_site.py on 127.0.0.1:5020

Detection rules
  COMM_LOSS      no valid answer from the gateway for 3 polls in a row            P1
  STALE_DATA     a turbine heartbeat has not changed for 5 polls (frozen device)  P2
  GEARBOX_TEMP   gearbox temperature above 85 C (warning limit)                   P2
  CONFIG_CHANGE  live setpoint differs from the approved configuration            P1 (security)
"""
import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException
import logging
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)   # keep the console readable

TURBINES = ["WTG01", "WTG02", "WTG03"]
TEMP_LIMIT_C = 85.0
STALE_POLLS = 5
COMM_FAIL_POLLS = 3

RUNBOOK = {
    "COMM_LOSS": [
        "Confirm scope: one turbine, the whole park, or several sites? (one gateway vs network)",
        "Check with the control room whether they also lost data; check whether the site still produces (local control keeps running)",
        "Remote diagnostics: ping and port check to the gateway, check firewall/VPN tunnel and switch status, check gateway/server services and event logs",
        "If not resolved remotely: dispatch field technician or supplier; keep control room updated",
        "Evidence for RCA: timestamps of first failure and recovery, network logs, gateway logs, recent changes",
    ],
    "STALE_DATA": [
        "Value looks valid but is frozen: compare heartbeat/timestamp with other turbines",
        "Check turbine controller and its communication module; check whether the turbine is still producing",
        "Flag the data as bad quality to operators and the historian so decisions are not based on it",
        "Restart of communication module only via the agreed procedure and with control room approval",
        "Evidence: last good timestamp, controller logs, firmware/recent changes",
    ],
    "GEARBOX_TEMP": [
        "Inform the control room: process alarm, not an OT fault, but confirm the measurement is real",
        "Cross-check with related signals (power, rotor speed, cooling) to rule out a sensor fault",
        "Follow the asset owner's procedure (curtail or stop turbine); hand over to the service team",
        "Evidence: trend before the alarm, maintenance history",
    ],
    "CONFIG_CHANGE": [
        "Treat as a potential security incident until proven otherwise: inform cybersecurity (SOC) immediately",
        "Check change management: is there an approved change or a planned activity by a supplier?",
        "Identify the source: which account, which engineering station or remote connection wrote the value",
        "Restore the approved value only after agreement with the control room and cybersecurity; preserve logs",
        "Evidence: SCADA audit trail, remote-access logs, firewall logs, time of change",
    ],
}
PRIORITY = {"COMM_LOSS": "P1", "STALE_DATA": "P2", "GEARBOX_TEMP": "P2", "CONFIG_CHANGE": "P1"}


class IncidentBook:
    def __init__(self):
        self.open, self.closed = {}, []

    def raise_(self, key, kind, asset, detail):
        if key in self.open:
            return
        self.open[key] = {"id": f"INC-{len(self.open) + len(self.closed) + 1:03d}", "type": kind,
                          "priority": PRIORITY[kind], "asset": asset, "detail": detail,
                          "opened": datetime.now().strftime("%H:%M:%S"), "closed": ""}
        i = self.open[key]
        print(f"  >>> OPEN  {i['id']} {i['priority']} {kind:<13} {asset:<6} {detail}")

    def clear(self, key):
        if key in self.open:
            i = self.open.pop(key)
            i["closed"] = datetime.now().strftime("%H:%M:%S")
            self.closed.append(i)
            print(f"  <<< CLEAR {i['id']} {i['type']} {i['asset']}")

    def all(self):
        return sorted(self.closed + list(self.open.values()), key=lambda i: i["id"])


def read(client, fc, addr, count):
    fn = client.read_input_registers if fc == 4 else client.read_holding_registers
    rr = fn(addr, count=count)
    if rr.isError():
        raise IOError(str(rr))
    return rr.registers


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5020)
    p.add_argument("--seconds", type=float, default=130)
    p.add_argument("--period", type=float, default=1.0)
    a = p.parse_args()

    approved = json.loads(Path("approved_config.json").read_text())["curtailment_setpoint_kw"]
    client = ModbusTcpClient(a.host, port=a.port, timeout=1, retries=0)
    client.connect()
    book = IncidentBook()
    fails, last_hb, same = 0, {}, {t: 0 for t in TURBINES}
    t0 = time.time()
    print(f"Monitoring {a.host}:{a.port} for {a.seconds:.0f} s ...")
    try:
        while time.time() - t0 < a.seconds:
            try:
                irs = read(client, 4, 0, 25)
                hrs = read(client, 3, 0, 21)
            except (IOError, ModbusException):
                fails += 1
                if fails >= COMM_FAIL_POLLS:
                    book.raise_("comm", "COMM_LOSS", "SITE", f"no answer from gateway for {fails} polls")
                if not client.connected:
                    client.connect()
                time.sleep(a.period)
                continue
            fails = 0
            book.clear("comm")
            line = []
            for n, tag in enumerate(TURBINES):
                b = n * 10
                power, rpm, temp, hb, sp = irs[b], irs[b + 1] / 10, irs[b + 2] / 10, irs[b + 4], hrs[b]
                line.append(f"{tag} {power:4d} kW {rpm:4.1f} rpm {temp:5.1f} C")
                same[tag] = same[tag] + 1 if last_hb.get(tag) == hb else 0
                last_hb[tag] = hb
                if same[tag] >= STALE_POLLS:
                    book.raise_(f"stale{tag}", "STALE_DATA", tag, f"heartbeat frozen at {hb} for {same[tag]} polls")
                else:
                    book.clear(f"stale{tag}")
                if temp > TEMP_LIMIT_C:
                    book.raise_(f"temp{tag}", "GEARBOX_TEMP", tag, f"gearbox {temp:.1f} C > {TEMP_LIMIT_C} C")
                elif temp < TEMP_LIMIT_C - 3:
                    book.clear(f"temp{tag}")
                if sp != approved[tag]:
                    book.raise_(f"cfg{tag}", "CONFIG_CHANGE", tag,
                                f"curtailment setpoint {sp} kW, approved {approved[tag]} kW, no approved change")
                else:
                    book.clear(f"cfg{tag}")
            print(f"{time.time() - t0:5.0f} s | " + " | ".join(line))
            time.sleep(a.period)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
    write_outputs(book)


def write_outputs(book):
    rows = book.all()
    with open("incident_log.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "priority", "type", "asset", "opened", "closed", "detail"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})
    lines = ["# Incident report – simulated wind site", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}", "",
             "| ID | Prio | Type | Asset | Opened | Closed | Detail |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['priority']} | {r['type']} | {r['asset']} | {r['opened']} | "
                     f"{r['closed'] or 'OPEN'} | {r['detail']} |")
    lines += ["", "## Runbooks for the incident types seen", ""]
    for kind in dict.fromkeys(r["type"] for r in rows):
        lines.append(f"### {kind} ({PRIORITY[kind]})")
        lines += [f"{i}. {s}" for i, s in enumerate(RUNBOOK[kind], 1)]
        lines.append("")
    lines += ["## Root cause analysis template", "",
              "- What happened, when, and which assets were affected?",
              "- Impact: lost production, lost visibility, safety or security impact?",
              "- Timeline: detection, response, recovery (from the incident log)",
              "- Root cause (5 whys) and contributing factors",
              "- Preventive actions, owner and due date", ""]
    Path("incident_report.md").write_text("\n".join(lines))
    print(f"\n{len(rows)} incidents. Wrote incident_log.csv and incident_report.md")


if __name__ == "__main__":
    main()
