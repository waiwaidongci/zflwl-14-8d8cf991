from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ENTRY = os.environ.get("THERMAL_ENTRY", "/app/dispatch.py")

SAFE_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
}


def _run(payload: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-S", "-P", "-B", ENTRY, str(payload), str(output)],
        text=True,
        capture_output=True,
        env=SAFE_ENV,
        timeout=30,
        check=False,
    )


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _example_payload() -> dict[str, object]:
    return {
        "schema": "heat-dispatch-v1",
        "hours": 4,
        "electric_demand": [3, 5, 2, 6],
        "heat_demand": [4, 4, 3, 5],
        "prices": [3, 12, 2, 15],
        "chp": {"capacity_e": 4, "heat_ratio": 1, "min_up": 2, "min_down": 1, "startup_cost": 7, "fuel_cost": 4},
        "boiler": {"capacity_heat": 8, "heat_cost": 6},
        "storage": {"capacity": 6, "initial_soc": 1, "final_soc": 1, "efficiency_percent": 90},
        "initial_status": 0,
        "initial_streak": 2,
        "final_status": 0,
    }


def _storage_payload() -> dict[str, object]:
    return {
        "schema": "heat-dispatch-v1",
        "hours": 4,
        "electric_demand": [0, 5, 0, 5],
        "heat_demand": [4, 4, 4, 4],
        "prices": [1, 20, 1, 20],
        "chp": {"capacity_e": 5, "heat_ratio": 2, "min_up": 1, "min_down": 1, "startup_cost": 3, "fuel_cost": 3},
        "boiler": {"capacity_heat": 8, "heat_cost": 8},
        "storage": {"capacity": 4, "initial_soc": 1, "final_soc": 1, "efficiency_percent": 100},
        "initial_status": 0,
        "initial_streak": 1,
        "final_status": 0,
    }


def _minimum_run_payload() -> dict[str, object]:
    return {
        "schema": "heat-dispatch-v1",
        "hours": 4,
        "electric_demand": [5, 5, 5, 5],
        "heat_demand": [4, 4, 4, 4],
        "prices": [20, 20, 20, 20],
        "chp": {"capacity_e": 5, "heat_ratio": 1, "min_up": 3, "min_down": 2, "startup_cost": 2, "fuel_cost": 5},
        "boiler": {"capacity_heat": 8, "heat_cost": 8},
        "storage": {"capacity": 0, "initial_soc": 0, "final_soc": 0, "efficiency_percent": 100},
        "initial_status": 0,
        "initial_streak": 2,
        "final_status": 1,
    }


