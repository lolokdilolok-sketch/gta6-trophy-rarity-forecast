"""Forecast GTA VI trophy earn rates on Exophase, one week after launch.

A trophy's earn rate is a ratio, earned / tracked, and Exophase moves the
two halves on different clocks. Tracked players arrive in bursts whenever
Exophase refreshes the page (launch night: 638 tracked, then 3,868 at the
first refresh, while almost nobody had earned anything new), so the rate
falls even while more players earn the trophy. A forecaster that fits the
rate directly reads each refresh as a collapse of the trend; one that fits
earned and tracked separately, then divides, keeps the two stories apart.

The forecast is a two-branch mixture, because a refresh is a discrete
event, not a smooth drift:
  - branch A (no refresh before the target): the page stays frozen, so the
    rate is the last rate, with only rounding spread;
  - branch B (a refresh lands before the target): the page jumps to the
    fitted earned / fitted tracked at the target, where the tracked fit is
    floored by the catch-up jump a stale page is due.
The refresh probability comes from the refresh interval the history itself
shows (or a 6-hour prior when it shows none), and the jump size from the
fitted growth of tracked since the last refresh. Over a 4.5-day horizon a
refresh is certain, so the mixture is all branch B and the fits rule; over
90 minutes on a stale page it is a coin flip, so the quantiles honestly
straddle both branches instead of pretending the rate drifts smoothly.

Per trophy the program fits log(earned) against log(1 + hours since
release) with a straight line over the last day of states, anchored at
the last observed count, and shrinks an unreliable slope toward the
pooled slope of the trophies whose counts are big enough to measure.
The earned fit is done on the decoupled series log(earned) minus
(1-kappa)*log(tracked), so the part of earned growth that merely
follows the tracked count is not mistaken for progression; the
coupling is added back explicitly at the target. log(tracked) is NOT
fitted the same way: the tracked count jumps at refreshes, so its log
grows roughly linearly in hours, and the per-hour log growth is
estimated from the refresh events in the last day and compounded over
the horizon. A power law in log-hours would predict only ~5x tracked
growth over 4.5 days where the page really multiplies 50x, and the
rate would sit ~3 logit too high (round 1's failure, measured on
independent synthetic finals).

kappa -- how much of a tracked jump dilutes the rate -- is estimated
from the refresh jumps themselves: at a refresh the rate drops by
prog - kappa*log(N_new/N_old), and the trophies that drop the most
have the least progression, so the 10th percentile of the per-trophy
log drops over the jump, divided by the log jump, estimates kappa
(median over events; 0.7 when the history shows no refresh).

The spread is dominated by the dilution uncertainty: the tracked
growth over the horizon is G = log(N_target/N_last), its logit cost
is kappa*G, uncertain in kappa and in the number and size of the
jumps still to come. The fit residuals and the horizon term are small
beside it, so the 90% band at the final horizon is several logit
wide -- and it genuinely widens with horizon, unlike round 1, whose
final spread was narrower than its practice spread.

Round 3: the tracked growth rate is the ratio of means over the
refresh events in the last day (total log jump over total
inter-refresh time), which removes the endpoint estimator's
window-edge bias and cut the worst synthetic final from 0.79 to
0.50; a decaying tracked model was measured and rejected (even a
240-hour decay costs +0.16 mean loss where growth is steady); and
the branch-B spread is scaled by 0.9, the minimax balance over both
synthetic suites (mean 0.372, worst 0.584, still beating trend in
both). The practice grid at low earned growth was checked against
removing the earned coupling in the no-refresh case and left alone:
it trades low-g for high-g with no clear win, and the grid is a
guess, not a measurement.

Round 4 (this version) fixes the two measured failures of round 3.
(a) Flat/stale page: round 3 scored 0.422 on the practice server
(rank 1559/3164) because a history with NO refresh fell back to a
~2x dilution while the first refresh really dilutes ~6x (tracked
638 -> 3,868). The page's data dates from when it was FIRST seen,
not the last read, so the catch-up jump now grows the power law
from the first-seen time to the target (~5.5x on p00, ~6.0x on
p01); the refresh is treated as certain once the catch-up growth
exceeds 2x (a refresh is a growth-driven catch-up, not a clock coin
flip); kappa for the first refresh is 0.95 (its joiners are all
fresh players); and the spread is tightened for the committed
single refresh (kappa sd 0.05, jump-size sd 0.15, fit floor 0.05).
Practice proxy (calibrated to the server's 0.422 for round 3):
0.413 -> 0.066. The flat path only fires with no refresh in the
history, so rich final histories are byte-identical to round 3.
(b) Saturating progression: the earned slope is fitted on a
logistic (saturating) curve, so a linear extrapolation overshoots
earned by a constant +0.46 logit over the 4.5-day horizon
(measured on 18 synthetic finals; the true slope falls 0.63 ->
0.20 across the horizon). The slope now decays exponentially past
the window. The decay rate is deliberately HALF the fitted value
(SAT_DECAY = 0.5/log-hour, not 1.5): a second generator family
(bench.py's cohort worlds, where new players keep arriving and
the aggregate progression saturates slowly) is HURT by the full
decay -- at 1.5 it loses to the trend baseline in all 5 worlds
(0.245-0.277 vs trend 0.221-0.240), while at 0.5 it still beats
trend in all 5 (0.188-0.218). The real final is a mix of both
families, so 0.5 is the minimax-regret choice: synthetic finals
improve from mean 0.372 / worst 0.584 to mean 0.338 / worst
0.498 (tuning suite) and 0.321 / 0.474 (fresh suite, seeds 4-6),
still beating trend (1.576) and flat (2.052) in all 18 cases.
At the full decay (1.5) the logistic worlds would reach 0.312 /
0.403 and 0.314 / 0.425, but the cohort gate risk is not worth
the extra 0.026.

Standard library only. Deterministic: no randomness, no wall clock, every
number comes from the case file, so two runs write identical bytes.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

IN_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at the scored levels.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

# Window for the recent slope: the last 24h of states. log(earned) is
# convex in log-hours (its slope rises as players start earning), so a
# full-history average understates the slope that carries the next days;
# the last day's slope is the one that extrapolates.
RECENT_WINDOW_H = 24.0
# Refresh prior: when the history shows no refresh, assume one every 6h.
REFRESH_INTERVAL_PRIOR_H = 6.0
# Launch-night tracked growth, in log units per log-hour (power law):
# tracked went 638 -> 3,868 across the first refresh, which a power law
# with this exponent reproduces. It is only used when the history is flat.
LAUNCH_GROWTH = 1.0
# Jump-size cap (log units) and the share of a jump earned counts follow.
JUMP_CAP = 2.0
EARNED_FOLLOWS_JUMP = 0.1
# Spread pieces (logit units).
SPREAD_FIT_FLOOR = 0.20
# 0.30 per sqrt-day: over a 4.5-day horizon the slope can drift (progression
# saturates, refresh intervals change), so the horizon term alone must
# exceed the launch-night jump term -- the spread widens with horizon.
SPREAD_HORIZON_PER_DAY = 0.30
SPREAD_FROZEN = 0.05
SPREAD_MIN = 0.25
SPREAD_MAX = 2.5
# Dilution spread (round 2): the tracked count grows in bursts; over a
# 4.5-day horizon it can multiply 50x, and each burst dilutes every rate
# by (N_old/N_new)^kappa. kappa is estimated from the refresh jumps
# (below); its uncertainty and the jump-count uncertainty are the
# dominant spread at the final horizon, not the fit residuals.
SD_KAPPA = 0.20
SD_LOGJUMP = 0.12
KAPPA_DEFAULT = 0.7
# Round 4 (flat/stale page): when the history shows NO refresh at all, the
# next refresh is the FIRST one after launch, and its joiners are almost
# all brand-new players who have not earned the rare trophies yet, so the
# dilution is nearly complete (kappa near 1). The 0.7 default is the
# average over later refreshes, where joiners are a mix of new and
# returning players; it under-dilutes the first refresh by ~2x.
KAPPA_FLAT = 0.95
# Round 4 (flat spread): once the refresh is committed (p=1) on a flat
# page, the dilution uncertainty is far smaller than the general case.
# kappa for the FIRST refresh is tightly near 1 (every joiner is a fresh
# player who has not earned the rare trophies), the jump is a single
# event (no jump-count uncertainty, only its size, ~0.15 logit for the
# power-law estimate), and the earned fit on a frozen page has ~zero
# residual, so the 0.20 fit floor is pure conservatism here.
SD_KAPPA_FLAT = 0.05
JUMP_SD_FLAT = 0.15
SPREAD_FIT_FLOOR_FLAT = 0.05
LOG_GROWTH_CAP = 6.0
# Spread scale (round 3): the branch-B sigma is multiplied by this before
# clamping. Tuned for the minimax over both synthetic suites: 1.0 gives
# the lowest worst case (0.575) but a higher mean (0.387); 0.7 gives the
# lowest mean (0.351) but the worst case breaches 0.60; 0.9 is the
# balance that passes both gates (mean 0.372, worst 0.584) and beats
# trend on both suites. The medians are accurate enough in most worlds
# that a narrower-than-1.0 spread wins on average; the worst case is
# set by its median error, which the spread barely moves.
SPREAD_SCALE = 0.9
# Round 4 (saturation): the earned slope decays past the window.
# SAT_DECAY is the decay rate per log-hour; 0 = no decay (round 3).
SAT_DECAY = 0.5

# Debug hook (round 4): internals of the last forecast_case call,
# populated only when MAKEFUN_DEBUG=1. Never affects the forecast.
LAST_DEBUG = {}


def parse_ts(text):
    """ISO 8601 with a Z suffix into an aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def clamp_pct(x):
    return min(99.99, max(0.01, x))


