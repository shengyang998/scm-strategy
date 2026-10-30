# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 SCM Research contributors. New project contribution.
"""Independent equations for a complete paper-study demonstration bundle.

This module contains no empirical rows, fitted empirical moments, source-device
parsers, or stored manuscript results. Structural sample sizes are configurable.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import numpy as np

from .schema import UNITS

GENERATOR_VERSION = "scm-strategy.paper-equations/1"
PAPER_SCHEMA_VERSION = "scm-strategy.paper-bundle/1"
PROTOCOL_ID = "scm-strategy-pressure/1.0.0"
SENSITIVITY_SPECS = (
    "participant_mean", "p10_p90", "offset_m010", "offset_p010", "offset_m025", "offset_p025"
)


def _common(identifier, index, suffix):
    return {"participant_id": identifier, "trial_id": f"{identifier}-{suffix}-{index}",
            "trial_index": index, "direction": "backward", "available": True,
            "exclusion_reason": ""}


def generate_paper_bundle(total_participants=50, primary_participants=25, seed=20261030):
    """Return all standard tables needed by the 22 fixed analysis configurations.

    Values come only from the equations below. Repeated-trial and sensitivity
    tables are synthetic teaching examples, not recovered device measurements.
    """
    for label, value in [("total_participants", total_participants), ("primary_participants", primary_participants)]:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(label + "_must_be_integer")
    if not 20 <= primary_participants < total_participants <= 10000:
        raise ValueError("require_20_le_primary_lt_total_le_10000")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed_must_be_nonnegative_integer")
    rng = np.random.default_rng(seed)
    primary, extension, paired, repeats, sensitivities = [], [], [], [], []
    profiles = []
    repeat_motion_n = max(1, primary_participants // 5)
    single_pressure_n = max(1, total_participants // 12)
    for i in range(total_participants):
        identifier = f"SYN-{i+1:05d}"
        height = float(rng.uniform(154, 190))
        weight = float(rng.uniform(49, 94))
        age = float(rng.uniform(20, 67))
        navicular = float(rng.uniform(.105, .195))
        foot_size = float(rng.uniform(215, 330))
        # Nearby task speeds create pairs without looking at any outcome.
        speed = float(7.6 + .58 * (i % 10) + rng.uniform(-.025, .025))
        knee = float(49 + 2.2 * (speed-10) + 18*(navicular-.15) + rng.normal(0, 5))
        ankle = float(36 + .9 * (speed-10) - 12*(navicular-.15) + rng.normal(0, 4))
        offsets = rng.normal(0, [.055, .065, .035])
        body = dict(height_cm=height, weight_kg=weight, age_years=age,
                    navicular_ratio=navicular, foot_size_proxy_cm2=foot_size)
        trial_rows = []
        n_pressure = 1 if i >= total_participants-single_pressure_n else (3 if i == 1 else 2)
        for j in range(n_pressure):
            index = j+2
            v = speed + .008*j
            k = max(1., knee + rng.normal(0, .75))
            a = max(1., ankle + rng.normal(0, .65))
            contact = float(np.exp(np.log(268)-.43*np.log(v/10)+.25*np.log(height/172)
                                   -.04*(k-49)/10+.025*(a-36)/10+offsets[0]+rng.normal(0,.012)))
            peak = float(np.exp(np.log(1270)+.50*np.log(v/10)+.80*np.log(weight/68)
                                +.025*(k-49)/10-.015*(a-36)/10+offsets[1]+rng.normal(0,.016)))
            area = float(np.exp(np.log(121)+.55*np.log(foot_size/270)+.13*np.log(weight/68)
                                +.8*(navicular-.15)+offsets[2]-.004*j+rng.normal(0,.018)))
            row = {**_common(identifier,index,"trial"), **body, "speed_kmh":v,
                   "knee_excursion_deg":k,"ankle_excursion_deg":a,"contact_ms":contact,
                   "pressure_peak_N":peak,"effective_area_cm2":area,
                   "qc_status":"WARNING" if i % 8 == 0 and j == 0 else "PASS"}
            trial_rows.append(row)
            repeats.append({**_common(identifier,index,"trial"),"speed_kmh":v,"effective_area_cm2":area})
        extension.append({k:v for k,v in trial_rows[0].items()
                          if k not in {"knee_excursion_deg","ankle_excursion_deg","qc_status"}})
        foot_length = float(rng.uniform(235,290))
        profiles.append({"participant_id":identifier,"height_cm":height,"weight_kg":weight,"age_years":age,
                         "bmi":weight/(height/100)**2,
                         "recorded_sex":"F" if i % 3 == 0 else "M",
                         "body_fat_pct":float(rng.uniform(11,32)),
                         "navicular_height_L_mm":navicular*foot_length,
                         "navicular_height_R_mm":navicular*foot_length*(1+.015*np.cos(i)),
                         "subject_median_speed_kmh":float(np.median([r["speed_kmh"] for r in trial_rows]))})
        if i >= primary_participants:
            continue
        selected = deepcopy(trial_rows[0])
        primary.append(selected)
        own_pairs = deepcopy(trial_rows[:2] if i < repeat_motion_n else trial_rows[:1])
        paired.extend(own_pairs)
        average = deepcopy(selected)
        average["trial_id"] = f"{identifier}-mean"
        for field in UNITS:
            average[field] = float(np.mean([r[field] for r in own_pairs]))
        statuses = {r["qc_status"] for r in own_pairs}
        average["qc_status"] = "MIXED_PASS_WARNING" if len(statuses)>1 else next(iter(statuses))
        sensitivities.append({**average,"spec":"participant_mean"})
        percentiles = {**deepcopy(selected),"spec":"p10_p90"}
        percentiles["knee_excursion_deg"] *= .88
        percentiles["ankle_excursion_deg"] *= .86
        sensitivities.append(percentiles)
        for spec, delta in [("offset_m010",-.10),("offset_p010",.10),("offset_m025",-.25),("offset_p025",.25)]:
            row = {**deepcopy(selected),"spec":spec}
            row["knee_excursion_deg"] *= 1 + delta*.015*np.sin(i+1)
            row["ankle_excursion_deg"] *= 1 + delta*.020*np.cos(i+1)
            row["contact_ms"] *= 1 + delta*.004*np.sin(i+2)
            row["pressure_peak_N"] *= 1 + delta*.006*np.cos(i+3)
            row["effective_area_cm2"] *= 1 + delta*.003*np.sin(i+4)
            sensitivities.append(row)
    metadata = {
        "schema_version":PAPER_SCHEMA_VERSION,"protocol_id":PROTOCOL_ID,
        "dataset_kind":"synthetic","units":{**UNITS,"bmi":"kg/m^2","body_fat_pct":"%",
            "navicular_height_L_mm":"mm","navicular_height_R_mm":"mm","subject_median_speed_kmh":"km/h"},
        "generator":{"version":GENERATOR_VERSION,"seed":seed,
                     "parameters":{"total_participants":total_participants,"primary_participants":primary_participants}},
        "description":"Independent equations, not an empirical fit. Sensitivity rows demonstrate a table contract; raw-time perturbations require private or independently licensed adapters. Profile median speed uses all generated eligible nonfirst pressure trials, not extension index speed.",
        "cohort_counts":{"source_participants":total_participants,"source_pressure_trials":len(repeats),
            "eligible_pressure_trials":len(repeats),"pressure_excluded_trials":0,
            "conservative_pair_count":len(paired),"eligible_nonfirst_backward_trials":len(repeats)},
    }
    return {"metadata":metadata,"primary":primary,"extension":extension,
            "sensitivities":sensitivities,"pressure_repeats":repeats,
            "paired_trials":paired,"cohort_profiles":profiles}


def verify_paper_recipe(bundle):
    """Verify exact regeneration; a dataset_kind label alone is not evidence."""
    from .schema import SchemaError
    meta = bundle.get("metadata",{})
    recipe = meta.get("generator",{})
    if meta.get("dataset_kind") != "synthetic" or recipe.get("version") != GENERATOR_VERSION:
        raise SchemaError("unsupported_paper_synthetic_recipe")
    parameters = recipe.get("parameters",{})
    if set(parameters) != {"total_participants","primary_participants"}:
        raise SchemaError("unexpected_paper_synthetic_parameters")
    expected = generate_paper_bundle(**parameters,seed=recipe.get("seed"))
    for table in ["primary","extension","sensitivities","pressure_repeats","paired_trials","cohort_profiles"]:
        if bundle.get(table) != expected[table]:
            raise SchemaError("paper_synthetic_table_does_not_match_recipe:"+table)
    return expected


def paper_synthetic_digest(bundle):
    payload={key:bundle[key] for key in ["primary","extension","sensitivities","pressure_repeats","paired_trials","cohort_profiles"]}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def write_synthetic_bundle(directory, *, total_participants=50, primary_participants=25, seed=20261030):
    """Use the shared schema writer rather than another CSV implementation."""
    from .paper_bundle import write_paper_bundle
    bundle=generate_paper_bundle(total_participants,primary_participants,seed)
    write_paper_bundle(bundle,directory)
    return bundle
