# SPDX-License-Identifier: BSD-3-Clause
"""Device-independent numerical features. Units are explicit; inputs are arrays."""
from __future__ import annotations

import math
import numpy as np


def effective_area_frame(pressure, cell_area_cm2):
    """Input pressure in N/cm²; return force N, effective cm² and occupied cm²."""
    p = np.asarray(pressure, dtype=np.float64)
    if not math.isfinite(cell_area_cm2) or cell_area_cm2 <= 0:
        raise ValueError("invalid_cell_area")
    if not np.isfinite(p).all() or np.any(p < 0):
        raise ValueError("invalid_pressure_values")
    total = float(p.sum())
    squared = float(np.square(p).sum())
    if total == 0:
        return 0.0, np.nan, 0.0
    return cell_area_cm2 * total, cell_area_cm2 * total * total / squared, cell_area_cm2 * int(np.count_nonzero(p))


def force_weighted_area(forces, areas, durations):
    """N, cm², seconds -> (effective cm², numerator N·cm²·s, impulse N·s)."""
    force, area, dt = (np.asarray(x, dtype=float) for x in (forces, areas, durations))
    if not (force.shape == area.shape == dt.shape):
        raise ValueError("frame_array_shape_mismatch")
    if not np.isfinite(force).all() or not np.isfinite(dt).all() or np.any(force < 0) or np.any(dt <= 0):
        raise ValueError("invalid_frame_weight")
    positive = force > 0
    if not np.isfinite(area[positive]).all() or np.any(area[positive] <= 0):
        raise ValueError("undefined_area_under_positive_load")
    denominator = float((force * dt).sum())
    numerator = float((force[positive] * area[positive] * dt[positive]).sum())
    return (numerator / denominator if denominator > 0 else np.nan), numerator, denominator


def percentile_excursion(values, percentiles=(5,95), *, unit):
    """Robust model-coordinate excursion, not a complete anatomical ROM."""
    if unit != "degree":
        raise ValueError("angle_unit_must_be_degree")
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or len(x) < 2 or not np.isfinite(x).all():
        raise ValueError("invalid_angle_series")
    if len(percentiles) != 2 or not (0 <= percentiles[0] < percentiles[1] <= 100):
        raise ValueError("invalid_percentiles")
    q = np.percentile(x, percentiles, method="linear")
    return float(q[1] - q[0])


def bilateral_excursion(time_s, left, right, window_s, *, unit, time_offset_s=0., percentiles=(5,95)):
    """Use all continuous samples in a declared reference-time window.

    time_offset_s maps source time into reference time once. The caller owns
    coordinate interpretation and synchronization; no event segmentation occurs.
    """
    time, l, r = (np.asarray(x,dtype=float) for x in (time_s,left,right))
    if time.ndim != 1 or not (time.shape == l.shape == r.shape) or len(time)<2:
        raise ValueError("invalid_series_shape")
    if not np.isfinite(time).all() or not np.all(np.diff(time)>0):
        raise ValueError("invalid_time_axis")
    if len(window_s)!=2 or not all(math.isfinite(x) for x in window_s) or window_s[0]>=window_s[1]:
        raise ValueError("invalid_window")
    if not math.isfinite(time_offset_s):
        raise ValueError("invalid_offset")
    t = time + time_offset_s
    use = (t >= window_s[0]-1e-9) & (t <= window_s[1]+1e-9)
    lv=percentile_excursion(l[use],percentiles,unit=unit)
    rv=percentile_excursion(r[use],percentiles,unit=unit)
    return {"left_deg":lv,"right_deg":rv,"mean_deg":(lv+rv)/2,"left_minus_right_deg":lv-rv,"n_samples":int(use.sum())}