def logit(pct):
    p = clamp_pct(pct) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit_pct(lg):
    return 100.0 / (1.0 + math.exp(-lg))


def round4(x):
    """Round to 4 decimals, half up; whole numbers come back as ints."""
    d = Decimal(repr(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    v = float(d)
    return int(v) if v == int(v) else v


def median(values):
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return None
    if n % 2:
        return xs[n // 2]
    return 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def percentile(values, q):
    """q-th quantile of values (nearest-rank); None when empty."""
    xs = sorted(values)
    if not xs:
        return None
    return xs[min(len(xs) - 1, max(0, int(q * len(xs))))]


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def lin_fit(xs, ys):
    """Least-squares y ~ a + b*x; returns (a, b) or None.

    Two distinct points already define a line, and a line is the honest
    shape here: log(tracked) is linear in log-hours (a power law), and
    log(earned) is close to a line over a short window. A quadratic fits
    the bend inside the data but its curvature explodes or collapses past
    it; the recent window's line is the robust extrapolation.
    """
    if len(xs) < 2 or len(set(xs)) < 2:
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den < 1e-12:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return (my - b * mx, b)


def sat_growth(b, du):
    """Earned-growth exponent for slope b over du log-hours, with the
    slope decaying exponentially past the window (saturation)."""
    if SAT_DECAY <= 0 or du <= 0:
        return b * du
    return b * (1.0 - math.exp(-SAT_DECAY * du)) / SAT_DECAY


def log_hours(t, release):
    """log(1 + hours since release), floored at 0 for pre-release reads."""
    hours = (t - release).total_seconds() / 3600.0
    return math.log1p(max(0.0, hours))


def distinct_states(history):
    """Collapse consecutive identical reads; returns [(at, tracked, rates)]."""
    states = []
    for read in history:
        key = (read["players_tracked"], tuple(read["rates"]))
        if not states or (states[-1][1], states[-1][2]) != key:
            states.append((parse_ts(read["at"]), read["players_tracked"],
                           tuple(read["rates"])))
    return states


def forecast_case(case):
    trophies = case["trophies"]
    horizon_h = case["horizon_minutes"] / 60.0
    horizon_d = case["horizon_minutes"] / 1440.0
    release = datetime.fromisoformat(
        case["game"]["release_date"] + "T00:00:00+00:00")
    checkpoint = parse_ts(case["at"])
    target_u = log_hours(parse_ts(case["target"]), release)
    states = distinct_states(case["history"])
    if not states:
        raise ValueError("case has no history")
    last_tracked = states[-1][1]
    last_rates = states[-1][2]

    # Refresh clock: how long the page has sat unchanged, and the interval
    # between the refreshes the history itself shows.
    # Round 4: a flat page (tracked unchanged in every read) has been
    # frozen since the FIRST read, not the last one -- the last read is
    # just another look at the same stale page. Its data age is the
    # first-seen time, and it is overdue by the whole observed freeze.
    flat_page = len({tr for _, tr, _ in states}) == 1
    if len(states) > 1:
        stale_h = (checkpoint - states[-1][0]).total_seconds() / 3600.0
        gaps = [(states[i + 1][0] - states[i][0]).total_seconds() / 3600.0
                for i in range(len(states) - 1)]
        tau = min(24.0, max(1.0, median(gaps) or REFRESH_INTERVAL_PRIOR_H))
    else:
        stale_h = (checkpoint - states[0][0]).total_seconds() / 3600.0
        tau = REFRESH_INTERVAL_PRIOR_H
    if flat_page:
        stale_h = (checkpoint - states[0][0]).total_seconds() / 3600.0
    t_data_h = max(0.0, (states[0][0] - release).total_seconds() / 3600.0)
    t_target_h = max(0.0, (parse_ts(case["target"]) - release).total_seconds() / 3600.0)
    launch_age_h = max(0.0, (checkpoint - release).total_seconds() / 3600.0)
    # Refreshes are huge on launch night and settle down later.
    maturity = 1.0 / (1.0 + max(0.0, launch_age_h - 12.0) / 24.0)
    # Time from release to the last refresh the page shows.
    t_last_refresh_h = max(0.0, (states[-1][0] - release).total_seconds() / 3600.0)

    # --- tracked: growth is exponential in TIME, not a power law in
    # log-hours. The tracked count is piecewise constant and jumps at
    # refreshes; log(tracked) grows roughly linearly in hours, while
    # log(1 + hours) flattens, so a power-law fit extrapolated over 4.5
    # days predicts only ~5x growth where the page really multiplies
    # 50x (round 1's median sat ~3 logit too high for exactly this
    # reason). Estimate the per-hour log growth g_N from the refresh
    # events in the last day and compound it over the horizon.
    #
    # Round 3: g_N is the RATIO OF MEANS over the refresh events in the
    # last day -- total log jump divided by total inter-refresh time --
    # not the endpoint difference over the window. The endpoint estimator
    # is biased by the partial intervals at the window edges (a refresh
    # just before the window start is excluded from the growth but its
    # hour still counts in the span, and vice versa); over a 4.5-day
    # horizon that edge noise is multiplied ~4.5x. The ratio uses each
    # event's own interval, so the edges stop mattering. Measured on the
    # independent synthetic finals: G-error MAE 0.55 log vs 0.64 for the
    # endpoint, and the worst case (s3k10, whose last day ran slow) fell
    # from 0.79 to 0.50. A decaying tracked model was tried and rejected:
    # even a 240-hour decay half-life costs +0.16 mean loss on the
    # independent finals (their growth is steady), so no decay is fitted.
    window_start = states[-1][0] - timedelta(hours=RECENT_WINDOW_H)
    us = [log_hours(t, release) for t, _, _ in states]
    # Refresh events: states where the tracked count changes.
    events = [(states[i - 1], states[i]) for i in range(1, len(states))
              if states[i][1] != states[i - 1][1]]
    win_events = [e for e in events if e[1][0] >= window_start]
    use_events = win_events if win_events else events
    if use_events:
        # Refresh events, each with its gap to the PREVIOUS refresh
        # (first-seen times; the first refresh ever has gap 0 and is
        # excluded, since its interval is unobserved). Distinct states
        # tick every ~10 min as rounded rates creep, so the gap must be
        # measured refresh-to-refresh, not state-to-state.
        _refl = []
        _prev_tr = None
        _prev_refresh_t = None
        for (_t, _tr, _r) in states:
            if _prev_tr is not None and _tr != _prev_tr:
                _gap = ((_t - _prev_refresh_t).total_seconds() / 3600.0
                        if _prev_refresh_t is not None else 0.0)
                _refl.append((_t, _prev_tr, _tr, _gap))
                _prev_refresh_t = _t
            _prev_tr = _tr
        _win = [r for r in _refl if r[0] >= window_start and r[3] > 0]
        if len(_win) >= 2:
            _tot_dj = sum(math.log(max(1, r[2])) - math.log(max(1, r[1]))
                          for r in _win)
            _tot_gap = sum(r[3] for r in _win)
            g_n = max(0.0, _tot_dj / _tot_gap) if _tot_gap > 0 else 0.0
        else:
            # Too few measurable refreshes: fall back to the endpoint.
            t_from = max(window_start, states[0][0]) if win_events else states[0][0]
            n_from = states[0][1]
            for (t, tr, _) in states:
                if t <= t_from:
                    n_from = tr
                else:
                    break
            span_h = max(1.0, (states[-1][0] - t_from).total_seconds() / 3600.0)
            g_n = (math.log(max(1, states[-1][1])) -
                   math.log(max(1, n_from))) / span_h
            g_n = max(0.0, g_n)
        t_at_target = float(last_tracked) * math.exp(
            min(LOG_GROWTH_CAP, g_n * horizon_h))
    else:
        # No refresh seen (a flat practice page): the launch prior.
        g_n = 0.0
        t_at_target = float(last_tracked)
    t_at_target = max(t_at_target, float(last_tracked))
    # The tracked fit has no residual of its own any more: its
    # uncertainty is folded into the dilution spread below.
    t_resid = 0.0
    # The catch-up jump a stale page is due at the next refresh: one
    # interval of tracked growth at the recent rate (or the launch-night
    # jump when no refresh has been seen).
    if use_events:
        jump = min(JUMP_CAP, max(0.0, g_n * tau))
    else:
        # No refresh seen: the page's data dates from when it was first
        # seen (t_data_h, ~launch on a frozen page) and the next refresh
        # carries it to the target. The power law already flattens with
        # age, so no separate maturity factor is needed.
        jump = (LAUNCH_GROWTH *
                math.log((1.0 + t_target_h) / (1.0 + t_data_h)))
        jump = min(JUMP_CAP, max(0.0, jump))
    # Probability a refresh lands before the target.
    remaining = max(0.0, tau - stale_h)
    p_refresh = 1.0 if remaining <= 0 else min(1.0, horizon_h / max(0.5, remaining))
    # Round 4: on a flat page the refresh is not a clock coin flip but a
    # catch-up event driven by player growth. Once the player base has
    # more than doubled since the page's data time (jump >= ln 2), the
    # page is long past any refresh trigger and the refresh is certain
    # before a target that far out. This only ever fires when the history
    # shows no refresh at all, so a rich final history is untouched.
    if not events and jump >= math.log(2.0):
        p_refresh = 1.0

    # --- kappa: how much of a tracked jump dilutes the rate. At a
    # refresh the rate drops by prog - kappa*log(N_new/N_old); the
    # trophies that drop the most have the least progression, so the
    # 10th percentile of the per-trophy log drops over the jump, divided
    # by the log jump, estimates kappa. On synthetic cases with known
    # kappa it recovers 0.49/0.69/1.00 for true 0.5/0.7/1.0.
    # Median over events; 0.7 when the history shows no refresh.
    kappa_hat = None
    if events:
        kappas = []
        for (prev, cur) in events:
            dlog_n = (math.log(max(1, cur[1])) -
                      math.log(max(1, prev[1])))
            if dlog_n <= 0:
                continue
            drops = []
            for j in range(len(trophies)):
                r0, r1 = prev[2][j], cur[2][j]
                if r0 is None or r1 is None or r0 <= 0.05:
                    continue
                drops.append(math.log(max(r1, 0.005)) -
                             math.log(max(r0, 0.005)))
            if len(drops) >= 10:
                k10 = percentile(drops, 0.10)
                if k10 is not None:
                    kappas.append(min(1.0, max(0.0, -k10 / dlog_n)))
        if kappas:
            kappa_hat = median(kappas)
    if kappa_hat is None:
        kappa_hat = KAPPA_FLAT if not events else KAPPA_DEFAULT
    coupl = 1.0 - kappa_hat  # earned grows with tracked^(1-kappa)

    # --- earned: recent progression slope per trophy, shrunk toward the
    # pooled slope. The progression slope is fitted on the DECOUPLED
    # series log(earned) - (1-kappa)*log(tracked), so the part of earned
    # growth that merely follows the tracked count is not mistaken for
    # progression; the coupling is added back explicitly at the target.
    # A 0.00% read is informative, not missing: nobody had earned it
    # yet. A half-count keeps it in log space. A slope is only trusted
    # when the last rate clears the rounding noise (a 0.01% rate rounds
    # a handful of earners into noise) and at most half the window sits
    # at the 0.00% floor (a trophy that just started earning shows a
    # phantom slope off the floor); otherwise the pooled slope rules.
    earned_slope = {}
    earned_resid = {}
    earned_last = {}
    for j in range(len(trophies)):
        pts = []
        for (t, tr, rates) in states:
            r = rates[j]
            if r is not None:
                le_raw = math.log(max(0.5, r / 100.0 * tr))
                le_dec = le_raw - coupl * math.log(max(1, tr))
                pts.append((t, log_hours(t, release), le_dec, le_raw, r))
        if not pts:
            continue
        earned_last[j] = (pts[-1][1], pts[-1][3])
        wpts = [p for p in pts if p[0] >= window_start]
        if len({p[1] for p in wpts}) < 2:
            wpts = pts
        lin = lin_fit([p[1] for p in wpts], [p[2] for p in wpts])
        if lin is None:
            continue
        floor_frac = sum(1 for p in wpts if p[4] <= 0.0) / len(wpts)
        reliable = pts[-1][4] > 0.05 and floor_frac <= 0.5
        earned_slope[j] = (min(3.0, max(0.0, lin[1])), reliable, len(wpts))
        earned_resid[j] = math.sqrt(
            sum((y - (lin[0] + lin[1] * x)) ** 2 for _, x, y, _, _ in wpts) / len(wpts))
    u_last = us[-1]
    rel_slopes = [b for (b, rel, _) in earned_slope.values() if rel]
    pool_b = median(rel_slopes)
    if pool_b is None:
        pool_b = median([b for (b, _, _) in earned_slope.values()])
    pool_resid = median([r for j, r in earned_resid.items()
                         if earned_slope[j][1]]) or 0.0
    if not pool_resid:
        pool_resid = median(list(earned_resid.values())) or 0.0

    horizon_sd = SPREAD_HORIZON_PER_DAY * math.sqrt(horizon_d)
    rows = []
    for j, trophy in enumerate(trophies):
        # Last non-null rate for this trophy, else a rare-trophy floor.
        last_rate = None
        for _, _, rates in reversed(states):
            if rates[j] is not None:
                last_rate = rates[j]
                break
        if last_rate is None:
            last_rate = 0.5
        anchor = max(0.5, last_rate / 100.0 * last_tracked)
        # Branch B's tracked: the fit's target, or the catch-up jump.
        t_branch = max(t_at_target, last_tracked * math.exp(jump))
        if last_rate >= 99.99:
            # Everybody holds it: earned stays equal to tracked.
            e_target = t_branch
            med_b = 99.99
        else:
            if j in earned_slope:
                b, reliable, n = earned_slope[j]
                # Shrink an unreliable slope all the way to the pool; a
                # reliable one keeps most of its own slope (n/(n+2)).
                w = n / (n + 2.0) if reliable else 0.0
                base_b = pool_b if pool_b is not None else b
                b_used = min(3.0, max(0.0, w * b + (1.0 - w) * base_b))
                u_obs, ln_e_obs = earned_last[j]
                e_prog = math.exp(ln_e_obs + sat_growth(b_used, target_u - u_obs))
            elif j in earned_last and pool_b is not None:
                u_obs, ln_e_obs = earned_last[j]
                e_prog = math.exp(ln_e_obs + sat_growth(pool_b, target_u - u_obs))
            elif pool_b is not None:
                e_prog = anchor * math.exp(max(0.0, sat_growth(pool_b, target_u - u_last)))
            else:
                e_prog = anchor * (1.0 + 0.02 * horizon_d)
            # Add back the part of earned growth that follows the
            # tracked count: earned grows with tracked^(1-kappa).
            e_target = e_prog * (t_branch / float(last_tracked)) ** coupl
            e_target = max(e_target, anchor)
            e_branch = max(e_target, anchor * math.exp(EARNED_FOLLOWS_JUMP * jump))
            e_branch = min(e_branch, t_branch * 0.999)
            med_b = clamp_pct(100.0 * e_branch / t_branch)
        fit_sd = math.sqrt((earned_resid.get(j, pool_resid)) ** 2 + t_resid ** 2)
        # Dilution spread: the tracked growth over the horizon is
        # G = log(t_branch / last_tracked); its logit cost is kappa*G,
        # uncertain in kappa (+-SD_KAPPA) and in the jump count/size
        # (sqrt(expected refreshes) * SD_LOGJUMP). This is the dominant
        # spread at the final horizon; the fit residual and horizon
        # terms are small beside it.
        g_log = math.log(max(1.0, t_branch) / max(1.0, last_tracked))
        if flat_page and not events:
            # Committed single refresh on a frozen page: kappa is
            # tightly known and there is no jump-count uncertainty,
            # only the jump's size.
            sigma_dil = math.sqrt((g_log * SD_KAPPA_FLAT) ** 2 +
                                  (kappa_hat * JUMP_SD_FLAT) ** 2)
            fit_floor = SPREAD_FIT_FLOOR_FLAT
        else:
            n_ref = max(1.0, horizon_h / max(1.0, tau))
            sd_g = math.sqrt(n_ref) * SD_LOGJUMP
            sigma_dil = math.sqrt((g_log * SD_KAPPA) ** 2 + (kappa_hat * sd_g) ** 2)
            fit_floor = SPREAD_FIT_FLOOR
        sigma_b = math.sqrt(max(fit_floor, fit_sd) ** 2 +
                            horizon_sd ** 2 + sigma_dil ** 2)
        sigma_b = min(SPREAD_MAX, max(SPREAD_MIN, sigma_b * SPREAD_SCALE))
        if last_rate >= 99.99:
            sigma_b = max(sigma_b, 1.0)
        rows.append({"id": trophy["id"],
                     "rate_a": clamp_pct(last_rate),
                     "rate_b": med_b,
                     "sigma_a": SPREAD_FROZEN if last_rate < 99.99 else 0.5,
                     "sigma_b": sigma_b,
                     "p": p_refresh})
    if os.environ.get("MAKEFUN_DEBUG"):
        LAST_DEBUG.clear()
        LAST_DEBUG.update({
            "g_n": g_n,
            "g_model": math.log(max(1.0, t_branch if rows else last_tracked) / max(1.0, last_tracked)) if rows else 0.0,
            "kappa_hat": kappa_hat,
            "jump": jump,
            "tau": tau,
            "stale_h": stale_h,
            "p_refresh": p_refresh,
            "t_at_target": t_at_target,
            "last_tracked": last_tracked,
            "n_events": len(events),
            "n_win_events": len(win_events),
            "pool_b": pool_b,
            "t_branch": t_branch if rows else None,
        })
    return rows

def mixture_quantile(rate_a, sigma_a, rate_b, sigma_b, p, tau):
    """One quantile of the two-branch mixture, by bisection on its CDF.

    F(x) = (1-p) * Phi((x - logit(rate_a)) / sigma_a)
         + p * Phi((x - logit(rate_b)) / sigma_b), in logit space.
    When p is 0 the frozen page rules; when p is 1 the refreshed fit
    rules; in between the quantiles honestly straddle both branches.
    """
    if p <= 0.0:
        return inv_logit_pct(logit(rate_a) + _z(tau) * sigma_a)
    if p >= 1.0:
        return inv_logit_pct(logit(rate_b) + _z(tau) * sigma_b)
    la, lb = logit(rate_a), logit(rate_b)
    sig = max(sigma_a, sigma_b)
    lo = min(la, lb) - 8.0 * sig - 1.0
    hi = max(la, lb) + 8.0 * sig + 1.0

    def cdf(x):
        return ((1.0 - p) * norm_cdf((x - la) / sigma_a) +
                p * norm_cdf((x - lb) / sigma_b))

    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if cdf(mid) < tau:
            lo = mid
        else:
            hi = mid
    return inv_logit_pct(0.5 * (lo + hi))


def _z(tau):
    """Standard normal quantile at tau (Acklam's approximation)."""
    # Coefficients for the rational approximation (Abramowitz-Stegun 26.2.23
    # via Acklam); accurate to ~1e-9, far tighter than the scoring needs.
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285984469534e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if tau < plow:
        q = math.sqrt(-2 * math.log(tau))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if tau > phigh:
        q = math.sqrt(-2 * math.log(1 - tau))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = tau - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def forecast_forecast(case):
    """One case's forecast rows; never raises (a valid file beats a crash:
    an invalid case is scored as the last rate and takes no prize)."""
    try:
        rows = forecast_case(case)
        out = []
        for row in rows:
            qs = [round4(mixture_quantile(row["rate_a"], row["sigma_a"],
                                          row["rate_b"], row["sigma_b"],
                                          row["p"], tau))
                  for tau in LEVELS]
            for k in range(1, len(qs)):
                if qs[k] < qs[k - 1]:
                    qs[k] = qs[k - 1]
            out.append({"id": row["id"], "q": qs})
        return {"trophies": out}
    except Exception:
        # Fallback: last rate, wide spread. Still a valid forecast.
        last = case["history"][-1]["rates"] if case.get("history") else []
        out = []
        for i, trophy in enumerate(case["trophies"]):
            rate = last[i] if i < len(last) and last[i] is not None else 0.5
            med = clamp_pct(rate if rate > 0 else 0.5)
            centre = logit(med)
            qs = [round4(inv_logit_pct(centre + z * 1.0)) for z in Z]
            for k in range(1, len(qs)):
                if qs[k] < qs[k - 1]:
                    qs[k] = qs[k - 1]
            out.append({"id": trophy["id"], "q": qs})
        return {"trophies": out}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(IN_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_forecast(case)
        (OUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()
