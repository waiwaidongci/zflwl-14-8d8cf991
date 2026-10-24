#!/usr/bin/env python3
"""Reference integer dynamic program for coupled heat and power dispatch.

边界检查覆盖公开输入区间；不合规数据统一拒收，失败路径不留下半成品。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


INPUT_KEYS = {
    "schema",
    "hours",
    "electric_demand",
    "heat_demand",
    "prices",
    "chp",
    "boiler",
    "storage",
    "initial_status",
    "initial_streak",
    "final_status",
}
CHP_KEYS = {
    "capacity_e",
    "heat_ratio",
    "min_up",
    "min_down",
    "startup_cost",
    "fuel_cost",
}
BOILER_KEYS = {"capacity_heat", "heat_cost"}
STORAGE_KEYS = {"capacity", "initial_soc", "final_soc", "efficiency_percent"}


class Refused(ValueError):
    pass


def _integer(value: Any, low: int, high: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused(f"{label} must be an integer")
    if not low <= value <= high:
        raise Refused(f"{label} is outside its allowed range")
    return value


def _series(value: Any, length: int, low: int, high: int, label: str) -> list[int]:
    if not isinstance(value, list) or len(value) != length:
        raise Refused(f"{label} must match the horizon")
    return [
        _integer(item, low, high, f"{label}[{index}]")
        for index, item in enumerate(value)
    ]


def parse_input(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Refused("input cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise Refused("input is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != INPUT_KEYS:
        raise Refused("top-level keys do not match heat-dispatch-v1")
    if payload.get("schema") != "heat-dispatch-v1":
        raise Refused("unsupported schema")
    hours = _integer(payload.get("hours"), 4, 10, "hours")
    electric = _series(payload.get("electric_demand"), hours, 0, 30, "electric_demand")
    heat = _series(payload.get("heat_demand"), hours, 0, 30, "heat_demand")
    prices = _series(payload.get("prices"), hours, 1, 20, "prices")

    raw_chp = payload.get("chp")
    if not isinstance(raw_chp, dict) or set(raw_chp) != CHP_KEYS:
        raise Refused("chp must have the exact parameter set")
    chp = {
        "capacity_e": _integer(raw_chp.get("capacity_e"), 1, 12, "chp.capacity_e"),
        "heat_ratio": _integer(raw_chp.get("heat_ratio"), 1, 3, "chp.heat_ratio"),
        "min_up": _integer(raw_chp.get("min_up"), 1, 4, "chp.min_up"),
        "min_down": _integer(raw_chp.get("min_down"), 1, 4, "chp.min_down"),
        "startup_cost": _integer(
            raw_chp.get("startup_cost"), 0, 50, "chp.startup_cost"
        ),
        "fuel_cost": _integer(raw_chp.get("fuel_cost"), 1, 10, "chp.fuel_cost"),
    }
    raw_boiler = payload.get("boiler")
    if not isinstance(raw_boiler, dict) or set(raw_boiler) != BOILER_KEYS:
        raise Refused("boiler must have the exact parameter set")
    boiler = {
        "capacity_heat": _integer(
            raw_boiler.get("capacity_heat"), 0, 30, "boiler.capacity_heat"
        ),
        "heat_cost": _integer(
            raw_boiler.get("heat_cost"), 1, 20, "boiler.heat_cost"
        ),
    }
    raw_storage = payload.get("storage")
    if not isinstance(raw_storage, dict) or set(raw_storage) != STORAGE_KEYS:
        raise Refused("storage must have the exact parameter set")
    capacity = _integer(raw_storage.get("capacity"), 0, 24, "storage.capacity")
    initial_soc = _integer(
        raw_storage.get("initial_soc"), 0, capacity, "storage.initial_soc"
    )
    final_soc = _integer(
        raw_storage.get("final_soc"), 0, capacity, "storage.final_soc"
    )
    storage = {
        "capacity": capacity,
        "initial_soc": initial_soc,
        "final_soc": final_soc,
        "efficiency_percent": _integer(
            raw_storage.get("efficiency_percent"),
            50,
            100,
            "storage.efficiency_percent",
        ),
    }
    return {
        "hours": hours,
        "electric_demand": electric,
        "heat_demand": heat,
        "prices": prices,
        "chp": chp,
        "boiler": boiler,
        "storage": storage,
        "initial_status": _integer(
            payload.get("initial_status"), 0, 1, "initial_status"
        ),
        "initial_streak": _integer(
            payload.get("initial_streak"), 0, 4, "initial_streak"
        ),
        "final_status": _integer(payload.get("final_status"), 0, 1, "final_status"),
    }


def optimize(model: dict[str, Any]) -> dict[str, Any]:
    chp = model["chp"]
    boiler = model["boiler"]
    storage = model["storage"]
    efficiency = storage["efficiency_percent"]
    capacity = storage["capacity"]
    initial_status = model["initial_status"]
    initial_streak = model["initial_streak"]
    if initial_streak == 0:
        initial_streak = 1
    states: dict[tuple[int, int, int], tuple[int, tuple[int, ...], list[dict[str, int]]]] = {
        (storage["initial_soc"], initial_status, initial_streak): (0, (), [])
    }

    for hour in range(model["hours"]):
        next_states: dict[
            tuple[int, int, int],
            tuple[int, tuple[int, ...], list[dict[str, int]]],
        ] = {}
        for (soc, previous_status, streak), (base_cost, actions, rows) in states.items():
            for status in (0, 1):
                if previous_status == 1 and status == 0 and streak < chp["min_up"]:
                    continue
                if previous_status == 0 and status == 1 and streak < chp["min_down"]:
                    continue
                next_streak = streak + 1 if status == previous_status else 1
                chp_electric = chp["capacity_e"] if status else 0
                chp_heat = chp_electric * chp["heat_ratio"]
                grid = max(0, model["electric_demand"][hour] - chp_electric)
                startup = chp["startup_cost"] if previous_status == 0 and status == 1 else 0
                fuel = chp["fuel_cost"] if status else 0
                fixed_cost = (
                    base_cost
                    + startup
                    + fuel
                    + grid * model["prices"][hour]
                )
                for boiler_heat in range(boiler["capacity_heat"] + 1):
                    for net in range(-capacity, capacity + 1):
                        if net > 0:
                            charge = net
                            discharge = 0
                            next_soc = soc + charge * efficiency // 100
                        elif net < 0:
                            charge = 0
                            discharge = -net
                            next_soc = soc - math.ceil(discharge * 100 / efficiency)
                        else:
                            charge = 0
                            discharge = 0
                            next_soc = soc
                        dump = (
                            chp_heat
                            + boiler_heat
                            + discharge
                            - charge
                            - model["heat_demand"][hour]
                        )
                        if dump < 0 or not 0 <= next_soc <= capacity:
                            continue
                        cost = fixed_cost + boiler_heat * boiler["heat_cost"]
                        action = (status, boiler_heat, net)
                        next_actions = actions + action
                        key = (next_soc, status, next_streak)
                        incumbent = next_states.get(key)
                        if incumbent is not None and (
                            incumbent[0] < cost
                            or (incumbent[0] == cost and incumbent[1] <= next_actions)
                        ):
                            continue
                        row = {
                            "boiler_heat": boiler_heat,
                            "charge": charge,
                            "chp_electric": chp_electric,
                            "chp_heat": chp_heat,
                            "chp_on": status,
                            "discharge": discharge,
                            "dump_heat": dump,
                            "grid_electric": grid,
                            "hour": hour,
                            "soc": next_soc,
                        }
                        next_states[key] = (cost, next_actions, rows + [row])
        states = next_states

    feasible = [
        (cost, actions, rows, state)
        for state, (cost, actions, rows) in states.items()
        if state[0] == storage["final_soc"]
        and state[1] == model["final_status"]
        and (
            (state[1] == 1 and state[2] >= chp["min_up"])
            or (state[1] == 0 and state[2] >= chp["min_down"])
        )
    ]
    if not feasible:
        raise Refused("no schedule satisfies the final operating state")
    cost, _actions, rows, _state = min(feasible, key=lambda item: (item[0], item[1]))
    return {"cost": cost, "schedule": rows, "status": "ok"}


def main() -> int:
    if len(sys.argv) != 3:
        print("REFUSED: expected input and output paths", file=sys.stderr)
        return 2
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    try:
        model = parse_input(source)
        result = optimize(model)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    target.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
