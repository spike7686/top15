# TOP15 Short Fade Research V1

## 1. Dataset
- Valid rows: 231503
- Unique symbols: 264
- Unique snapshots: 15549
- Time range: 2026-03-14T07:14:22.244118+00:00 -> 2026-04-10T07:00:01.273086+00:00
- History source: `data/top15_tracker/history.jsonl`
- Filter rule: `24h_volume_usd_gt_15m_excluding_stablecoins_binance_spot_only`

## 2. Core question
- Does it make sense to short immediately when a token enters overlap_candidate?
- Or is it better to wait until overlap stays true but the 1h momentum rolls over?

## 3. Signal Comparison
### 3.15 `first_overlap`
- Definition: First row where overlap_candidate flips from false to true.
- Sample count: 1948
- 4h short stats: win_rate=0.5786 | mean=-0.1381% | median=0.5382% | pf=0.9395
- 12h short stats: win_rate=0.5935 | mean=0.3103% | median=0.8722% | pf=1.0981
- 24h short stats: win_rate=0.5614 | mean=-0.4277% | median=0.5798% | pf=0.8933

### 3.22 `weak_core`
- Definition: Inside an overlap episode, rank_change_30m <= 0 and overlap_score_delta_30m <= 0.
- Sample count: 922
- 4h short stats: win_rate=0.5859 | mean=-0.0297% | median=0.4321% | pf=0.9811
- 12h short stats: win_rate=0.563 | mean=-0.2805% | median=0.4772% | pf=0.8881
- 24h short stats: win_rate=0.5413 | mean=-0.8429% | median=0.2448% | pf=0.7414

### 3.29 `weak_all_scores`
- Definition: Inside an overlap episode, rank_change_30m <= 0 and all 30m score deltas <= 0.
- Sample count: 905
- 4h short stats: win_rate=0.588 | mean=-0.0643% | median=0.4306% | pf=0.959
- 12h short stats: win_rate=0.5637 | mean=-0.3253% | median=0.4656% | pf=0.8696
- 24h short stats: win_rate=0.5393 | mean=-0.8924% | median=0.2392% | pf=0.7275

### 3.36 `weak_1h_turn`
- Definition: Inside an overlap episode, trend_1h turns to Range/Down/StrongDown and overlap_score_delta_30m <= 0.
- Sample count: 32
- 4h short stats: win_rate=0.8125 | mean=0.6935% | median=0.5344% | pf=5.7768
- 12h short stats: win_rate=0.6562 | mean=0.364% | median=0.2261% | pf=1.6737
- 24h short stats: win_rate=0.6875 | mean=1.1839% | median=0.2978% | pf=3.6345

### 3.43 `overheat_fade`
- Definition: Inside an overlap episode, 24h change >= 15, turnover >= 0.5, rank_change_30m <= 0, overlap_score_delta_30m <= 0.
- Sample count: 284
- 4h short stats: win_rate=0.5493 | mean=-0.4215% | median=0.5926% | pf=0.8635
- 12h short stats: win_rate=0.6338 | mean=-0.2423% | median=1.4276% | pf=0.9487
- 24h short stats: win_rate=0.6514 | mean=-0.0184% | median=1.4938% | pf=0.9963

### 3.50 `extreme_overheat_fade`
- Definition: Inside an overlap episode, 24h change >= 20, turnover >= 0.8, darkhorse_score_delta_30m <= 0, overlap_score_delta_30m <= 0.
- Sample count: 210
- 4h short stats: win_rate=0.519 | mean=-1.04% | median=0.3616% | pf=0.7227
- 12h short stats: win_rate=0.6524 | mean=-1.2501% | median=1.8668% | pf=0.8001
- 24h short stats: win_rate=0.6429 | mean=-1.2018% | median=2.4544% | pf=0.8274

### 3.57 `no_breakout_fade`
- Definition: Inside an overlap episode, breakout_1h == NoBreakout, rank_change_30m <= 0, overlap_score_delta_30m <= 0.
- Sample count: 832
- 4h short stats: win_rate=0.5669 | mean=-0.0847% | median=0.3437% | pf=0.9441
- 12h short stats: win_rate=0.5518 | mean=-0.4025% | median=0.3795% | pf=0.8391
- 24h short stats: win_rate=0.5301 | mean=-0.992% | median=0.1971% | pf=0.6915

