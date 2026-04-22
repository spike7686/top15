# TOP15 路径研究小结 V1

## 1. 结论
- 现阶段新路径字段已经足以开始研究“榜位推进”与“交叉确认成立”之间的时间关系。
- 当前最重要的新发现：**很多强势币是先快速冲进前5/前3，再经过更长时间才完成正式交叉确认。**
- 这说明 `overlap_candidate` 更偏“持续性确认信号”，不是“瞬时强势识别信号”。

## 2. 当前正式交叉候选样本概览
- 当前正式交叉候选数：10
- median_hours_to_top10: 0.0
- median_hours_to_top5: 0.1275
- median_hours_to_top3: 0.626
- median_entry_to_confirmation_hours: 1.446
- median_episode_duration_h: 3.088

## 3. 当前正式交叉候选路径明细
- ENJ | 当前排名 1 | 事件起点 2026-03-17T23:40:01.718636+08:00 | 事件持续 20.083h | 到Top10 0.0h | 到Top5 0.167h | 到Top3 0.745h | 到正式确认 17.539h | overlap 20
- ANKR | 当前排名 2 | 事件起点 2026-03-18T07:39:42.554292+08:00 | 事件持续 12.089h | 到Top10 0.499h | 到Top5 0.583h | 到Top3 0.583h | 到正式确认 9.544h | overlap 19
- CHR | 当前排名 3 | 事件起点 2026-03-18T17:44:42.798814+08:00 | 事件持续 2.005h | 到Top10 0.0h | 到Top5 0.0h | 到Top3 0.0h | 到正式确认 1.005h | overlap 16
- VANRY | 当前排名 4 | 事件起点 2026-03-18T16:39:45.329935+08:00 | 事件持续 3.088h | 到Top10 0.168h | 到Top5 0.544h | 到Top3 0.669h | 到正式确认 1.446h | overlap 18
- HOT | 当前排名 5 | 事件起点 2026-03-18T15:44:43.872389+08:00 | 事件持续 4.005h | 到Top10 0.0h | 到Top5 0.088h | 到Top3 0.838h | 到正式确认 1.461h | overlap 17
- JST | 当前排名 7 | 事件起点 2026-03-18T18:06:31.220457+08:00 | 事件持续 1.642h | 到Top10 0.392h | 到Top5 Noneh | 到Top3 Noneh | 到正式确认 1.055h | overlap 16
- AUCTION | 当前排名 12 | 事件起点 2026-03-18T14:30:02.035469+08:00 | 事件持续 5.25h | 到Top10 0.0h | 到Top5 0.0h | 到Top3 0.083h | 到正式确认 2.706h | overlap 16
- ATOM | 当前排名 14 | 事件起点 2026-03-18T17:35:01.340660+08:00 | 事件持续 2.167h | 到Top10 0.662h | 到Top5 Noneh | 到Top3 Noneh | 到正式确认 1.0h | overlap 15
- YFI | 当前排名 14 | 事件起点 None | 事件持续 Noneh | 到Top10 Noneh | 到Top5 Noneh | 到Top3 Noneh | 到正式确认 Noneh | overlap 15
- AXS | 当前排名 15 | 事件起点 2026-03-18T18:45:02.066015+08:00 | 事件持续 1.0h | 到Top10 0.0h | 到Top5 Noneh | 到Top3 Noneh | 到正式确认 1.0h | overlap 16

## 4. 确认滞后（正式确认 - 进入Top5）
- ENJ | 确认滞后Top5 17.372h | 确认滞后Top3 16.794h | 到Top5 0.167h | 到确认 17.539h
- ANKR | 确认滞后Top5 8.961h | 确认滞后Top3 8.961h | 到Top5 0.583h | 到确认 9.544h
- AUCTION | 确认滞后Top5 2.706h | 确认滞后Top3 2.623h | 到Top5 0.0h | 到确认 2.706h
- HOT | 确认滞后Top5 1.373h | 确认滞后Top3 0.623h | 到Top5 0.088h | 到确认 1.461h
- CHR | 确认滞后Top5 1.005h | 确认滞后Top3 1.005h | 到Top5 0.0h | 到确认 1.005h
- VANRY | 确认滞后Top5 0.902h | 确认滞后Top3 0.777h | 到Top5 0.544h | 到确认 1.446h
- JST | 确认滞后Top5 Noneh | 确认滞后Top3 Noneh | 到Top5 Noneh | 到确认 1.055h
- ATOM | 确认滞后Top5 Noneh | 确认滞后Top3 Noneh | 到Top5 Noneh | 到确认 1.0h
- YFI | 确认滞后Top5 Noneh | 确认滞后Top3 Noneh | 到Top5 Noneh | 到确认 Noneh
- AXS | 确认滞后Top5 Noneh | 确认滞后Top3 Noneh | 到Top5 Noneh | 到确认 1.0h

## 5. 路径分类（启发式）
- ENJ | FastRank_SlowConfirm | rank60m 0 | 到Top5 0.167h | 到确认 17.539h
- ANKR | MixedPath | rank60m 0 | 到Top5 0.583h | 到确认 9.544h
- CHR | MixedPath | rank60m 0 | 到Top5 0.0h | 到确认 1.005h
- VANRY | MixedPath | rank60m 0 | 到Top5 0.544h | 到确认 1.446h
- HOT | MixedPath | rank60m 0 | 到Top5 0.088h | 到确认 1.461h
- JST | Unclassified | rank60m 2 | 到Top5 Noneh | 到确认 1.055h
- AUCTION | FastRank_SlowConfirm | rank60m 3 | 到Top5 0.0h | 到确认 2.706h
- ATOM | Unclassified | rank60m -3 | 到Top5 Noneh | 到确认 1.0h
- YFI | Unclassified | rank60m None | 到Top5 Noneh | 到确认 Noneh
- AXS | Unclassified | rank60m -8 | 到Top5 Noneh | 到确认 1.0h

## 6. 当前研究判断
- ENJ / ANKR / HOT / VANRY / AUCTION / CHR 这批样本共同显示：榜位推进往往早于交叉确认成立。
- 因此后续模型应把“榜位推进速度”与“确认滞后时间”分开研究。
- 若目标是更早识别潜在黑马，不能只等 `overlap_candidate=true`；还要结合 `hours_to_top5`、`rank_change_30m/60m`、分数斜率一起判断。
- 若目标是筛选高确定性正式候选，则 `entry_to_confirmation_hours` 与 `current_episode_duration_hours` 很关键。