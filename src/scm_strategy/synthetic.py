# SPDX-License-Identifier: BSD-3-Clause
"""Fixed standalone equations. No empirical parameters, rows or fitted curves."""
from __future__ import annotations

import hashlib
import numpy as np
from .schema import SCHEMA_VERSION,UNITS,validate_records,canonical_csv,SchemaError

GENERATOR_VERSION="scm-strategy.equations/1"


def generate(participants=60,seed=20261030):
    if not isinstance(participants,int) or participants<20 or participants>10000:
        raise ValueError("synthetic_participants_must_be_20_to_10000")
    if not isinstance(seed,int) or seed<0:
        raise ValueError("seed_must_be_nonnegative_integer")
    rng=np.random.default_rng(seed)
    rows=[]
    for i in range(participants):
        speed=float(rng.uniform(7,13))
        height=float(rng.uniform(152,190))
        weight=float(rng.uniform(48,92))
        age=float(rng.uniform(20,65))
        nav=float(rng.uniform(.10,.20))
        foot=float(rng.uniform(210,315))
        knee=float(48+2.4*(speed-10)+rng.normal(0,5))
        ankle=float(38+1.2*(speed-10)+rng.normal(0,4))
        contact=float(np.exp(np.log(260)-.42*np.log(speed/10)+.25*np.log(height/170)-.035*(knee-48)/10+.018*(ankle-38)/10+rng.normal(0,.035)))
        peak=float(np.exp(np.log(1300)+.55*np.log(speed/10)+.75*np.log(weight/68)+.02*(knee-48)/10-.018*(ankle-38)/10+rng.normal(0,.04)))
        area=float(np.exp(np.log(120)+.5*np.log(foot/260)+.15*np.log(weight/68)+.9*(nav-.15)+rng.normal(0,.025)))
        rows.append(dict(participant_id=f"SYN-{i+1:05d}",speed_kmh=speed,height_cm=height,weight_kg=weight,age_years=age,
                         navicular_ratio=nav,foot_size_proxy_cm2=foot,knee_excursion_deg=knee,ankle_excursion_deg=ankle,
                         contact_ms=contact,pressure_peak_N=peak,effective_area_cm2=area))
    metadata={"schema_version":SCHEMA_VERSION,"dataset_kind":"synthetic","units":dict(UNITS),
              "generator":{"version":GENERATOR_VERSION,"seed":seed,"parameters":{"participants":participants}}}
    return rows,metadata


def verify_recipe(records,metadata):
    """A synthetic label alone is insufficient: every value must regenerate."""
    if metadata.get("dataset_kind")!="synthetic":
        raise SchemaError("synthetic_recipe_required")
    recipe=metadata.get("generator",{})
    if set(recipe)!={"version","seed","parameters"} or recipe.get("version")!=GENERATOR_VERSION:
        raise SchemaError("unsupported_synthetic_generator")
    params=recipe.get("parameters",{})
    if set(params)!={"participants"}:
        raise SchemaError("unexpected_synthetic_parameter")
    expected,_=generate(params["participants"],recipe["seed"])
    actual=validate_records(records,metadata)
    if canonical_csv(actual)!=canonical_csv(expected):
        raise SchemaError("synthetic_input_does_not_match_recipe")
    return expected


def synthetic_digest(records):
    return hashlib.sha256(canonical_csv(records).encode()).hexdigest()

