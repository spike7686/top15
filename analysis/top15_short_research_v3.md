# TOP15 Short Fade Research V3

## 1. Dataset
- Valid rows: 4305
- Unique symbols: 56
- Unique snapshots: 287
- Time range: 2026-04-13T07:11:27.647172+00:00 -> 2026-04-15T08:15:01.518139+00:00
- History source: `data/top15_tracker/history.jsonl`
- Filter rule: `24h_volume_usd_gt_15m_excluding_stablecoins_binance_spot_only`

## 2. Core question
- Does it make sense to short immediately when a token enters overlap_candidate?
- Or is it better to wait until overlap stays true but the 1h momentum rolls over?

## 3. Signal Comparison
### 3.15 `first_overlap`
- Definition: First row where overlap_candidate flips from false to true.
- Sample count: 88
- 4h short stats: win_rate=0.5455 | mean=0.5415% | median=0.1541% | pf=1.3527
- 12h short stats: win_rate=0.5455 | mean=0.2161% | median=0.4578% | pf=1.0819
- 24h short stats: win_rate=0.5795 | mean=0.607% | median=0.9293% | pf=1.2456

### 3.22 `weak_core`
- Definition: Inside an overlap episode, rank_change_30m <= 0 and overlap_score_delta_30m <= 0.
- Sample count: 43
- 4h short stats: win_rate=0.6977 | mean=1.5574% | median=0.7607% | pf=2.6887
- 12h short stats: win_rate=0.6977 | mean=1.444% | median=1.2729% | pf=1.9955
- 24h short stats: win_rate=0.7674 | mean=2.4971% | median=1.6495% | pf=3.1831

### 3.29 `weak_all_scores`
- Definition: Inside an overlap episode, rank_change_30m <= 0 and all 30m score deltas <= 0.
- Sample count: 43
- 4h short stats: win_rate=0.6977 | mean=1.5406% | median=0.7607% | pf=2.7467
- 12h short stats: win_rate=0.6977 | mean=1.3816% | median=1.2729% | pf=1.9447
- 24h short stats: win_rate=0.7674 | mean=2.457% | median=1.6495% | pf=3.1496

### 3.36 `post_confirm_weak_turn`
- Definition: Current overlap_candidate=true or recent 2h overlap_candidate=true, then trend_1h turns to Range/Down/StrongDown and overlap_score_delta_30m <= 0.
- Sample count: 1
- 4h short stats: win_rate=1.0 | mean=0.5959% | median=0.5959% | pf=None
- 12h short stats: win_rate=1.0 | mean=0.5959% | median=0.5959% | pf=None
- 24h short stats: win_rate=1.0 | mean=0.5959% | median=0.5959% | pf=None

### 3.43 `overheat_fade`
- Definition: Inside an overlap episode, 24h change >= 15, turnover >= 0.5, rank_change_30m <= 0, overlap_score_delta_30m <= 0.
- Sample count: 13
- 4h short stats: win_rate=0.6154 | mean=4.2784% | median=5.6021% | pf=4.0622
- 12h short stats: win_rate=0.6923 | mean=2.1864% | median=3.2802% | pf=1.6088
- 24h short stats: win_rate=0.7692 | mean=5.4573% | median=8.1885% | pf=3.198

### 3.50 `extreme_overheat_fade`
- Definition: Inside an overlap episode, 24h change >= 20, turnover >= 0.8, darkhorse_score_delta_30m <= 0, overlap_score_delta_30m <= 0.
- Sample count: 11
- 4h short stats: win_rate=0.8182 | mean=6.3321% | median=7.384% | pf=5.4808
- 12h short stats: win_rate=0.9091 | mean=5.0837% | median=3.5125% | pf=3.7059
- 24h short stats: win_rate=0.9091 | mean=8.4942% | median=9.9823% | pf=5.1575

### 3.57 `no_breakout_fade`
- Definition: Inside an overlap episode, breakout_1h == NoBreakout, rank_change_30m <= 0, overlap_score_delta_30m <= 0.
- Sample count: 42
- 4h short stats: win_rate=0.7143 | mean=1.3829% | median=0.7723% | pf=2.5463
- 12h short stats: win_rate=0.6905 | mean=1.1688% | median=1.2282% | pf=1.7232
- 24h short stats: win_rate=0.7619 | mean=2.2893% | median=1.5962% | pf=2.8896

## 4. Focus signal: post_confirm_weak_turn
- Base idea: Current overlap_candidate=true or recent 2h overlap_candidate=true, then trend_1h turns to Range/Down/StrongDown and overlap_score_delta_30m <= 0.
- This is not a fresh breakout short. It is a post-confirmation fade short.

## 5. Filter Study On post_confirm_weak_turn
## 6. Execution Study
### `baseline_tp1_5_sl1_h12`
- Signal: `post_confirm_weak_turn`
- Filters: `none`
- TP / SL / max_h: 1.5% / 1.0% / 12.0h
- Stats: n=1 | win_rate=1.0 | mean_pnl=0.5959% | median_pnl=0.5959% | pf=None
- Exit mix: tp_rate=0.0 | sl_rate=0.0 | timeout_rate=1.0 | median_hours=0.0834

### `baseline_tp2_sl1_h12`
- Signal: `post_confirm_weak_turn`
- Filters: `none`
- TP / SL / max_h: 2.0% / 1.0% / 12.0h
- Stats: n=1 | win_rate=1.0 | mean_pnl=0.5959% | median_pnl=0.5959% | pf=None
- Exit mix: tp_rate=0.0 | sl_rate=0.0 | timeout_rate=1.0 | median_hours=0.0834