## 4. Focus signal: weak_1h_turn
- Base idea: keep overlap_candidate=true, but wait for trend_1h to shift to Range/Down/StrongDown while overlap_score_delta_30m <= 0.
- This is not a fresh breakout short. It is a post-confirmation fade short.

## 5. Filter Study On weak_1h_turn
### `all`
- Sample count: 32
- 4h: win_rate=0.8125 | mean=0.6935% | median=0.5344% | pf=5.7768
- 12h: win_rate=0.6562 | mean=0.364% | median=0.2261% | pf=1.6737
- 24h: win_rate=0.6875 | mean=1.1839% | median=0.2978% | pf=3.6345

### `no_breakout_1h`
- Sample count: 29
- 4h: win_rate=0.8276 | mean=0.7343% | median=0.5969% | pf=5.5987
- 12h: win_rate=0.6207 | mean=0.3527% | median=0.2065% | pf=1.5916
- 24h: win_rate=0.6552 | mean=1.2611% | median=0.283% | pf=3.5432

### `pos_ge_8`
- Sample count: 26
- 4h: win_rate=0.7692 | mean=0.5142% | median=0.3012% | pf=3.8778
- 12h: win_rate=0.5769 | mean=0.0083% | median=0.168% | pf=1.0124
- 24h: win_rate=0.6154 | mean=0.7782% | median=0.2048% | pf=2.4071

### `turnover_ge_0_4`
- Sample count: 26
- 4h: win_rate=0.8462 | mean=0.6526% | median=0.6084% | pf=4.7759
- 12h: win_rate=0.6154 | mean=0.3519% | median=0.2527% | pf=1.561
- 24h: win_rate=0.6538 | mean=1.3327% | median=0.4872% | pf=3.4512

### `chg_3_8`
- Sample count: 18
- 4h: win_rate=0.9444 | mean=0.9718% | median=1.1658% | pf=5.7044
- 12h: win_rate=0.7778 | mean=0.7319% | median=0.4945% | pf=2.1245
- 24h: win_rate=0.8889 | mean=2.2658% | median=1.1072% | pf=6.5375

### `activity_low`
- Sample count: 23
- 4h: win_rate=0.8261 | mean=0.6899% | median=1.0182% | pf=4.5312
- 12h: win_rate=0.6087 | mean=0.3436% | median=0.2456% | pf=1.4858
- 24h: win_rate=0.6522 | mean=1.4556% | median=0.4318% | pf=3.3699

### `no_breakout_1h+chg_3_8`
- Sample count: 17
- 4h: win_rate=0.9412 | mean=1.0116% | median=1.2229% | pf=5.6253
- 12h: win_rate=0.7647 | mean=0.7316% | median=0.4318% | pf=2.0617
- 24h: win_rate=0.8824 | mean=2.3671% | median=1.1274% | pf=6.4638

### `no_breakout_1h+pos_ge_8`
- Sample count: 23
- 4h: win_rate=0.7826 | mean=0.5422% | median=0.3082% | pf=3.6933
- 12h: win_rate=0.5217 | mean=-0.0523% | median=0.022% | pf=0.9304
- 24h: win_rate=0.5652 | mean=0.8227% | median=0.2032% | pf=2.3158

### `no_breakout_1h+turnover_ge_0_4`
- Sample count: 24
- 4h: win_rate=0.8333 | mean=0.6689% | median=0.8075% | pf=4.5725
- 12h: win_rate=0.5833 | mean=0.3277% | median=0.2261% | pf=1.4822
- 24h: win_rate=0.625 | mean=1.3946% | median=0.3574% | pf=3.3678

### `pos_ge_8+chg_3_8`
- Sample count: 12
- 4h: win_rate=0.9167 | mean=0.7224% | median=1.0634% | pf=3.3315
- 12h: win_rate=0.6667 | mean=0.145% | median=0.2643% | pf=1.1486
- 24h: win_rate=0.8333 | mean=1.9278% | median=0.4872% | pf=4.141

