# TOP15 全量历史成功/失败样本实证分析 V1

## 1. 数据范围
- 样本行数：29,295
- 唯一快照：1,944
- 唯一币种：131
- 时间跨度：98.595 小时
- 原始快照间隔中位数：0.401 分钟
- V1 连续事件切分间隔：20.0 分钟

## 2. 标签定义（V1）
- 成功样本：`best_pos<=5 and max_chg24>=20 and duration_h>=1.0`
- 失败样本：`best_pos>5 and max_chg24<15 and duration_h<1.0`
- 边界样本：其余全部事件
- 连续事件总数：601
- 成功：50 | 失败：317 | 边界：234

## 3. 启动初期特征对比（以连续事件首个快照为准）
- 起始榜位 中位数：成功 `2.5` | 失败 `14` | 边界 `12.0`
- 起始24h涨幅% 中位数：成功 `21.884999999999998` | 失败 `5.1` | 边界 `7.165`
- 起始24h成交额(百万美元) 中位数：成功 `35.57755689620927` | 失败 `36.97395908154461` | 边界 `37.49296312834403`
- 起始换手率 中位数：成功 `1.7044528742627958` | 失败 `0.2012350464489544` | 边界 `0.3089216297802436`
- 起始1h窗口涨幅% 中位数：成功 `31.024096385542162` | 失败 `11.244657686717572` | 边界 `13.816966949051434`
- 起始4h窗口涨幅% 中位数：成功 `33.22981366459628` | 失败 `11.530383294274113` | 边界 `14.00662625838235`
- 起始结构分 中位数：成功 `6.0` | 失败 `4.0` | 边界 `5.0`
- 起始黑马分 中位数：成功 `10.0` | 失败 `9.0` | 边界 `10.0`
- 起始持续走强分 中位数：成功 `6.0` | 失败 `9.0` | 边界 `9.0`
- 起始交叉分 中位数：成功 `14.5` | 失败 `15.0` | 边界 `16.0`

## 4. 启动初期命中率差异
- 1d/4h/1h 三周期同向强势：成功 `74.0%` | 失败 `50.8%` | 边界 `60.7%`
- 起始 1h 窗口涨幅 >= 10%：成功 `86.0%` | 失败 `53.9%` | 边界 `66.7%`
- 起始 4h 窗口涨幅 >= 15%：成功 `82.0%` | 失败 `38.8%` | 边界 `42.7%`
- 起始黑马分 >= 10：成功 `56.0%` | 失败 `48.3%` | 边界 `51.3%`
- 起始持续走强分 >= 8：成功 `40.0%` | 失败 `61.5%` | 边界 `61.1%`
- 起始交叉分 >= 15：成功 `46.0%` | 失败 `59.3%` | 边界 `60.7%`
- 起始换手率 >= 0.5：成功 `78.0%` | 失败 `27.8%` | 边界 `40.6%`
- 起始换手率 >= 1.0：成功 `62.0%` | 失败 `13.6%` | 边界 `21.8%`
- 起始 1h 存在突破：成功 `36.0%` | 失败 `12.6%` | 边界 `20.9%`
- 起始 4h 存在突破：成功 `48.0%` | 失败 `18.3%` | 边界 `32.1%`
- 起始 1h+4h 双突破：成功 `32.0%` | 失败 `9.1%` | 边界 `17.5%`
- 起始时已在前5：成功 `82.0%` | 失败 `0.0%` | 边界 `17.1%`

