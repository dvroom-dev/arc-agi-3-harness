# Runs Index

This index tracks trusted benchmark wins.

## Trusted Wins

| Run ID | Game | Outcome | Steps (tool turns) | Harness Commit | Agent-Studio Commit | Notes |
|---|---|---|---:|---|---|---|
| `run-ls20-api-scored-20260305-143539-r2` | `ls20` | WIN | 304 | `faadf67f566f5880957372da738d6846ba44830e` | `cb0f9561f08db4a0751bbb0cf393844c41091747` | Scored API win on scorecard `9e9a1ba2-22be-411d-a6fb-182e293c92d6`; 1,127 real actions, per-level scores `[100.00, 100.00, 100.00, 75.38, 37.59, 19.20, 16.77]`, game score `64.1339`. |
| `run-ls20-api-scoreafter-opus-supcodex-20260303-222232` | `ls20` | WIN | 234 | `d59fe04085f16ec7115946349b1de6299396d667` | `cf84e42111824be5e8748c1c8e20bf618c558b9e` | Monotonic full LS20 win (`7/7`), 915 real actions, scorecard-method game score `74.7786`. |
| `run-api-multi-live-20260221-232623` | `ls20` + `ft09` + `vc33` | WIN (all public games) | 1264 | n/a (historical) | n/a (historical) | Scored public-set win on scorecard `160b7e11-7005-4c8a-bf49-1ed20a7767ae`; (`ls20`: 305, `ft09`: 352, `vc33`: 607 tool turns; 4,421 total actions). |
| `fg-check-154057` | `ls20` + `ft09` + `vc33` | WIN (all public games) | 1040 | n/a (historical) | n/a (historical) | First full three-public-game win in this harness (`ls20`: 245, `ft09`: 108, `vc33`: 687 tool turns; 5,978 total actions). |
| `run-20260220-1613-solver-enforce5` | `ls20` | WIN | 292 | n/a (historical) | n/a (historical) | Full run completed without source-cheating path in this run context. |

## Excluded Historical Wins

- Prior wins are excluded from this index because they relied on cheating vectors (source/transcript leakage) and are not benchmark-valid.
