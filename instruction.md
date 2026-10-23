# 寒潮前的热电储热班次

园区在寒潮来临时会同时抬高电负荷和换热站需求。热电联产机组一旦点火就有最短运行时间，
储热罐又不能让夜间最后一个小时留下偏差；如果只看眼前电价启停机组，凌晨会把燃料费
浪费在反复点火上。请把 `/app/dispatch.py` 中的贪心逻辑改成整段时窗内的最低成本计划。

运行时仍使用 `python3 /app/dispatch.py <input.json> <output.json>`。模型依赖镜像内
Python 标准库，不查询外部电价或天气服务。

## 调度输入

输入最外层只有 `schema`、`hours`、`electric_demand`、`heat_demand`、`prices`、
`chp`、`boiler`、`storage`、`initial_status`、`initial_streak`、`final_status`。

```json
{
  "schema": "heat-dispatch-v1",
  "hours": 4,
  "electric_demand": [3, 5, 2, 6],
  "heat_demand": [4, 4, 3, 5],
  "prices": [3, 12, 2, 15],
  "chp": {
    "capacity_e": 4,
    "heat_ratio": 1,
    "min_up": 2,
    "min_down": 1,
    "startup_cost": 7,
    "fuel_cost": 4
  },
  "boiler": {
    "capacity_heat": 8,
    "heat_cost": 6
  },
  "storage": {
    "capacity": 6,
    "initial_soc": 1,
    "final_soc": 1,
    "efficiency_percent": 90
  },
  "initial_status": 0,
  "initial_streak": 2,
  "final_status": 0
}
```

`hours` 是 4 到 10 的整数。三个逐时数组的长度都等于 `hours`：电负荷与热负荷是 0 到 30
的整数，购电价是 1 到 20 的整数。`initial_status`、`final_status` 只能为 0 或 1，
`initial_streak` 是 0 到 4 的整数。

机组参数 `capacity_e` 为 1 到 12，`heat_ratio` 为 1 到 3，最小开停机时间各为 1 到 4；
每次从停机切到开机还要支付 `startup_cost`，燃料成本按全部发电量计算。锅炉上限为 0 到
30，单位热量成本为 1 到 20。储热容量为 0 到 24，初末库存都必须落在 `0..capacity`
之内，单向效率为 50 到 100 的整数百分比。布尔值不能冒充任何整数字段。

## 逐时物理关系

开机的 CHP 固定发出 `capacity_e` 千瓦时电，并同时产生 `capacity_e * heat_ratio` 千瓦时热。
不足的电由电网补足，CHP 多发的电不计收益。热侧由 CHP、锅炉和储热共同满足；多余的
热量可以排空。

储热每小时只能选择充或放一侧。充电量先乘以效率百分比再向下取整进入库存；放电时需要
向上取整消耗库存。充放之后库存仍在 `0..capacity` 内。相邻小时的开关状态还要满足
最小连续运行和最小连续停机时间，且最终状态与 `final_status` 一致。

## 选优与结果

总成本是燃料费、启动费、购电费和锅炉热量费之和，整段时窗成本最低者胜出。成本相同时，
按小时比较 `chp_on`、`boiler_heat`、储热净流量的动作元组，动作较小者优先。

成功结果由 `status`、`schedule`、`cost` 三部分组成。`status` 是 `"ok"`，`cost` 是整数；
`schedule` 每小时恰好有一个对象，字段为 `hour`、`chp_on`、`chp_electric`、`chp_heat`、
`grid_electric`、`boiler_heat`、`charge`、`discharge`、`dump_heat`、`soc`。`hour` 从 0
开始递增，`chp_on` 是 0 或 1，其余能量字段为非负整数。

输入损坏或没有满足末状态的计划时，不创建输出文件；标准错误输出一行
`REFUSED: <原因>`，退出码为 2。程序成功时不在终端留字，JSON 用无空格、按键排序的
写法，文件最后保留一个换行。