## 5. 规则候选（按成功精度排序，V1）
- R11 pos<=5 at start | 命中总数 81 | 成功 41 | 失败 0 | 边界 40 | 成功精度 50.6% | 成功召回 82.0% | 失败占比 0.0%
- R15 trend_all_strong & breakout4h & darkhorse>=10 | 命中总数 95 | 成功 19 | 失败 30 | 边界 46 | 成功精度 20.0% | 成功召回 38.0% | 失败占比 31.6%
- R10 double_breakout | 命中总数 86 | 成功 16 | 失败 29 | 边界 41 | 成功精度 18.6% | 成功召回 32.0% | 失败占比 33.7%
- R7 turnover>=0.5 | 命中总数 222 | 成功 39 | 失败 88 | 边界 95 | 成功精度 17.6% | 成功召回 78.0% | 失败占比 39.6%
- R8 breakout1h | 命中总数 107 | 成功 18 | 失败 40 | 边界 49 | 成功精度 16.8% | 成功召回 36.0% | 失败占比 37.4%
- R3 pc4h>=15 | 命中总数 264 | 成功 41 | 失败 123 | 边界 100 | 成功精度 15.5% | 成功召回 82.0% | 失败占比 46.6%
- R9 breakout4h | 命中总数 157 | 成功 24 | 失败 58 | 边界 75 | 成功精度 15.3% | 成功召回 48.0% | 失败占比 36.9%
- R14 pc1h>=10 & pc4h>=15 & darkhorse>=10 | 命中总数 199 | 成功 26 | 失败 101 | 边界 72 | 成功精度 13.1% | 成功召回 52.0% | 失败占比 50.8%
- R2 pc1h>=10 | 命中总数 370 | 成功 43 | 失败 171 | 边界 156 | 成功精度 11.6% | 成功召回 86.0% | 失败占比 46.2%
- R1 trend_all_strong | 命中总数 340 | 成功 37 | 失败 161 | 边界 142 | 成功精度 10.9% | 成功召回 74.0% | 失败占比 47.4%

## 6. 成功样本示例（前15）
- COS | start_pos 1 | duration 1.33h | best_pos 1 | max_chg24 168.45% | start_pc1h 115.33888228299642 | start_pc4h 111.31855309218201 | start_dark 7.0 | start_persist 2.0
- COS | start_pos 1 | duration 4.17h | best_pos 1 | max_chg24 159.88% | start_pc1h 200.83234244946496 | start_pc4h 111.31855309218201 | start_dark 11.0 | start_persist 3.0
- COS | start_pos 1 | duration 3.59h | best_pos 1 | max_chg24 155.14% | start_pc1h 139.47681331747924 | start_pc4h 135.00583430571763 | start_dark 8.0 | start_persist 2.0
- COS | start_pos 1 | duration 2.25h | best_pos 1 | max_chg24 138.90% | start_pc1h 171.46254458977407 | start_pc4h 164.52742123687278 | start_dark 8.0 | start_persist 2.0
- COS | start_pos 1 | duration 7.70h | best_pos 1 | max_chg24 130.35% | start_pc1h 153.9833531510107 | start_pc4h 164.52742123687278 | start_dark 7.0 | start_persist 1.0
- CFG | start_pos 1 | duration 20.17h | best_pos 1 | max_chg24 108.93% | start_pc1h None | start_pc4h None | start_dark 5.0 | start_persist 0.0
- COS | start_pos 1 | duration 4.50h | best_pos 1 | max_chg24 96.21% | start_pc1h 78.47800237812129 | start_pc4h 75.26254375729289 | start_dark 12.0 | start_persist None
- G | start_pos 1 | duration 2.09h | best_pos 1 | max_chg24 90.82% | start_pc1h 76.56249999999997 | start_pc4h 44.75308641975309 | start_dark 13.0 | start_persist 5.0
- C | start_pos 2 | duration 8.54h | best_pos 1 | max_chg24 75.14% | start_pc1h 67.28395061728395 | start_pc4h 64.25619834710744 | start_dark 11.0 | start_persist 6.0
- G | start_pos 2 | duration 12.75h | best_pos 1 | max_chg24 73.16% | start_pc1h 86.56249999999997 | start_pc4h 84.25925925925925 | start_dark 14.0 | start_persist 8.0
- C | start_pos 2 | duration 1.01h | best_pos 2 | max_chg24 67.95% | start_pc1h 65.22633744855966 | start_pc4h 65.9090909090909 | start_dark 18.0 | start_persist 10.0
- G | start_pos 1 | duration 7.51h | best_pos 1 | max_chg24 65.30% | start_pc1h 41.249999999999986 | start_pc4h 39.197530864197546 | start_dark 20.0 | start_persist 11.0
- REZ | start_pos 1 | duration 14.93h | best_pos 1 | max_chg24 63.51% | start_pc1h 30.34055727554181 | start_pc4h 31.5625 | start_dark 13.0 | start_persist 7.0
- DEGO | start_pos 11 | duration 23.01h | best_pos 1 | max_chg24 61.45% | start_pc1h 288.07692307692304 | start_pc4h 188.28571428571428 | start_dark 11.0 | start_persist 6.0
- ENJ | start_pos 9 | duration 18.17h | best_pos 1 | max_chg24 60.35% | start_pc1h 14.128642111050024 | start_pc4h 14.696132596685077 | start_dark 12.0 | start_persist 13.0