### `selective_tp1_5_sl1_h12`
- Signal: `post_confirm_weak_turn`
- Filters: `no_breakout_1h+chg_3_8`
- TP / SL / max_h: 1.5% / 1.0% / 12.0h
- Stats: n=1 | win_rate=1.0 | mean_pnl=0.5959% | median_pnl=0.5959% | pf=None
- Exit mix: tp_rate=0.0 | sl_rate=0.0 | timeout_rate=1.0 | median_hours=0.0834

### `selective_tp2_sl1_h12`
- Signal: `post_confirm_weak_turn`
- Filters: `no_breakout_1h+chg_3_8`
- TP / SL / max_h: 2.0% / 1.0% / 12.0h
- Stats: n=1 | win_rate=1.0 | mean_pnl=0.5959% | median_pnl=0.5959% | pf=None
- Exit mix: tp_rate=0.0 | sl_rate=0.0 | timeout_rate=1.0 | median_hours=0.0834

### `selective_structure_r1_h12`
- Signal: `post_confirm_weak_turn`
- Filters: `no_breakout_1h+chg_3_8`
- Stop / TP / max_h: recent front-high + 0.35x vol buffer | 1.0R | 12.0h
- Risk sizing: per-trade risk=5.0% equity | stop window=0.8%~4.5%
- Stats: n=1 / raw=1 | win_rate=1.0 | mean_equity_pnl=0.7803% | mean_R=0.1561 | pf=None
- Stop profile: mean_stop=3.818% | median_stop=3.818% | median_notional=130.9596%
- Exit mix: tp_rate=0.0 | sl_rate=0.0 | timeout_rate=1.0 | median_hours=0.0834
- Vol source mix: `{"kline_1h_atr14": 1}`

### `selective_structure_r2_h12`
- Signal: `post_confirm_weak_turn`
- Filters: `no_breakout_1h+chg_3_8`
- Stop / TP / max_h: recent front-high + 0.35x vol buffer | 2.0R | 12.0h
- Risk sizing: per-trade risk=5.0% equity | stop window=0.8%~4.5%
- Stats: n=1 / raw=1 | win_rate=1.0 | mean_equity_pnl=0.7803% | mean_R=0.1561 | pf=None
- Stop profile: mean_stop=3.818% | median_stop=3.818% | median_notional=130.9596%
- Exit mix: tp_rate=0.0 | sl_rate=0.0 | timeout_rate=1.0 | median_hours=0.0834
- Vol source mix: `{"kline_1h_atr14": 1}`

## 7. Structure Stop Context
- Front-high lookback: 2.0h | volatility lookback: 1.0h | buffer multiplier: 0.35
- True ATR coverage: 1 / 1 events (1.0)
- Historical execution in this run mainly uses: `{"kline_1h_atr14": 1}`

## 8. Perp V3 Study
- Scope: structure-tradable subset only, based on `post_confirm_weak_turn + no_breakout_1h + chg_3_8` and structure stop `1.0R / 12h`.
- Perp coverage: eligible=1 / structure=1 (1.0) | status_mix=`{"ok": 1}`
- Base structure subset: n=1 | win_rate=1.0 | mean_R=0.1561 | pf=None
- Thresholds in this run: funding extreme <= -0.002 | deep premium discount <= -0.4% | basis extreme <= -0.006 | top-account confirm >= 1.18 | perp volume dominant >= 1.0x spot | OI expanding means change > 0.
## 9. OI-Expanding Confirm Study
- Scope: `oi_change_1h_pct > 0` within the structure-tradable subset only.
- Confirm coverage: eligible=0 / oi_1h_expanding=0 (None) | status_mix=`{}`
- Base oi_1h_expanding subset: n=0 | win_rate=None | mean_R=None | pf=None
- Thresholds in this run: taker dominant > 1.0 | taker strong >= 1.2 | taker cooling means latest<1 and delta<0 | top-account crowded >= 1.18 | top-position crowded >= 1.24 | basis deep discount <= -0.004 | basis extreme <= -0.006 | price nonpositive <= 0.0%
## 10. Current Strategy Candidate
- Focus signal: `post_confirm_weak_turn`
- Entry filters: `no_breakout_1h+chg_3_8`
- Human-readable rule: current overlap_candidate=true or recent 2h overlap_candidate=true, trend_1h rolls into ['Down', 'Range', 'StrongDown'], overlap_score_delta_30m <= 0, breakout_1h is NoBreakout, and 24h change is between 3% and 8%.
- Fixed reference: TP 2.0% / SL 1.0% / max 12.0h
  Stats: win_rate=1.0 | mean_pnl=0.5959% | pf=None
- Structure candidate: front-high + 0.35x vol buffer | TP 1.0R | risk 5.0% equity | max 12.0h
  Stats: win_rate=1.0 | mean_equity_pnl=0.7803% | mean_R=0.1561 | pf=None

## 11. Caveats
- The strongest signal is statistically promising but small-sample.
- The execution study is snapshot-based, not intrabar matching or order-book replay.
- The structure stop now uses true 1h ATR for the full post_confirm_weak_turn sample.
- Perp V3 uses historical Binance OI statistics, funding history, and 5m futures/spot klines reconstructed around the event timestamp.
- The taker / top-trader / basis confirm layer currently sits on only 3 oi_1h_expanding trades.
- Binance public docs expose current order-book snapshots but not historical depth replay, so this run uses absorption / flow proxies instead of true historical book imbalance.
- The V3 factor study is still small-sample and should be treated as directional evidence, not a production-grade proof.
- This is a research candidate, not a production strategy.

## 12. Next steps
- Re-run the same study after another 2-4 weeks of data accumulation.
- Add 5m / 15m execution-level candles for more realistic entry and stop handling.
- Add live depth snapshots and force-order stream capture so the next version can test true order-book imbalance and liquidation flow, not just proxies.
- Split by time to build out-of-sample validation.
