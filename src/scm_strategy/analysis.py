# SPDX-License-Identifier: BSD-3-Clause
"""Small-sample participant analysis with explicitly supplied configuration."""
from __future__ import annotations

import numpy as np
from .schema import validate_records,SchemaError
from .synthetic import verify_recipe
from .statistics import (fit_ols,coefficient_intervals,loso,bootstrap_analysis,percentile_interval)

ANALYSIS_VERSION="scm-strategy.analysis/1"
OUTCOME_MODELS={"contact_ms":("ms","height_cm"),"pressure_peak_N":("N","weight_kg")}


def model_design(records,size):
    v=np.array([r["speed_kmh"] for r in records])
    s=np.array([r[size] for r in records])
    knee=np.array([r["knee_excursion_deg"] for r in records])
    ankle=np.array([r["ankle_excursion_deg"] for r in records])
    x0=np.column_stack([np.ones(len(records)),np.log(v),np.log(s)])
    return x0,np.column_stack([x0,knee/10,ankle/10])


def analyze(records,metadata,*,dataset_kind="private_empirical",bootstrap_replicates=2000,seed=20261030):
    rows=validate_records(records,metadata)
    if dataset_kind not in {"private_empirical","synthetic"}:
        raise SchemaError("unsupported_analysis_dataset_kind")
    if dataset_kind=="synthetic":
        verify_recipe(rows,metadata)
    if len(rows)<20:
        raise SchemaError("analysis_requires_at_least_20_participants")
    if not isinstance(bootstrap_replicates,int) or not 1<=bootstrap_replicates<=20000:
        raise SchemaError("bootstrap_replicates_must_be_1_to_20000")
    if not isinstance(seed,int) or seed<0:
        raise SchemaError("seed_must_be_nonnegative_integer")
    ids=[r["participant_id"] for r in rows]
    result={"analysis_version":ANALYSIS_VERSION,"dataset_kind":dataset_kind,"n_participants":len(rows),
            "configuration":{"bootstrap_replicates":bootstrap_replicates,"seed":seed},
            "independent_unit":"participant","outcomes":{},
            "interpretation":"Observational association and participant-held-out prediction; no causal, metabolic, injury or equivalence claim."}
    for index,(outcome,(unit,size)) in enumerate(OUTCOME_MODELS.items()):
        y=np.array([r[outcome] for r in rows])
        x0,x1=model_design(rows,size)
        fit=fit_ols(x1,np.log(y))
        ci=coefficient_intervals(fit)
        cv=loso(y,x0,x1,ids)
        boot=bootstrap_analysis(y,x0,x1,ids,bootstrap_replicates,seed+index)
        labels=["intercept","log_speed_kmh","log_"+size,"knee_excursion_deg_per10","ankle_excursion_deg_per10"]
        coefficients=[]
        for i,label in enumerate(labels):
            values=boot["coefficients_augmented"][:,i] if boot["valid"] else np.array([])
            coefficients.append({"term":label,"estimate":float(fit.beta[i]),"hc3_ci95":ci[i].tolist(),
                                 "bootstrap_ci95":percentile_interval(values)})
        metric_boot=[m["delta_mae_baseline_minus_augmented"] for m in boot["metrics"]]
        predictions=[{("participant_id" if key=="anonymized_id" else key):value for key,value in row.items()} for row in cv["predictions"]]
        result["outcomes"][outcome]={"unit":unit,"baseline_terms":labels[:3],"augmented_terms":labels,
            "coefficients":coefficients,"design_condition_number":fit.condition_number,
            "condition_number_above_30":fit.condition_number>30,"residual_df":fit.df,
            "cross_validation":cv["metrics"],"delta_mae_bootstrap_ci95":percentile_interval(np.array(metric_boot)),
            "bootstrap":{"requested":boot["requested"],"valid":boot["valid"],"failures":boot["failures"]},
            "predictions":predictions}
    return result