## 7. 失败样本示例（前15）
- HOOK | start_pos 8 | duration 0.09h | best_pos 6 | max_chg24 9.65% | start_pc1h 22.222222222222214 | start_pc4h 23.65591397849463 | start_dark 7.0 | start_persist 6.0
- CFX | start_pos 7 | duration 0.59h | best_pos 6 | max_chg24 10.82% | start_pc1h 26.198486122792257 | start_pc4h 27.539311517212067 | start_dark 11.0 | start_persist 10.0
- PLUME | start_pos 6 | duration 0.34h | best_pos 6 | max_chg24 11.57% | start_pc1h -7.563636363636358 | start_pc4h -9.149392423159398 | start_dark -1.0 | start_persist -4.0
- TOWNS | start_pos 6 | duration 0.09h | best_pos 6 | max_chg24 14.00% | start_pc1h 29.21686746987953 | start_pc4h 33.22981366459628 | start_dark 8.0 | start_persist 5.0
- SXP | start_pos 7 | duration 0.75h | best_pos 7 | max_chg24 5.88% | start_pc1h -31.862745098039223 | start_pc4h -31.753554502369674 | start_dark -13.0 | start_persist None
- HOOK | start_pos 7 | duration 0.17h | best_pos 7 | max_chg24 8.11% | start_pc1h 21.69312169312169 | start_pc4h 23.65591397849463 | start_dark 7.0 | start_persist 6.0
- LA | start_pos 7 | duration 0.01h | best_pos 7 | max_chg24 9.27% | start_pc1h 6.744379683597011 | start_pc4h 11.236442516268982 | start_dark 9.0 | start_persist 9.0
- DEXE | start_pos 7 | duration 0.09h | best_pos 7 | max_chg24 11.81% | start_pc1h 47.125798389336296 | start_pc4h 45.309928688974225 | start_dark 9.0 | start_persist 7.0
- G | start_pos 12 | duration 0.26h | best_pos 7 | max_chg24 13.58% | start_pc1h 60.937499999999986 | start_pc4h 76.54320987654323 | start_dark 9.0 | start_persist 5.0
- AUDIO | start_pos 11 | duration 0.84h | best_pos 8 | max_chg24 5.96% | start_pc1h -5.152758777929788 | start_pc4h -2.9990627928772335 | start_dark 0.0 | start_persist -2.0
- HUMA | start_pos 15 | duration 0.42h | best_pos 8 | max_chg24 6.19% | start_pc1h 17.26114649681529 | start_pc4h 9.631391200951247 | start_dark 0.0 | start_persist -2.0
- POWR | start_pos 8 | duration 0.16h | best_pos 8 | max_chg24 7.08% | start_pc1h 13.237639553429007 | start_pc4h 14.308681672025722 | start_dark 10.0 | start_persist 11.0
- TLM | start_pos 15 | duration 0.84h | best_pos 8 | max_chg24 7.44% | start_pc1h 7.495429616087741 | start_pc4h 7.829839704069047 | start_dark 5.0 | start_persist 4.0
- PIXEL | start_pos 8 | duration 0.83h | best_pos 8 | max_chg24 8.71% | start_pc1h 165.44715447154474 | start_pc4h 160.1593625498008 | start_dark 7.0 | start_persist 6.0
- NEIRO | start_pos 8 | duration 0.09h | best_pos 8 | max_chg24 8.84% | start_pc1h 18.118195956454116 | start_pc4h 16.113744075829388 | start_dark 14.0 | start_persist 12.0

## 8. V1 科学结论
- 当前数据已经足够支撑第一轮实证分析与规则筛选。
- 但当前时间跨度约 4.1 天，只能支持“阶段性规律”，不能直接宣称长期稳定的确定性规则。
- 从首快照对比看，成功样本整体更倾向于：更高的 1h/4h 动能、更高的黑马/持续走强分、更强的三周期同向。
- 仅靠 darkhorse/persistence/overlap 静态高分并不足够，失败样本中也存在高分但持续性差、榜位推进弱的案例。
- 下一阶段应重点增加：榜位前移速度、从首次入榜到进入前5的用时、分数斜率、放量突破持续时间。