def test_gate_schedule_meets_heat_balance_and_final_state(tmp_path: Path) -> None:
    # case_id: HD-BALANCE-01 HD-OUT-01 HD-CONTEXT-01 HD-INPUT-01 HD-STATUS-01 HD-OUT-02 HD-STATUS-02 HD-OUT-03
    """题面：
    「输入最外层只有 `schema`、`hours`、`electric_demand`、`heat_demand`、`prices`、」
    """

    source = tmp_path / "example.json"
    output = tmp_path / "example.out.json"
    _write(source, _example_payload())
    completed = _run(source, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert result["status"] == "ok"
    assert result["schedule"][-1]["chp_on"] == 0
    assert result["schedule"][-1]["soc"] == 1
    assert result["cost"] == 151


def test_chp_fuel_cost_is_fixed_per_operating_hour(tmp_path: Path) -> None:
    """题面：
    「`fuel_cost` 是每个开机小时支付的固定燃料费」
    「不乘 `capacity_e`、实际发电量或热比；停机小时不计燃料费」
    """

    # case_id: HD-FUEL-01
    payload = {
        "schema": "heat-dispatch-v1",
        "hours": 4,
        "electric_demand": [0, 0, 0, 0],
        "heat_demand": [0, 0, 0, 0],
        "prices": [1, 1, 1, 1],
        "chp": {"capacity_e": 5, "heat_ratio": 1, "min_up": 1, "min_down": 1, "startup_cost": 2, "fuel_cost": 5},
        "boiler": {"capacity_heat": 0, "heat_cost": 1},
        "storage": {"capacity": 0, "initial_soc": 0, "final_soc": 0, "efficiency_percent": 100},
        "initial_status": 0,
        "initial_streak": 0,
        "final_status": 1,
    }
    source = tmp_path / "fuel-cost.json"
    output = tmp_path / "fuel-cost.out.json"
    _write(source, payload)
    completed = _run(source, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert result["cost"] == 7
    assert [row["chp_on"] for row in result["schedule"]] == [0, 0, 0, 1]


def test_minimum_up_and_down_times_shape_commitment(tmp_path: Path) -> None:
    # case_id: HD-COMMIT-01 HD-TIE-01 HD-GREEDY-02 HD-TIE-02
    """题面：
    「30，单位热量成本为 1 到 20。储热容量为 0 到 24，初末库存都必须落在 `0..capacity`」
    """

    source = tmp_path / "minimum-run.json"
    output = tmp_path / "minimum-run.out.json"
    _write(source, _minimum_run_payload())
    completed = _run(source, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert result["cost"] == 22
    assert [row["chp_on"] for row in result["schedule"]] == [1, 1, 1, 1]


def test_final_on_streak_at_minimum_up_is_accepted(tmp_path: Path) -> None:
    # case_id: HD-COMMIT-02
    """题面：
    「的整数，购电价是 1 到 20 的整数。`initial_status`、`final_status` 只能为 0 或 1，」
    """

    payload = _minimum_run_payload()
    payload["chp"]["min_up"] = 4
    source = tmp_path / "minimum-up-exact.json"
    output = tmp_path / "minimum-up-exact.out.json"
    _write(source, payload)
    completed = _run(source, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert result["cost"] == 22
    assert [row["chp_on"] for row in result["schedule"]] == [1, 1, 1, 1]


def test_storage_shift_respects_final_inventory(tmp_path: Path) -> None:
    # case_id: HD-STORAGE-01 HD-FIELDS-01 HD-FIELDS-02
    """题面：
    「`schedule` 每小时恰好有一个对象，字段为 `hour`、`chp_on`、`chp_electric`、`chp_heat`、」
    """

    source = tmp_path / "storage.json"
    output = tmp_path / "storage.out.json"
    _write(source, _storage_payload())
    completed = _run(source, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert result["cost"] == 120
    assert [row["soc"] for row in result["schedule"]] == [0, 0, 4, 1]
    assert result["schedule"][-1]["discharge"] == 3


def test_storage_capacity_upper_bound_is_accepted(tmp_path: Path) -> None:
    # case_id: HD-LIMIT-01
    """题面：
    「`REFUSED: <原因>`，退出码为 2。程序成功时不在终端留字，JSON 用无空格、按键排序的」
    """

    payload = _storage_payload()
    payload["storage"] = {
        "capacity": 24,
        "initial_soc": 0,
        "final_soc": 0,
        "efficiency_percent": 50,
    }
    source = tmp_path / "capacity.json"
    output = tmp_path / "capacity.out.json"
    _write(source, payload)
    completed = _run(source, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert result["status"] == "ok"
    assert result["schedule"][-1]["soc"] == 0


def test_efficiency_below_public_limit_is_refused(tmp_path: Path) -> None:
    # case_id: HD-LIMIT-02 HD-FAIL-01
    """题面：
    「输入损坏或没有满足末状态的计划时，不创建输出文件；标准错误输出一行」
    """

    payload = _storage_payload()
    payload["storage"]["efficiency_percent"] = 49
    source = tmp_path / "efficiency.json"
    output = tmp_path / "efficiency.out.json"
    _write(source, payload)
    completed = _run(source, output)
    assert completed.returncode == 2
    assert completed.stderr.startswith("REFUSED: ")
    assert not output.exists()


def test_hourly_array_length_mismatch_is_refused(tmp_path: Path) -> None:
    # case_id: HD-SCHEMA-01 HD-INPUT-02
    """题面：
    「储热罐又不能让夜间最后一个小时留下偏差；如果只看眼前电价启停机组，凌晨会把燃料费」
    """

    payload = _example_payload()
    payload["prices"].pop()
    source = tmp_path / "length.json"
    output = tmp_path / "length.out.json"
    _write(source, payload)
    completed = _run(source, output)
    assert completed.returncode == 2
    assert completed.stderr.startswith("REFUSED: ")
    assert not output.exists()


def test_boolean_integer_field_is_refused(tmp_path: Path) -> None:
    # case_id: HD-BOOL-01
    """题面：
    「储热每小时只能选择充或放一侧。充电量先乘以效率百分比再向下取整进入库存；放电时需要」
    """

    payload = _example_payload()
    payload["chp"]["capacity_e"] = True
    source = tmp_path / "boolean.json"
    output = tmp_path / "boolean.out.json"
    _write(source, payload)
    completed = _run(source, output)
    assert completed.returncode == 2
    assert completed.stderr.startswith("REFUSED: ")
    assert not output.exists()


def test_success_output_is_canonical_and_silent(tmp_path: Path) -> None:
    # case_id: HD-SER-01
    """题面：
    「`schedule` 每小时恰好有一个对象，字段为 `hour`、`chp_on`、`chp_electric`、`chp_heat`、」
    """

    source = tmp_path / "example.json"
    output = tmp_path / "canonical.json"
    _write(source, _example_payload())
    completed = _run(source, output)
    raw = output.read_bytes()
    parsed = json.loads(raw)
    canonical = (
        json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert raw == canonical


def test_cli_argument_arity_contract(tmp_path: Path) -> None:
    # case_id: HD-ARG-01
    """题面：
    「30，单位热量成本为 1 到 20。储热容量为 0 到 24，初末库存都必须落在 `0..capacity`」
    """

    source = tmp_path / "cli-arity.json"
    output = tmp_path / "cli-arity.out.json"
    _write(source, _example_payload())
    completed = subprocess.run(
        [sys.executable, "-S", "-P", "-B", ENTRY, str(source), str(output), "extra"],
        text=True,
        capture_output=True,
        env=SAFE_ENV,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stderr.startswith("REFUSED: ")
    assert not output.exists()
