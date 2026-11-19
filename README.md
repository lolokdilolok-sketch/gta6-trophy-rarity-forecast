# GTA VI Trophy Rarity Forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/lolokdilolok-sketch/gta6-trophy-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/lolokdilolok-sketch/gta6-trophy-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts each of the 55 GTA VI PS5 trophies' Exophase earn rate at
26 Nov 2026 00:00 UTC, for the make.fun bounty
`gta6-trophy-rarity-forecast-01`.

## Method

A trophy's rate is a ratio, `earned / tracked`, and Exophase moves the
two halves on different clocks: tracked players arrive in bursts whenever
the page refreshes (launch night: 638 tracked, then 3,868 at the first
refresh, while almost nobody had earned anything new), so the rate falls
even while more players earn the trophy. Fitting the rate directly reads
each refresh as a collapse of the trend. This program fits earned and
tracked separately, then divides.

- **Tracked:** log(tracked) grows roughly linearly in HOURS, not as a
  power law in log-hours: the count is piecewise constant and jumps at
  refreshes. The per-hour log growth is estimated from the refresh
  events in the last day and compounded over the horizon (capped at
  6 log units). A power-law fit in log-hours was round 1's fatal
  error: it predicted ~5x tracked growth over 4.5 days where the page
  really multiplies 50x, so the rate sat ~3 logit too high. Round 3
  changed the estimator to the RATIO OF MEANS over the refresh events
  in the last day (total log jump / total inter-refresh time), which
  removes the endpoint estimator's window-edge bias (G-error MAE 0.55
  vs 0.64 log) and cut the worst synthetic final from 0.79 to 0.50.
  A decaying tracked model was measured and rejected: even a 240-hour
  decay half-life costs +0.16 mean loss where growth is steady.
- **kappa (dilution):** how much of a tracked jump dilutes the rate.
  At a refresh the rate drops by prog − kappa·log(N_new/N_old); the
  trophies that drop the most have the least progression, so the 10th
  percentile of the per-trophy log drops over the jump, divided by the
  log jump, estimates kappa (median over events; 0.7 when the history
  shows no refresh). On synthetic cases with known kappa it recovers
  0.49/0.69/1.00 for true 0.5/0.7/1.0.
- **Earned:** per trophy, log(earned) against log(1 + hours) over the
  last day of states, anchored at the last observed count — but fitted
  on the decoupled series log(earned) − (1−kappa)·log(tracked), so the
  part of earned growth that merely follows the tracked count is not
  mistaken for progression. The coupling is added back explicitly at
  the target: earned grows with tracked^(1−kappa). A slope is only
  trusted when the last rate clears the rounding noise (above 0.05%)
  and at most half the window sits at 0.00%; otherwise the slope
  shrinks toward the pooled slope of the trophies whose counts are big
  enough to measure. A 0.00% read counts as a half-earner, not as
  missing.
- **Two-branch mixture:** a refresh is a discrete event, not a smooth
  drift. Branch A (no refresh before the target) keeps the page frozen
  at the last rate; branch B (a refresh lands) uses the fitted
  earned / fitted tracked, with tracked floored by the catch-up jump a
  stale page is due. The refresh probability comes from the refresh
  interval the history itself shows (6-hour prior when it shows none).
  Over a 4.5-day horizon a refresh is certain, so the fits rule; over
  90 minutes on a stale page the quantiles honestly straddle both
  branches.
- **Spread:** dominated by the dilution uncertainty, not the fit
  residuals. The tracked growth over the horizon is G =
  log(N_target/N_last); its logit cost is kappa·G, uncertain in kappa
  (±0.20) and in the number and size of the jumps still to come
  (sqrt(expected refreshes) × 0.12 in log units). Round 3 scales the
  branch-B sigma by 0.9 — the minimax balance over both synthetic
  suites (scale 1.0: lowest worst case 0.575 but mean 0.387; scale
  0.7: lowest mean 0.351 but worst case 0.602 breaches the gate; 0.9
  passes both: mean 0.372, worst 0.584). The 90% band at the
  final horizon is ~3–4 logit wide (sigma_b median 1.27–1.54 before
  scaling), and it genuinely widens with horizon (edge test: sigma_b
  0.45 at 90 min → 0.77 at 6,510 min). The 100% trophy is forced to
  99.99 with a wide spread.

Standard library only. Deterministic: no randomness, no wall clock, so
two runs write identical bytes.

## Usage

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` in the input directory (or `/input/`), writes one
`<id>.out` per case to the output directory (or `/output/`).

## Validation (measured 19 Nov 2026, round 3)

- Independent synthetic finals (9 cases: 3 seeds × kappa 0.5/0.7/1.0,
  saturating trophy curves, refreshes every 5–9h, tracked ×46–67 over
  the horizon): mine mean loss **0.372** (per case 0.288–0.584) vs
  trend baseline 1.576 vs flat 2.052 — beats trend in all 9 cases.
  Coverage90 0.98. Worst case is now s3k7 (0.584); s3k10, the round-2
  worst case, fell from 0.793 to 0.497. Round 2 was 0.401 / 0.793.
- Synthetic final, five worlds of round 1 (cohort dilution, fast/slow
  tracked growth, fast progression, and a no-dilution world): mine
  0.168–0.196 vs trend 0.221–0.240 vs flat 0.459–0.527 — still beats
  trend in all 5 (round 2 was 0.180–0.206 there; the ratio estimator
  plus the 0.9 spread scale recovered most of the smooth-world loss).
- Practice grid (answer = first refresh, tracked 3,868, earned growth
  g): mine 0.18–0.56 (p00) and 0.20–0.46 (p01) vs flat starter
  0.61–1.69 across g = 1.0–3.0 (at g ≈ 1.2: ~0.45 vs 1.51). The
  earned coupling in the no-refresh case was tested (removing it
  helps the grid at low g but hurts at high g, with no effect on the
  synthetic finals) and left in place; the grid is reported, not
  chased.
- Backtests (fit to time t, predict the next read and the page 6h
  later): wins the +6h test at t = 24/36/48h (0.21/0.06/0.06 vs
  trend 0.35/0.08/0.07). The t = 12h +6h test stays the weak spot
  (0.73 vs flat 0.62): with only two refreshes seen, kappa and g_N
  are estimated from almost nothing; neither competition horizon is
  at t = 12h.
- Edge cases (edge.py, exit 0): 0% trophy, null rates, trophy missing
  from some reads, tracked jump (dilution), secret trophies, 6,510-min
  horizon. The spread now genuinely widens with horizon (sigma_b
  median 0.45 at 90 min → 0.77 at 6,510 min) — round 1's edge test
  FAILED this assertion twice (final spread narrower than practice).
- Two runs byte-identical; ~0.3 s per case; outputs ~2.8 KB each
  (limit 65,536); all 55 ids, quantiles non-decreasing, 0–100.

## Caveat

The synthetic worlds are one family's guess at the real progression
and refresh pattern, calibrated to the launch-night rates. The real
final has more uncertainty than any of them (the house AI model is
also unknown), so the spread is kept deliberately wider than the
simulator alone would suggest. Two specific risks: (1) if the real
tracked growth DECAYS over the horizon (launch wave passing), the
linear-time extrapolation overshoots and the median sits too low —
the dilution spread (±~1 logit) is meant to cover that; (2) kappa is
estimated from the refresh jumps, and if the real refreshes are rarer
or the progression between them is larger, kappa is underestimated
and the median sits too high — again covered by the spread, not by
the median.
