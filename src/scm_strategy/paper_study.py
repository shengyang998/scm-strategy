# SPDX-License-Identifier: BSD-3-Clause
"""Portable frozen-paper orchestration, using standardized inputs only.

Migrated from project-authored study.py; no device reader code is included.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from importlib.resources import files
import math
from collections import Counter

import numpy as np
from scipy.stats import spearmanr
from .paper_bundle import validate_paper_bundle, read_paper_bundle, PROTOCOL_ID

from .statistics import (
    NumericalFailure, bootstrap_analysis, coefficient_intervals,
    containment_frontier, fit_ols, log_ratio_intervals, loso,
    percentile_interval, raw_predictions,
)


TRANSFORMS = {
    "log_speed_kmh": ("speed_kmh", np.log),
    "log_height_cm": ("height_cm", np.log),
    "log_weight_kg": ("weight_kg", np.log),
    "log_foot_size_proxy_cm2": ("foot_size_proxy_cm2", np.log),
    "age_years_per10": ("age_years", lambda x: x / 10),
    "navicular_ratio_per001": ("navicular_ratio", lambda x: x / .01),
    "knee_excursion_deg_per10": ("knee_excursion_deg", lambda x: x / 10),
    "ankle_excursion_deg_per10": ("ankle_excursion_deg", lambda x: x / 10),
}


def number(row: dict, key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, ValueError, TypeError):
        return float("nan")


def design(records: list[dict], terms: list[str]) -> np.ndarray:
    columns = [np.ones(len(records))]
    for term in terms:
        raw, transform = TRANSFORMS[term]
        values = np.array([number(r, raw) for r in records])
        with np.errstate(invalid="ignore", divide="ignore"):
            columns.append(transform(values))
    return np.column_stack(columns)


def select_complete(records: list[dict], terms: list[str], outcome: str, logged: bool = True):
    ids = [r["participant_id"] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("participant table has duplicate ids")
    x = design(records, terms)
    y = np.array([number(r, outcome) for r in records])
    valid = np.isfinite(x).all(axis=1) & np.isfinite(y)
    valid &= np.array([r.get("available", True) is True for r in records])
    if logged:
        valid &= y > 0
    included = [r for r, ok in zip(records, valid) if ok]
    excluded = []
    for i,(row,ok) in enumerate(zip(records,valid)):
        if ok:continue
        reasons=[]
        if row.get("available",True) is not True:reasons.append("input_unavailable:"+row.get("exclusion_reason",""))
        missing_terms=[term for j,term in enumerate(terms,1) if not np.isfinite(x[i,j])]
        if missing_terms:reasons.append("missing_predictors:"+",".join(missing_terms))
        if not np.isfinite(y[i]) or (logged and y[i]<=0):reasons.append("missing_or_invalid_outcome:"+outcome)
        excluded.append({"participant_id":row["participant_id"],"reason":";".join(reasons)})
    return included, x[valid], y[valid], excluded


def select_cases(records: list[dict], caliper: float, max_pairs: int) -> tuple[list[dict], dict]:
    """Selection reads only id, speed, height, weight, and navicular ratio."""
    keys = ["height_cm", "weight_kg", "navicular_ratio"]
    complete = [r for r in records if all(np.isfinite(number(r, k)) for k in keys + ["speed_kmh"])]
    values = np.array([[number(r, k) for k in keys] for r in complete])
    if len(complete) < 2:
        return [], {"reason": "fewer than two complete body profiles"}
    sd = values.std(axis=0, ddof=1)
    if np.any(sd <= 0):
        return [], {"reason": "zero body-feature sample SD; no unplanned scaling substitution"}
    candidates = []
    for i in range(len(complete)):
        for j in range(i + 1, len(complete)):
            a, b = sorted([complete[i], complete[j]], key=lambda r: r["participant_id"])
            dv = abs(number(a, "speed_kmh") - number(b, "speed_kmh"))
            if dv <= caliper:
                delta = np.array([number(a, k) - number(b, k) for k in keys]) / sd
                candidates.append({"participant_a": a["participant_id"], "participant_b": b["participant_id"],
                                   "body_distance": float(np.linalg.norm(delta)), "speed_difference_kmh": dv,
                                   "standardized_speed_kmh": (number(a, "speed_kmh") + number(b, "speed_kmh")) / 2})
    candidates.sort(key=lambda r: (-r["body_distance"], r["participant_a"], r["participant_b"]))
    chosen, used = [], set()
    for row in candidates:
        if row["participant_a"] not in used and row["participant_b"] not in used:
            chosen.append(row)
            used.update([row["participant_a"], row["participant_b"]])
            if len(chosen) == max_pairs:
                break
    return chosen, {"scale": "sample SD ddof=1", "body_features": keys, "sample_sd": sd.tolist(),
                    "n_body_complete": len(complete), "n_speed_matched_candidate_pairs": len(candidates),
                    "selection_did_not_use": ["motion features", "pressure outcomes", "model residuals"]}


def coefficient_rows(fit, terms, samples=None, logged=True):
    ci95 = coefficient_intervals(fit, .95)
    ci90 = coefficient_intervals(fit, .90)
    rows = []
    for j, term in enumerate(["intercept"] + terms):
        boot = percentile_interval(samples[:, j]) if samples is not None and len(samples) else None
        row = {"term": term, "estimate": float(fit.beta[j]), "hc3_se": float(np.sqrt(max(fit.covariance_hc3[j, j], 0))),
               "hc3_ci95": ci95[j].tolist(), "hc3_ci90": ci90[j].tolist(), "participant_bootstrap_ci95": boot}
        if logged:
            row.update({"conditional_geometric_mean_ratio": float(np.exp(fit.beta[j])),
                        "geometric_ratio_hc3_ci95": np.exp(ci95[j]).tolist(),
                        "ratio_interpretation": "geometric mean association per listed term unit, not an arithmetic mean effect"})
        rows.append(row)
    return rows


def diagnostics(fit, x, terms, minimum_n, max_condition):
    reasons = []
    if len(x) < minimum_n:
        reasons.append(f"n={len(x)} below frozen minimum {minimum_n}")
    if fit.condition_number > max_condition:
        reasons.append(f"standardized design condition number={fit.condition_number:.6g} above {max_condition}")
    residual_features = {}
    for j, term in enumerate(["fitted_log_outcome"] + terms):
        values = fit.fitted if j == 0 else x[:, j]
        if np.std(values) > 0 and np.std(fit.residual) > 0:
            residual_features[term] = float(spearmanr(values, fit.residual).statistic)
    rho = float(spearmanr(fit.fitted, np.abs(fit.residual)).statistic) if np.std(fit.fitted) > 0 else None
    return {"rank": fit.rank, "n_parameters": x.shape[1], "residual_df": fit.df,
            "standardized_design_condition_number": fit.condition_number,
            "max_leverage": float(np.max(fit.leverage)), "log_residual_sd": float(np.sqrt(fit.sigma2)),
            "global_smearing_factor": fit.smear, "residual_spearman_correlations": residual_features,
            "abs_residual_vs_fitted_spearman": rho,
            "interpretation_gate_passed": not reasons, "stop_interpretation_reasons": reasons,
            "smearing_assumption": "training residual distribution represents the conditional log error distribution; HC3 does not correct heteroscedastic retransformation bias"}


def prediction_analysis(records, name, outcome, controls, protocol, replicates, seed, cases=None, progress=None):
    terms = controls + protocol["strategy_terms"]
    included, x1, y, excluded = select_complete(records, terms, outcome)
    ids = [r["participant_id"] for r in included]
    result = {"analysis": name, "outcome": outcome, "controls": controls, "strategy_terms": protocol["strategy_terms"],
              "n": len(ids), "input_n": len(records), "included_ids": ids, "exclusions": excluded}
    if len(y) <= x1.shape[1]:
        return {**result, "status": "numerically_not_estimable", "reason": "no residual degrees of freedom"}
    x0 = x1[:, :1 + len(controls)]
    try:
        f0 = fit_ols(x0, np.log(y))
        f1 = fit_ols(x1, np.log(y))
        cv = loso(y, x0, x1, ids)
    except (NumericalFailure, np.linalg.LinAlgError) as exc:
        return {**result, "status": "numerically_not_estimable", "reason": str(exc)}
    lookup = {r["participant_id"]: r for r in included}
    usable_cases, contrasts = [], []
    for case in cases or []:
        if case["participant_a"] not in lookup or case["participant_b"] not in lookup:
            usable_cases.append({**case, "status": "selected_case_unavailable_for_model"})
            continue
        a = {**lookup[case["participant_a"]], "speed_kmh": case["standardized_speed_kmh"]}
        b = {**lookup[case["participant_b"]], "speed_kmh": case["standardized_speed_kmh"]}
        xa, xb = design([a, b], terms)
        contrasts.append((xa, xb))
        usable_cases.append({**case, "status": "model_available", "contrast_index": len(contrasts) - 1,
                             "observed_a": number(lookup[case["participant_a"]], outcome),
                             "observed_b": number(lookup[case["participant_b"]], outcome),
                             "model_smearing_mean_a": float(raw_predictions(f1, xa)),
                             "model_smearing_mean_b": float(raw_predictions(f1, xb)),
                             "conditional_mean_difference_a_minus_b": float(raw_predictions(f1, xa) - raw_predictions(f1, xb)),
                             **log_ratio_intervals(f1, xa, xb)})
    boot = bootstrap_analysis(y, x0, x1, ids, replicates, seed, contrasts, progress)
    for case in usable_cases:
        if case["status"] != "model_available":
            continue
        j = case.pop("contrast_index")
        samples = boot["case_differences"][:, j] if boot["valid"] else []
        ci90 = percentile_interval(samples, .90)
        case.update({"conditional_mean_difference_bootstrap_ci90": ci90,
                     "conditional_mean_difference_bootstrap_ci95": percentile_interval(samples, .95),
                     "minimum_symmetric_additive_containment_bound": containment_frontier(ci90) if ci90 else None,
                     "frontier_unit": {"contact_ms": "ms", "pressure_peak_N": "N", "effective_area_cm2": "cm2"}.get(outcome, outcome),
                     "frontier_is_not_a_substantive_equivalence_threshold": True,
                     "mean_difference_assumptions": "global Duan residual distribution transport; fixed observed predictor profiles; does not include predictor measurement error"})
    metric_intervals = {key: percentile_interval([r[key] for r in boot["metrics"]]) for key in cv["metrics"]}
    d0 = diagnostics(f0, x0, controls, protocol["minimum_main_participants"], protocol["maximum_standardized_design_condition_number"])
    d1 = diagnostics(f1, x1, terms, protocol["minimum_main_participants"], protocol["maximum_standardized_design_condition_number"])
    influence = []
    for i, pid in enumerate(ids):
        keep = np.arange(len(ids)) != i
        try:
            dropped = fit_ols(x1[keep], np.log(y[keep]))
            dropped_cv = loso(y[keep], x0[keep], x1[keep], [p for j, p in enumerate(ids) if j != i])
            flagged_terms = [term for j, term in enumerate(["intercept"] + terms)
                             if j and f1.beta[j] * dropped.beta[j] < 0 and abs(dropped.beta[j]) > abs(f1.beta[j])]
            original_delta = cv["metrics"]["delta_mae_baseline_minus_augmented"]
            new_delta = dropped_cv["metrics"]["delta_mae_baseline_minus_augmented"]
            influence.append({"omitted_id": pid, "augmented_coefficients": dropped.beta.tolist(),
                              "terms_reversed_and_larger_magnitude": flagged_terms,
                              "refitted_loso_delta_mae": new_delta,
                              "positive_improvement_lost_when_omitted": original_delta > 0 and new_delta <= 0})
        except (NumericalFailure, np.linalg.LinAlgError) as exc:
            influence.append({"omitted_id": pid, "reason": str(exc), "status": "not_estimable"})
    warnings = []
    if boot["valid"] < replicates:
        warnings.append("Some originally drawn bootstrap samples were numerically non-estimable; not redrawn or silently replaced")
    if boot["valid"] < .95 * replicates:
        warnings.append("More than 5% bootstrap draws failed; percentile interval reliability is limited")
    if any(r.get("terms_reversed_and_larger_magnitude") or r.get("positive_improvement_lost_when_omitted") for r in influence):
        warnings.append("Prespecified influential-participant criterion triggered; do not describe an unqualified stable effect")
    return {**result, "status": "estimated", "baseline_diagnostics": d0, "augmented_diagnostics": d1,
            "baseline_coefficients": coefficient_rows(f0, controls, boot["coefficients_baseline"]),
            "augmented_coefficients": coefficient_rows(f1, terms, boot["coefficients_augmented"]),
            "cv_metrics": cv["metrics"], "cv_metric_bootstrap_ci95": metric_intervals,
            "cv_predictions": cv["predictions"], "case_comparisons": usable_cases,
            "bootstrap": {**{k: boot[k] for k in ("requested", "valid", "failures")},
                          "distinct_participant_counts": boot["bootstrap_distinct_participants"],
                          "distinct_participant_mean": float(np.mean(boot["bootstrap_distinct_participants"])),
                          "cv_interval_label": "approximate participant-bootstrap sensitivity interval; nominal 95%, coverage not established; resampling reduces distinct training participants"},
            "influence": influence, "warnings": warnings,
            "residuals": [{"participant_id": pid, "fitted_log": float(f1.fitted[i]), "residual_log": float(f1.residual[i]),
                           "fitted_smearing_mean": float(raw_predictions(f1, x1[i])), "leverage": float(f1.leverage[i])}
                          for i, pid in enumerate(ids)]}


def association_analysis(records, name, outcome, terms, logged, replicates, seed, protocol):
    included, x, y, excluded = select_complete(records, terms, outcome, logged)
    result = {"analysis": name, "outcome": outcome, "terms": terms, "outcome_logged": logged,
              "n": len(included), "input_n": len(records), "excluded": excluded, "secondary_or_exploratory": True}
    response = np.log(y) if logged else y
    try:
        fit = fit_ols(x, response)
    except (NumericalFailure, np.linalg.LinAlgError) as exc:
        return {**result, "status": "numerically_not_estimable", "reason": str(exc)}
    rng = np.random.default_rng(seed)
    samples, failures = [], 0
    for _ in range(replicates):
        draw = rng.integers(len(y), size=len(y))
        try:
            samples.append(fit_ols(x[draw], response[draw], inference=False).beta)
        except (NumericalFailure, np.linalg.LinAlgError):
            failures += 1
    return {**result, "status": "estimated", "diagnostics": diagnostics(fit, x, terms, 20, protocol["maximum_standardized_design_condition_number"]),
            "coefficients": coefficient_rows(fit, terms, np.asarray(samples), logged),
            "bootstrap": {"requested": replicates, "valid": len(samples), "failed": failures}}


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def write_json(path: Path, value):
    path.write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load_paper_protocol():
    return json.loads(files("scm_strategy").joinpath("protocols/paper_v1.json").read_text())


def _repeat_statistics(groups):
    arrays = [np.asarray(g, dtype=float) for g in groups]
    if len(arrays) < 2 or any(len(g) < 2 or not np.isfinite(g).all() for g in arrays):
        raise NumericalFailure("need_at_least_two_complete_repeat_groups")
    ss = sum(float(np.square(g-g.mean()).sum()) for g in arrays)
    sw = math.sqrt(ss / sum(len(g)-1 for g in arrays))
    balanced = math.sqrt(float(np.mean([g.var(ddof=1) for g in arrays])))
    delta = np.array([g[-1]-g[0] for g in arrays])
    bias = float(delta.mean()); sd = float(delta.std(ddof=1))
    return {"pooled_within_sd_cm2": sw, "participant_balanced_within_sd_cm2": balanced,
            "first_last_bias_cm2": bias, "first_last_difference_sd_cm2": sd,
            "first_last_loa_lower_cm2": bias-1.96*sd, "first_last_loa_upper_cm2": bias+1.96*sd,
            "repeatability_coefficient_cm2": 1.96*math.sqrt(2)*sw,
            "mean_absolute_first_last_difference_cm2": float(np.abs(delta).mean()),
            "median_absolute_first_last_difference_cm2": float(np.median(np.abs(delta)))}


def _bootstrap_repeats(groups, seed, replicates):
    point = _repeat_statistics(groups)
    rng = np.random.default_rng(seed)
    draws = rng.integers(len(groups), size=(replicates, len(groups)))
    samples = {key: [] for key in point}
    for draw in draws:
        result = _repeat_statistics([groups[i] for i in draw])
        for key, value in result.items(): samples[key].append(value)
    return {key: {"estimate": value, "bootstrap_ci95": np.quantile(samples[key], [.025,.975], method="linear").tolist()} for key, value in point.items()}


def measurement_summary(bundle, protocol, replicates):
    primary_ids = {r["participant_id"] for r in bundle["primary"]}
    extension_ids = {r["participant_id"] for r in bundle["extension"]}
    by_person = {}
    for row in bundle["pressure_repeats"]: by_person.setdefault(row["participant_id"], []).append(row)
    groups = {}; details = []
    for pid in sorted(extension_ids):
        rows = sorted(by_person.get(pid, []), key=lambda r: (r["trial_index"], r["trial_id"]))
        reason = []
        values = np.array([number(r,"effective_area_cm2") for r in rows])
        speeds = np.array([number(r,"speed_kmh") for r in rows])
        if len(rows)<2: reason.append("only_one_or_no_repeat_trial")
        if any(not r["available"] for r in rows): reason.append("unavailable_repeat_trial")
        if not np.isfinite(values).all() or not np.isfinite(speeds).all(): reason.append("missing_repeat_value")
        speed_range = float(np.ptp(speeds)) if len(speeds) and np.isfinite(speeds).all() else None
        if speed_range is not None and speed_range > protocol["repeat_speed_tolerance_kmh"]+1e-12: reason.append("all_repeat_speed_range_exceeded")
        if not reason: groups[pid] = values
        details.append({"participant_id":pid,"in_primary":pid in primary_ids,"n_trials":len(rows),
                        "speed_range_kmh":speed_range,"repeatability_eligible":not reason,"exclusion_reason":";".join(reason)})
    result = {"version":"scm-strategy.paper-measurement/1","seed":protocol["seed"],"bootstrap_replicates":replicates,"unit":"cm2",
              "measurement_scope":"same-session near-speed standardized repeat features; not biological validity or cross-day reliability",
              "difference_convention":"last minus first by trial_index, then trial_id",
              "eligibility":details}
    for key, ids, seed in [("full_pressure_cohort",extension_ids,protocol["seed"]),
                            ("primary_motion_cohort",primary_ids,protocol["seed"]+1)]:
        selected = [value for pid,value in groups.items() if pid in ids]
        cohort = {"cohort_n":len(ids),"repeatable_n":len(selected),"repeat_trial_n":sum(len(v) for v in selected)}
        try: cohort.update(status="estimated",statistics=_bootstrap_repeats(selected,seed,replicates))
        except NumericalFailure as exc: cohort.update(status="not_estimable",reason=str(exc),statistics={})
        result[key] = cohort
    result["motion_repeats"] = _motion_repeat_description(bundle.get("paired_trials"), protocol)
    result["source_quality_counts"] = bundle["metadata"].get("quality_counts", {})
    result["source_quality_counts_are_producer_supplied"] = True
    return result


def _motion_repeat_description(rows, protocol):
    if rows is None: return {"status":"not_available","reason":"optional paired_trials table not supplied","n_participants":0,"n_pairs":0}
    grouped = {}
    for row in rows: grouped.setdefault(row["participant_id"],[]).append(row)
    detail=[]; excluded=[]
    for pid in sorted(grouped):
        group=sorted(grouped[pid],key=lambda r:(r["trial_index"],r["trial_id"]))
        if len(group)<2: continue
        speeds=np.array([number(r,"speed_kmh") for r in group])
        if not np.isfinite(speeds).all() or np.ptp(speeds)>protocol["repeat_speed_tolerance_kmh"] or any(not r["available"] for r in group):
            excluded.append({"participant_id":pid,"reason":"incomplete_or_noncomparable_motion_repeats"});continue
        row={"participant_id":pid,"n_pairs":len(group)}
        for feature in ["knee_excursion_deg","ankle_excursion_deg"]:
            values=np.array([number(r,feature) for r in group])
            if not np.isfinite(values).all(): break
            row[feature]=float(values[-1]-values[0])
        else: detail.append(row);continue
        excluded.append({"participant_id":pid,"reason":"missing_motion_repeat_feature"})
    result={"status":"descriptive" if detail else "not_estimable","n_participants":len(detail),"n_pairs":sum(r["n_pairs"] for r in detail),
            "scope":"Descriptive within-session repeat differences; no population reliability claim","exclusions":excluded}
    for feature in ["knee_excursion_deg","ankle_excursion_deg"]:
        values=np.array([row[feature] for row in detail])
        result[feature]={"signed_difference_mean_deg":float(values.mean()) if len(values) else None,
                         "signed_difference_range_deg":[float(values.min()),float(values.max())] if len(values) else None,
                         "absolute_difference_median_deg":float(np.median(np.abs(values))) if len(values) else None,
                         "absolute_difference_range_deg":[float(np.abs(values).min()),float(np.abs(values).max())] if len(values) else None}
    return result


def cohort_selection_summary(bundle):
    counts={"primary_n":len(bundle["primary"]),"extension_n":len(bundle["extension"]),
            "paired_trial_rows":len(bundle.get("paired_trials",[])),"pressure_repeat_rows":len(bundle["pressure_repeats"]),
            "primary_qc_counts":dict(Counter(r["qc_status"] for r in bundle["primary"]))}
    common={"counts":counts,"producer_supplied_cohort_counts":bundle["metadata"].get("cohort_counts",{}),
            "producer_supplied_quality_counts":bundle["metadata"].get("quality_counts",{}),"source_counts_not_reconstructed":True}
    if "cohort_profiles" not in bundle:
        return {**common,"status":"not_available","reason":"cohort_profiles missing; index-trial speed is not substituted for participant median speed","variables":[],"categorical":[]}
    primary={r["participant_id"] for r in bundle["primary"]}; profiles=bundle["cohort_profiles"]
    def describe(values):
        a=np.array([v for v in values if v is not None],dtype=float)
        return {"n":len(a),"mean":float(a.mean()) if len(a) else None,"sd":float(a.std(ddof=1)) if len(a)>1 else None,
                "median":float(np.median(a)) if len(a) else None,"min":float(a.min()) if len(a) else None,"max":float(a.max()) if len(a) else None}
    def summary(key, category=None):
        def values(rows):
            return [float(r[key]==category) if category else number(r,key) for r in rows if r.get(key) is not None and (not category or r[key]!="unknown")]
        selected=[r for r in profiles if r["participant_id"] in primary];excluded=[r for r in profiles if r["participant_id"] not in primary]
        out={"variable":key,"kind":"category_indicator" if category else "continuous","level":category}
        groups={name:describe(values(rows)) for name,rows in [("full",profiles),("selected",selected),("not_selected",excluded)]}
        for name,group in groups.items():out.update({name+"_"+k:v for k,v in group.items()})
        a,b=groups["selected"],groups["not_selected"]
        den=math.sqrt((a["mean"]*(1-a["mean"])+b["mean"]*(1-b["mean"]))/2) if category and a["n"] and b["n"] else math.sqrt((a["sd"]**2+b["sd"]**2)/2) if a["sd"] is not None and b["sd"] is not None else None
        out["smd_selected_vs_not_selected"]=(a["mean"]-b["mean"])/den if den else None
        return out
    numbers=[key for key in profiles[0] if key not in {"participant_id","recorded_sex"}] if profiles else []
    profiles_by_id={r["participant_id"]:r for r in profiles}
    observed=[]
    for field in ["age_years","height_cm","weight_kg","bmi","navicular_ratio","speed_kmh","knee_excursion_deg","ankle_excursion_deg","contact_ms","pressure_peak_N","effective_area_cm2"]:
        row={"variable":field,"scope":"primary paired index versus pressure extension index; missing extension motion is not imputed"}
        for scope,records in [("primary",bundle["primary"]),("not_selected",[r for r in bundle["extension"] if r["participant_id"] not in primary]),("extension",bundle["extension"])]:
            vals=[r.get(field,profiles_by_id[r["participant_id"]].get(field)) for r in records]
            row[scope]=describe(vals)
        observed.append(row)
    return {**common,"status":"estimated","source_scope":"producer supplied participant-level cohort profiles; median speed across eligible pressure trials, not index-trial speed",
            "full_extension_n":len(profiles),"primary_n":len(primary),"not_selected_n":len(profiles)-len(primary),
            "variables":[summary(key) for key in numbers],"categorical":[summary("recorded_sex",category) for category in ["F","M"]],
            "observed_descriptives":observed}


def _inspect_design(x):
    scale=x[:,1:].std(axis=0,ddof=0);constant=scale<=np.finfo(float).eps
    z=np.column_stack([np.ones(len(x)),(x[:,1:]-x[:,1:].mean(axis=0))/np.where(constant,1,scale)])
    singular=np.linalg.svd(z,compute_uv=False)
    rank=int(np.sum(singular>singular[0]*max(z.shape)*np.finfo(float).eps))
    condition=float(singular[0]/singular[-1]) if singular[-1]>0 else float("inf")
    return condition,rank,int(np.count_nonzero(constant))


def _design_statistics(conditions,ranks,constants,p,threshold):
    a=np.asarray(conditions);finite=a[np.isfinite(a)]
    return {"matrix_count":len(a),"parameters":p,"rank_min":min(ranks),"rank_deficient_count":sum(r<p for r in ranks),
            "constant_predictor_matrix_count":sum(c>0 for c in constants),"condition_infinite_count":int(np.count_nonzero(~np.isfinite(a))),
            "condition_above_frozen_threshold_count":int(np.count_nonzero(a>threshold)),"threshold":threshold,
            "finite_condition_quantiles":dict(zip(["min","p50","p90","p95","p99","max"],np.quantile(finite,[0,.5,.9,.95,.99,1],method="linear").tolist())) if len(finite) else {},
            "maximum_condition_number":float(a.max()) if np.isfinite(a).all() else "infinity"}


def numerical_design_audit(records, terms, protocol, replicates):
    x=design(records,terms);n,p=x.shape
    if n<=p: return {"status":"not_estimable","reason":"insufficient design rows"}
    f=_inspect_design(x);oc=[];orr=[];ok=[]
    for held in range(n):
        c,r,k=_inspect_design(x[np.arange(n)!=held]);oc.append(c);orr.append(r);ok.append(k)
    bc=[];br=[];bk=[];unique=[];train_unique=[];train_rows=[];rng=np.random.default_rng(protocol["seed"])
    for _ in range(replicates):
        counts=np.bincount(rng.integers(n,size=n),minlength=n);active=np.flatnonzero(counts);unique.append(len(active))
        for held in active:
            indices=np.repeat(np.arange(n),counts*(np.arange(n)!=held))
            c,r,k=_inspect_design(x[indices]);bc.append(c);br.append(r);bk.append(k)
            train_unique.append(len(active)-1);train_rows.append(len(indices))
    return {"status":"audited","n_source_participants":n,"terms":terms,
            "full_sample":{"condition_number":f[0],"rank":f[1],"constant_predictors":f[2]},
            "original_loso_training":_design_statistics(oc,orr,ok,p,protocol["maximum_standardized_design_condition_number"]),
            "bootstrap_loso_training":_design_statistics(bc,br,bk,p,protocol["maximum_standardized_design_condition_number"]),
            "bootstrap_distinct_participant_histogram":dict(sorted(Counter(unique).items())),
            "minimum_bootstrap_distinct_participants":min(unique),"minimum_bootstrap_training_distinct_participants":min(train_unique),
            "bootstrap_training_rows_min_max":[min(train_rows),max(train_rows)]}


def run_paper_study(bundle, *, bootstrap_replicates=None, progress=None, include_design_audit=True):
    """Run 17 prediction specifications plus 5 associations, all with one frozen seed.

    Smaller bootstrap counts are permitted only for explicitly synthetic input,
    and are labeled verification runs rather than full protocol reproductions.
    """
    if isinstance(bundle,(str,Path)):bundle=read_paper_bundle(bundle)
    normalized=validate_paper_bundle({k:v for k,v in bundle.items() if k!="validation"})
    input_digest=hashlib.sha256(json.dumps({k:v for k,v in normalized.items() if k!="validation"},sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    protocol=load_paper_protocol();reps=protocol["bootstrap_replicates"] if bootstrap_replicates is None else bootstrap_replicates
    if isinstance(reps,bool) or not isinstance(reps,int) or not 1<=reps<=20000:raise ValueError("invalid_paper_bootstrap_count")
    if normalized["metadata"]["dataset_kind"]!="synthetic" and reps!=protocol["bootstrap_replicates"]:raise ValueError("empirical_paper_study_requires_frozen_bootstrap_count")
    primary=normalized["primary"];extension=normalized["extension"];sens=normalized["sensitivities"]
    cases,case_meta=select_cases(primary,protocol["case_speed_caliper_kmh"],protocol["case_max_pairs"])
    selected_ids={c[k] for c in cases for k in ("participant_a","participant_b")}
    jobs=[("primary",primary,False),("PASS_only",[r for r in primary if r["qc_status"]=="PASS"],False)]
    jobs += [(spec,[r for r in sens if r["spec"]==spec],False) for spec in protocol["sensitivity_table_specs"]]
    jobs += [("primary_height_replaced_by_age",primary,True)]
    analyses={};summaries=[];audit_jobs=[]
    for name,records,use_age in jobs:
        outcomes=["contact_ms"] if use_age else ["contact_ms","pressure_peak_N"]
        for outcome in outcomes:
            controls=["log_speed_kmh","age_years_per10" if use_age else "log_height_cm" if outcome=="contact_ms" else "log_weight_kg"]
            label=name+"__"+outcome
            callback=(lambda done,total,label=label:progress(label,done,total)) if progress else None
            result=prediction_analysis(records,label,outcome,controls,protocol,reps,protocol["seed"],cases if name=="primary" else None,callback)
            analyses[label]=result
            summaries.append({k:result.get(k) for k in ("analysis","outcome","n","status","warnings")})
            if result["status"]=="estimated":
                summaries[-1].update(metrics=result["cv_metrics"],intervals=result["cv_metric_bootstrap_ci95"],interpretation_gate_passed=result["augmented_diagnostics"]["interpretation_gate_passed"])
                lookup={r["participant_id"]:r for r in records};included=[lookup[i] for i in result["included_ids"]]
                for model,terms in [("baseline",controls),("augmented",controls+protocol["strategy_terms"])]:audit_jobs.append((label,model,included,terms))
    specs=[(primary,"body_to_knee","knee_excursion_deg",["log_speed_kmh","log_height_cm","navicular_ratio_per001"],False),
           (primary,"body_to_ankle","ankle_excursion_deg",["log_speed_kmh","log_height_cm","navicular_ratio_per001"],False),
           (extension,"extension_contact","contact_ms",["log_speed_kmh","log_height_cm","log_weight_kg","navicular_ratio_per001"],True),
           (extension,"extension_peak","pressure_peak_N",["log_speed_kmh","log_height_cm","log_weight_kg","navicular_ratio_per001"],True),
           (extension,"extension_area","effective_area_cm2",["log_speed_kmh","log_weight_kg","log_foot_size_proxy_cm2","navicular_ratio_per001"],True)]
    for records,label,outcome,terms,logged in specs:
        result=association_analysis(records,label,outcome,terms,logged,reps,protocol["seed"],protocol);analyses[label]=result
        summaries.append({k:result.get(k) for k in ("analysis","outcome","n","status")})
    audits=[]
    if include_design_audit:
        for label,model,records,terms in audit_jobs:
            if progress:progress("design:"+label+":"+model,0,reps)
            audits.append({"analysis":label,"model":model,**numerical_design_audit(records,terms,protocol,reps)})
    return json_safe({"schema_version":"scm-strategy.paper-study/1","protocol_id":PROTOCOL_ID,
            "dataset_kind":"private_empirical","input_dataset_kind":normalized["metadata"]["dataset_kind"],"exportable":False,
            "input_bundle_sha256":input_digest,
            "configuration":{**protocol,"executed_bootstrap_replicates":reps,"full_frozen_draw_count":reps==protocol["bootstrap_replicates"]},
            "analyses":analyses,"summary":summaries,"case_selection":{"cases":cases,"metadata":case_meta,"observed_profiles":[r for r in primary if r["participant_id"] in selected_ids]},
            "measurement_summary":measurement_summary(normalized,protocol,reps),"cohort_selection_summary":cohort_selection_summary(normalized),
            "numerical_design":{"status":"audited" if include_design_audit else "not_run","models":audits},
            "input_validation":normalized["validation"],"interpretation":"Standardized features to paper statistics; source QC, raw decoding, causal and clinical validity are not reconstructed."})


def save_paper_study(result, directory):
    """Private local output only; deliberately incompatible with export-web."""
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    write_json(root/"paper_study.json",result)
    write_json(root/"analysis_summary.json",result["summary"])
    for name,value in result["analyses"].items():write_json(root/(name+".json"),value)
    for key,filename in [("case_selection","case_selection.json"),("measurement_summary","measurement_summary.json"),
                         ("cohort_selection_summary","cohort_selection_summary.json"),("numerical_design","numerical_design_audit.json")]:write_json(root/filename,result[key])
    rows=[]
    for name,analysis in result["analyses"].items():
        for model,key in [("baseline","baseline_coefficients"),("augmented","augmented_coefficients"),("secondary","coefficients")]:
            rows.extend({"analysis":name,"model":model,**c} for c in analysis.get(key,[]))
    if rows:
        import csv
        fields=list(dict.fromkeys(k for row in rows for k in row))
        with (root/"coefficients.csv").open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fields);writer.writeheader();writer.writerows(rows)
    write_json(root/"run_manifest.json",{"schema_version":"scm-strategy.paper-run/1","dataset_kind":"private_empirical",
               "input_dataset_kind":result["input_dataset_kind"],"analysis_mode":"paper-study","protocol_id":PROTOCOL_ID,
               "input_bundle_sha256":result["input_bundle_sha256"],
               "exportable":False,"privacy":"Local private output including participant contrasts; export-web is not a paper-run exporter."})
    return root
