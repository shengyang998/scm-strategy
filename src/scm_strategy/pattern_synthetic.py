# SPDX-License-Identifier: BSD-3-Clause
"""Independent numeric examples; no empirical records, templates or fitted values."""
from __future__ import annotations

import numpy as np

from .pattern_bundle import CHANNELS, SCHEMA_VERSION, UNITS, validate_pattern_bundle


def generate_pattern_bundle(participants=50, primary_participants=25, seed=20261030, samples=240):
    if participants < 12 or primary_participants < 8 or primary_participants > participants or samples < 40:
        raise ValueError("synthetic_example_requires_12_people_8_primary_40_samples")
    rng = np.random.default_rng(seed)
    people, index, repeats, pairs, clouds, ids = [], [], [], [], [], []
    t = np.arange(samples) * 20 / samples
    pressure_fields = ("pressure_peak_N_left", "pressure_peak_N_right", "effective_area_cm2_left", "effective_area_cm2_right")
    for i in range(participants):
        pid = f"SYN-{i + 1:05d}"
        length = rng.uniform(225, 280, 2)
        ratio = rng.uniform(.12, .19) + rng.normal(0, .009, 2)
        person = {"participant_id": pid, "height_cm": rng.uniform(150, 190), "weight_kg": rng.uniform(48, 92),
            "navicular_ratio": float(ratio.mean()), "navicular_height_left_mm": float(length[0] * ratio[0]),
            "navicular_height_right_mm": float(length[1] * ratio[1]), "foot_length_left_mm": float(length[0]), "foot_length_right_mm": float(length[1]),
            "forefoot_width_left_mm": rng.uniform(82, 110), "forefoot_width_right_mm": rng.uniform(82, 110)}
        people.append(person)
        speed = 7.5 + .75 * (i // 5) + rng.uniform(-.015, .015)
        base = np.array([person["weight_kg"] * 14, person["weight_kg"] * 14, 95 + .18 * person["height_cm"], 95 + .18 * person["height_cm"]])
        base *= np.exp(rng.normal(0, .035, 4))
        contact = 230 + rng.normal(0, 14)
        index.append({"participant_id": pid, "trial_id": f"IX-{i + 1:05d}", "speed_kmh": speed, "contact_ms": contact, **dict(zip(pressure_fields, base))})
        n_repeats = 2 if i % 7 else 1
        for repeat in range(n_repeats):
            pressure = base * np.exp(rng.normal(0, .01, 4))
            repeats.append({"participant_id": pid, "trial_id": f"PR-{i + 1:05d}-{repeat}", "replicate_index": repeat + 1,
                "speed_kmh": speed + rng.normal(0, .004), "contact_ms": contact + rng.normal(0, 2), **dict(zip(pressure_fields, pressure)),
                "available": True, "direction": "backward", "window_duration_s": 20., "n_left_events": 26, "n_right_events": 26})
        if i >= primary_participants:
            continue
        n_motion = 2 if i < min(5, primary_participants) else 1
        frequency = 1.3 + rng.uniform(-.09, .09)
        knee_amp, ankle_amp = rng.uniform(23, 38), rng.uniform(10, 19)
        phase = rng.uniform(-.2, .2)
        asymmetry = rng.uniform(.02, .13)
        posture = rng.normal(0, 2, 4)
        for repeat in range(n_motion):
            pair_id = f"PA-{i + 1:05d}-{repeat}"
            theta = 2 * np.pi * frequency * t + phase + repeat * .07
            trace = np.column_stack([35 + knee_amp * np.sin(theta), 5 + ankle_amp * np.sin(theta + .6),
                35 + knee_amp * (1 + asymmetry) * np.sin(theta + np.pi), 5 + ankle_amp * (1 - asymmetry) * np.sin(theta + np.pi + .6)])
            trace += posture + rng.normal(0, .12, trace.shape)
            clouds.append(trace); ids.append(pair_id)
            pressure = base * np.exp(rng.normal(0, .008, 4))
            pairs.append({"pair_id": pair_id, "participant_id": pid, "replicate_index": repeat + 1,
                "speed_kmh": speed + rng.normal(0, .003), "is_primary": repeat == 0, "primary_order": i if repeat == 0 else None,
                "analysis_order": len(pairs), "window_start_s": 0., "window_end_s": 20., "contact_ms": contact + rng.normal(0, 2),
                **dict(zip(pressure_fields, pressure)), "motion_status": "valid", "qc_status": "SYNTHETIC",
                "available": True, "direction": "backward", "n_left_events": 26, "n_right_events": 26})
    bundle = {"metadata": {"schema_version": SCHEMA_VERSION, "dataset_kind": "synthetic", "units": UNITS,
        "recording_scope": "Independent sinusoidal coordinate arrays and lognormal pressure examples; no empirical data or scientific effect estimate.",
        "generator": {"name": "scm-strategy.pattern-equations/1", "seed": seed, "participants": participants, "primary_participants": primary_participants, "samples_per_record": samples}},
        "participants": people, "pressure_index": index, "pressure_repeats": repeats, "paired_trials": pairs,
        "motion": {"pair_ids": np.array(ids, dtype=str), "row_offsets": np.arange(len(ids) + 1, dtype=np.int64) * samples,
                   "values_deg": np.vstack(clouds), "channel_names": np.array(CHANNELS, dtype=str)}}
    return validate_pattern_bundle(bundle)
