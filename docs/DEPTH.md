# 深度登记 水库库容插值与日水量收支

- 规模：中型
- 核心规则：单调水位库容曲线分段线性插值；流量梯形积分；缺口超限不插补，日边界拆分且收支误差显式归因
- 使用者与工作流：水库调度数据员；采信水位流量日志，复核日库容变化与入出库偏差

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 测站采信 | 采信水位流量与来源 | `/api/m1` | `app/modules/m1_receive/rules.py` `app/modules/m1_receive/service.py` | `tests/test_m1_receive.py` |
| M2 曲线校核 | 校验曲线及测次冲突 | `/api/m2` | `app/modules/m2_curve/rules.py` `app/modules/m2_curve/service.py` | `tests/test_m2_curve.py` |
| M3 流量积分 | 梯形积分并定位缺口 | `/api/m3` | `app/modules/m3_integrate/rules.py` `app/modules/m3_integrate/service.py` | `tests/test_m3_integrate.py` |
| M4 库容换算 | 按曲线分段换算库容 | `/api/m4` | `app/modules/m4_storage/rules.py` `app/modules/m4_storage/service.py` | `tests/test_m4_storage.py` |
| M5 日收支 | 跨午夜切分日水量账 | `/api/m5` | `app/modules/m5_budget/rules.py` `app/modules/m5_budget/service.py` | `tests/test_m5_budget.py` |
| M6 异常复核 | 按缺测优先裁决超差 | `/api/m6` | `app/modules/m6_review/rules.py` `app/modules/m6_review/service.py` | `tests/test_m6_review.py` |
| M7 重算留痕 | 核对总积分与重算水位 | `/api/m7` | `app/modules/m7_trace/rules.py` `app/modules/m7_trace/service.py` | `tests/test_m7_trace.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | GB18030测站 | 静默填补或算错 | 明确隔离和守恒 | `app/modules/m1_receive/rules.py` | `tests/test_m1_receive.py::test_legacy_encoding` |
| TRAP-06 | 全角流量 | 静默填补或算错 | 明确隔离和守恒 | `app/modules/m2_curve/rules.py` | `tests/test_m2_curve.py::test_fullwidth` |
| TRAP-07 | 未知水位 | 静默填补或算错 | 明确隔离和守恒 | `app/modules/m2_curve/rules.py` | `tests/test_m2_curve.py::test_sentinel` |
| TRAP-10 | 小数插值 | 静默填补或算错 | 明确隔离和守恒 | `app/modules/m4_storage/rules.py` | `tests/test_m4_storage.py::test_decimal_precision` |
| TRAP-13 | 缺口和乱序 | 静默填补或算错 | 明确隔离和守恒 | `app/modules/m3_integrate/rules.py` | `tests/test_m3_integrate.py::test_real_late_point_retained` |
| TRAP-14 | 同刻水文矛盾 | 静默填补或算错 | 明确隔离和守恒 | `app/modules/m2_curve/rules.py` | `tests/test_m2_curve.py::test_real_conflict` |
| TRAP-15 | 升每秒换算 | 静默填补或算错 | 明确隔离和守恒 | `app/modules/m2_curve/rules.py` | `tests/test_m2_curve.py::test_unit_conversion` |
| TRAP-23 | 午夜切分 | 静默填补或算错 | 明确隔离和守恒 | `app/modules/m5_budget/rules.py` | `tests/test_m5_budget.py::test_midnight_split` |
| TRAP-31 | 改版同一水位被算成水量 | 新旧曲线库容直接相减混入库变/收支差 | T点调整单列 `curve_adjust`，不进 `storage_change` 与 `residual` | `app/modules/m5_budget/rules.py` | `tests/test_curve_switch.py::test_adjustment_separate_from_storage_change` |
| TRAP-32 | 重复运行同一改版重复调整 | 每次重跑再加一次调整量 | 调整每站仅登记一次，参数参与幂等ID，登记按生效时刻去重 | `app/modules/m5_budget/rules.py` `app/store.py` | `tests/test_curve_switch.py::test_rerun_same_switch_adjusts_once` `test_revision_registry_idempotent_and_conflict` |
| TRAP-33 | 已复核日账被新曲线改写 | 重算覆盖历史确认值 | 确认日整行快照替换、保持原曲线，未确认日续跑 | `app/store.py` | `tests/test_curve_switch.py::test_confirmed_day_keeps_old_curve_on_rerun` |
| TRAP-34 | 生效时刻落在缺口仍硬切 | 外推或静默制造库容 | 判 `CURVE_SWITCH` 整体失败，不存批次不登记，旧账保留 | `app/modules/m5_budget/rules.py` `app/modules/m2_curve/handler.py` | `tests/test_curve_switch.py::test_switch_in_gap_fails_and_old_ledger_remains` |
| TRAP-35 | 生效时刻与观测/日界重合漏调整 | 边界分支只算一侧曲线 | 边界分支补登记一次T点调整 | `app/modules/m5_budget/rules.py` | `tests/test_curve_switch.py::test_adjustment_separate_from_storage_change` |

## 对账规则

输入逻辑行数 = 采信行数 + 隔离行数；空行单列。每条重复、冲突、超限、缺失均保留原始行号与原因码。计算阶段的输出数量可聚合，原始采信records始终保留，业务平衡另按模块给出的重量、时长、电量或座席数量核对。
相同输入摘要、规则版本、参数产生相同批次ID。运行原子插入SQLite；复核使用整数版本乐观锁。

## 曲线改版留痕

`curve_revisions` 按生效时刻保存新曲线与试算批次；`confirmed_days` 保存复核通过完整日的整行快照。切换失败（含缺口、越界、已确认日冲突）不写任何新表。曲线调整量与物理库变分列，M7 的日切积分守恒只核流量体积，不受曲线改版影响。

## 已知不覆盖

库容曲线采用线性分段，不作范围外推；流量与水位相邻点间线性变化。未建蒸发降雨及地下渗漏模型，收支差保留待人工归因。不做外部调度，曲线改版调整仅作曲线口径差异列示，不生成入出库水量。