### `no_breakout_1h+pos_ge_8+chg_3_8`
- Sample count: 11
- 4h: win_rate=0.9091 | mean=0.7613% | median=1.1086% | pf=3.2524
- 12h: win_rate=0.6364 | mean=0.0913% | median=0.2456% | pf=1.0858
- 24h: win_rate=0.8182 | mean=2.0537% | median=0.4318% | pf=4.0673

### `no_breakout_1h+pos_ge_8+turnover_ge_0_4+chg_3_8`
- Sample count: 10
- 4h: win_rate=0.9 | mean=0.579% | median=1.0634% | pf=2.5572
- 12h: win_rate=0.7 | mean=0.1986% | median=0.2643% | pf=1.185
- 24h: win_rate=0.9 | mean=2.2835% | median=2.5654% | pf=4.207

## 6. Execution Study
### `baseline_tp1_5_sl1_h12`
- Signal: `weak_1h_turn`
- Filters: `none`
- TP / SL / max_h: 1.5% / 1.0% / 12h
- Stats: n=32 | win_rate=0.75 | mean_pnl=0.6906% | median_pnl=1.5% | pf=4.1395
- Exit mix: tp_rate=0.5625 | sl_rate=0.2188 | timeout_rate=0.2188 | median_hours=3.5834

### `baseline_tp2_sl1_h12`
- Signal: `weak_1h_turn`
- Filters: `none`
- TP / SL / max_h: 2.0% / 1.0% / 12h
- Stats: n=32 | win_rate=0.6562 | mean_pnl=0.6172% | median_pnl=0.2791% | pf=3.2348
- Exit mix: tp_rate=0.4062 | sl_rate=0.25 | timeout_rate=0.3438 | median_hours=5.2613

### `selective_tp1_5_sl1_h12`
- Signal: `weak_1h_turn`
- Filters: `no_breakout_1h+chg_3_8`
- TP / SL / max_h: 1.5% / 1.0% / 12h
- Stats: n=17 | win_rate=0.8235 | mean_pnl=1.0588% | median_pnl=1.5% | pf=7.0
- Exit mix: tp_rate=0.8235 | sl_rate=0.1765 | timeout_rate=0.0 | median_hours=1.9921

### `selective_tp2_sl1_h12`
- Signal: `weak_1h_turn`
- Filters: `no_breakout_1h+chg_3_8`
- TP / SL / max_h: 2.0% / 1.0% / 12h
- Stats: n=17 | win_rate=0.8235 | mean_pnl=1.2619% | median_pnl=2.0% | pf=8.1507
- Exit mix: tp_rate=0.7059 | sl_rate=0.1765 | timeout_rate=0.1176 | median_hours=3.6667

## 7. Current Strategy Candidate
- Focus signal: `weak_1h_turn`
- Entry filters: `no_breakout_1h+chg_3_8`
- Human-readable rule: overlap_candidate stays true, trend_1h rolls to Range/Down/StrongDown, overlap_score_delta_30m <= 0, breakout_1h is NoBreakout, and 24h change is between 3% and 8%.
- Conservative execution: TP 1.5% / SL 1.0% / max 12h
  Stats: win_rate=0.8235 | mean_pnl=1.0588% | pf=7.0
- Aggressive execution: TP 2.0% / SL 1.0% / max 12h
  Stats: win_rate=0.8235 | mean_pnl=1.2619% | pf=8.1507

## 8. Caveats
- The strongest signal is statistically promising but small-sample.
- The execution study is snapshot-based, not intrabar matching or order-book replay.
- No funding, borrow cost, perp availability, or slippage filter is included yet.
- This is a research candidate, not a production strategy.

## 9. Next steps
- Re-run the same study after another 2-4 weeks of data accumulation.
- Add 5m / 15m execution-level candles for more realistic entry and stop handling.
- Add Binance perp tradability, funding, and liquidity filters.
- Split by time to build out-of-sample validation.
