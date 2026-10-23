#!/usr/bin/env python3
"""Starter thermal dispatch with myopic price thresholds."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("REFUSED: expected input and output paths", file=sys.stderr)
        return 2
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("REFUSED: unreadable input", file=sys.stderr)
        return 2

    chp = payload["chp"]
    boiler = payload["boiler"]
    storage = payload["storage"]
    soc = storage["initial_soc"]
    status = payload["initial_status"]
    streak = max(1, payload["initial_streak"])
    schedule: list[dict[str, int]] = []
    cost = 0
    for hour in range(payload["hours"]):
        want_on = int(
            payload["prices"][hour]
            + payload["heat_demand"][hour] * boiler["heat_cost"]
            > chp["fuel_cost"] + chp["heat_ratio"] * boiler["heat_cost"]
        )
        if want_on != status:
            cost += chp["startup_cost"] if want_on else 0
            status = want_on
            streak = 1
        else:
            streak += 1
        chp_e = chp["capacity_e"] if status else 0
        chp_h = chp_e * chp["heat_ratio"]
        grid = max(0, payload["electric_demand"][hour] - chp_e)
        heat_gap = payload["heat_demand"][hour] - chp_h
        boiler_heat = max(0, min(boiler["capacity_heat"], heat_gap))
        net = payload["heat_demand"][hour] - chp_h - boiler_heat
        charge = min(storage["capacity"] - soc, max(0, net))
        discharge = min(soc, max(0, -net))
        soc = soc + charge * storage["efficiency_percent"] // 100 - discharge
        dump = max(0, chp_h + boiler_heat - payload["heat_demand"][hour] - charge)
        cost += (
            status * chp["fuel_cost"]
            + grid * payload["prices"][hour]
            + boiler_heat * boiler["heat_cost"]
        )
        schedule.append(
            {
                "boiler_heat": boiler_heat,
                "charge": charge,
                "chp_electric": chp_e,
                "chp_heat": chp_h,
                "chp_on": status,
                "discharge": discharge,
                "dump_heat": dump,
                "grid_electric": grid,
                "hour": hour,
                "soc": soc,
            }
        )
    result = {"cost": cost, "schedule": schedule, "status": "ok"}
    target.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
