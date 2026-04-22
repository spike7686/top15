# TOP15 路径研究小结 V2

## 1. 结论
- 路径研究 V2 已完成第一轮真正落地：不仅有设计稿，采集主链路也已经把 **确认滞后层 + 确认前稳定性层 + 事件密度层 + V2 路径分类** 写入 `latest/history/display`。
- 当前最重要的新结论：
  1. **“确认滞后”字段现在已按更严格口径收紧**，只在“先进入 Top5/Top3，再发生确认”时才计算 lag；否则记为 `None`，避免把“先确认后进前排”的样本误当成负滞后。
  2. **当前正式交叉候选里，已出现明确的 FastRank_FastConfirm 与 SlowRank_FastConfirm 两类样本。**
  3. **确认前稳定性字段已经能直接用于比较不同样本的路径质量**，不再只靠主观观察。

---

## 2. 本轮已正式落地的 V2 字段

### 2.1 确认滞后层
- `confirmation_lag_vs_top10_h`
- `confirmation_lag_vs_top5_h`
- `confirmation_lag_vs_top3_h`
- `top10_to_top5_hours`
- `top5_to_top3_hours`
- `top3_to_confirmation_hours`

### 2.2 事件表现 / 密度层
- `episode_snapshot_count`
- `episode_best_rank`
- `episode_worst_rank`
- `episode_rank_improve_range`
- `episode_confirmation_snapshot_index`
- `episode_confirmation_progress_ratio`

### 2.3 确认前稳定性层
- `episode_best_rank_before_confirmation`
- `episode_worst_rank_before_confirmation`
- `pre_confirmation_rank_range`
- `pre_confirmation_rank_std`
- `pre_confirmation_top10_presence_ratio`
- `pre_confirmation_top5_presence_ratio`
- `pre_confirmation_top3_presence_ratio`

### 2.4 路径分类层
- `path_class_v2`

---

## 3. 本轮口径修正

### 3.1 为什么要修正 lag 字段
早先直接用：
- `entry_to_confirmation_hours - hours_to_top5`
- `entry_to_confirmation_hours - hours_to_top3`

会把“确认发生时还没进 Top5/Top3”的样本也算进去，产生负值。

### 3.2 新口径
现在改为：
- **只有当 `hours_to_top5 <= entry_to_confirmation_hours` 时，`confirmation_lag_vs_top5_h` 才有效**
- **只有当 `hours_to_top3 <= entry_to_confirmation_hours` 时，`confirmation_lag_vs_top3_h` 才有效**
- 否则统一记为 `None`

### 3.3 专业解释
这相当于把 lag 字段从“机械时间差”修正为“有因果顺序约束的阶段差值”。

也就是：
- 先发生 A，再发生 B，才研究 `B - A`
- 如果 A 根本还没发生，就不应硬算差值

---

## 4. 当前正式交叉候选概览（本轮最新快照）

- 当前正式交叉候选数：4
- median_hours_to_top10: 0.0
- median_hours_to_top5: 0.917
- median_hours_to_top3: 3.251
- median_entry_to_confirmation_hours: 1.002
- median_confirmation_lag_vs_top5_h: 0.543
- median_pre_confirmation_rank_range: 4.5
- median_pre_confirmation_rank_std: 1.022

---

## 5. 当前正式交叉候选路径明细

### 5.1 SAHARA
- 当前排名：3
- 到 Top5：0.0h
- 到正式确认：1.0h
- 确认滞后 Top5：1.0h
- 确认前排名波动区间：3
- 确认前排名标准差：0.597
- 路径分类：`FastRank_FastConfirm`

**判断：**
这是当前最标准的“快速冲前排 + 较快完成确认”的样本之一，且确认前稳定性不错。

### 5.2 QNT
- 当前排名：4
- 到 Top5：0.917h
- 到正式确认：1.004h
- 确认滞后 Top5：0.087h
- 确认前排名波动区间：2
- 确认前排名标准差：0.566
- 路径分类：`SlowRank_FastConfirm`

