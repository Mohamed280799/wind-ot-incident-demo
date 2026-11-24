"""Simulated wind-farm site: 3 turbines behind one Modbus TCP gateway (stand-in for a park SCADA/RTU).

Runs a scripted scenario so the monitor has real incidents to detect:
    t =  20 s  Turbine 2 gearbox temperature starts rising (overheating)       -> process alarm
    t =  45 s  Turbine 3 controller freezes: heartbeat stops changing          -> stale data
    t =  70 s  Turbine 1 curtailment setpoint changed by an unknown source     -> security event
    t =  95 s  Gateway stops answering for 15 s (network / gateway outage)     -> communication loss
    t = 110 s  Gateway back online

    python sim_site.py                 # scripted scenario on 127.0.0.1:5020
    python sim_site.py --normal        # no faults

Register map (per turbine n = 1..3, base = (n-1)*10):
  Input registers  base+0 active power [kW]      base+1 rotor speed [0.1 rpm]
                   base+2 gearbox temp [0.1 C]    base+3 status (1 run, 0 stop)
                   base+4 heartbeat counter
  Holding register base+0 curtailment setpoint [kW] (max allowed power, default 3600)
Only the Python standard library is needed.
"""
import argparse
import asyncio
import math
import random
import struct
import time

N_TURBINES = 3
ir = [0] * 40
hr = [0] * 40
for n in range(N_TURBINES):
    hr[n * 10] = 3600

state = {"offline": False}


def turbine_step(n, t, scenario):
    base = n * 10
    if scenario and n == 2 and t >= 45:                    # turbine 3 controller frozen:
        return                                             # all values stop updating but still look valid
    wind = 9 + 2 * math.sin(t / 15 + n) + random.uniform(-0.3, 0.3)          # m/s
    p_avail = max(0.0, min(3600.0, 3600 * ((wind - 3) / 9) ** 3))
    power = min(p_avail, hr[base])
    rpm = 0 if power == 0 else 9 + 5 * power / 3600
    temp = 55 + 15 * power / 3600 + random.uniform(-0.5, 0.5)

    if scenario and n == 1 and t >= 20:                    # turbine 2 overheating
        temp += min(40, (t - 20) * 1.0)
    ir[base + 0] = int(power)
    ir[base + 1] = int(rpm * 10)
    ir[base + 2] = int(temp * 10)
    ir[base + 3] = 1 if power > 0 else 0
    ir[base + 4] = (ir[base + 4] + 1) % 65536


async def site_cycle(scenario):
    t0 = time.time()
    tampered = False
    while True:
        t = time.time() - t0
        for n in range(N_TURBINES):
            turbine_step(n, t, scenario)
        if scenario and t >= 70 and not tampered:          # write from unknown source
            hr[0] = 1200
            tampered = True
        state["offline"] = scenario and 95 <= t < 110       # gateway outage
        await asyncio.sleep(0.5)


def handle_pdu(pdu):
    fc = pdu[0]
    try:
        if fc in (3, 4):
            addr, count = struct.unpack(">HH", pdu[1:5])
            table = hr if fc == 3 else ir
            if addr + count > len(table):
                return bytes([fc | 0x80, 2])
            return bytes([fc, 2 * count]) + struct.pack(f">{count}H", *table[addr:addr + count])
        if fc == 6:
            addr, value = struct.unpack(">HH", pdu[1:5])
            if addr >= len(hr):
                return bytes([fc | 0x80, 2])
            hr[addr] = value
            return pdu[:5]
    except struct.error:
        return bytes([fc | 0x80, 3])
    return bytes([fc | 0x80, 1])


async def serve_client(reader, writer):
    try:
        while True:
            header = await reader.readexactly(7)
            tid, pid, length, unit = struct.unpack(">HHHB", header)
            pdu = await reader.readexactly(length - 1)
            if state["offline"]:            # gateway hangs: no answer, client times out
                continue
            reply = handle_pdu(pdu)
            writer.write(struct.pack(">HHHB", tid, pid, len(reply) + 1, unit) + reply)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()


async def main(host, port, scenario):
    asyncio.create_task(site_cycle(scenario))
    server = await asyncio.start_server(serve_client, host, port)
    print(f"Simulated wind site on {host}:{port} ({'scripted fault scenario' if scenario else 'normal'})")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5020)
    p.add_argument("--normal", action="store_true", help="run without injected faults")
    a = p.parse_args()
    asyncio.run(main(a.host, a.port, not a.normal))