**判断：**
它不是“起步即冲前排”，但一旦推进到前排，确认跟得非常快，而且确认前路径很稳。

### 5.3 JST
- 当前排名：6
- 到 Top5：3.973h
- 到正式确认：1.055h
- 确认滞后 Top5：None
- 确认前排名波动区间：6
- 确认前排名标准差：1.796
- 路径分类：`Unclassified`

**判断：**
这是典型的“确认先于 Top5”的样本。说明系统会在它尚未进入前五前，就已给出正式交叉确认。路径波动也较大，不适合被简单归入稳健快确认模板。

### 5.4 TRX
- 当前排名：11
- 到 Top5：None
- 到正式确认：1.0h
- 确认滞后 Top5：None
- 确认前排名波动区间：6
- 确认前排名标准差：1.448
- 路径分类：`Unclassified`

**判断：**
这是另一个重要样本：它说明正式确认并不严格依赖“先进入 Top5”。也就是说，`overlap_candidate` 的本质仍然更偏综合确认，而不是单纯前排榜位门槛。

---

## 6. 当前 V2 路径分类分布
- `FastRank_FastConfirm`: 2
- `SlowRank_FastConfirm`: 1
- `Unclassified`: 10

### 解读
- 当前样本里，**FastConfirm（确认快）已经能看到，但 SlowConfirm（确认慢）这一轮快照里暂时没出现典型样本。**
- `Unclassified` 仍然很多，说明当前 V2 分类规则还是偏保守，属于合理现象。
- 这也再次说明：**现阶段更适合把 `path_class_v2` 作为研究标签，而不是直接作为交易规则。**

---

## 7. 当前研究判断

### 7.1 已经可以确认的事情
1. **V2 不是纸面设计了，已经进入可持续积累阶段。**
2. **确认前稳定性** 现在可以被量化比较，不用只靠肉眼看榜位变化。
3. **“先确认、后进 Top5”** 这种路径真实存在，因此后续不能把“进 Top5”误设为正式确认的必要条件。

### 7.2 当前最有研究价值的点
后续优先观察：
- `FastRank_FastConfirm` 是否更容易继续冲击 Top3 / Top1
- `SlowRank_FastConfirm` 是否代表“中继加速型强势路径”
- `Unclassified` 中哪些属于“确认前高波动但后续继续走强”的特殊模板

### 7.3 现阶段仍不该做的事
- 不应该直接拿当前 V2 分类当成确定性交易规则
- 不应该根据 1~2 天样本就给 `lag/std/range` 下硬阈值
- 不应该把 `overlap_candidate=true` 解读成“必然已在前五”

---

## 8. 下一步建议

### 步骤 1：继续积累 2~4 周样本
重点不是再堆字段，而是让：
- `path_class_v2`
- `pre_confirmation_rank_range`
- `pre_confirmation_rank_std`
- `episode_confirmation_progress_ratio`

形成更厚的历史样本。

### 步骤 2：做按路径分类的历史回看
后续可以新增一个研究脚本，专门统计：
- 各 `path_class_v2` 类型的后续表现
- 确认后 1h / 4h / 24h 的收益与回撤
- 哪些分类更接近真正的“稳定黑马路径”

### 步骤 3：把 V2 研究结果接到前端展示
下一轮值得推进的是：
- 在前端卡片或详情里展示 `path_class_v2`
- 展示 `pre_confirmation_rank_range / std`
- 让用户在 UI 上直接看到“确认前稳不稳”

---

## 9. 最终判断
当前这一步的意义，不是“已经找到最终黑马规则”，而是：

> TOP15 路径研究已经从“概念分析”推进到了“字段可积累、样本可比较、后续可回测”的阶段。

这一步很关键，因为后面真正有价值的，不是多讲几个故事，而是让路径研究进入能长期积累证据的状态。
