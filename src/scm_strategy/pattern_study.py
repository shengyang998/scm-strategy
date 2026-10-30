# SPDX-License-Identifier: BSD-3-Clause
"""The fixed exploratory pattern study from explicit numeric inputs only."""
from __future__ import annotations

from collections import defaultdict
import csv
from importlib.resources import files
import json
import math
from pathlib import Path

import numpy as np

from . import __version__
from .pattern_bundle import validate_pattern_bundle
from . import pattern_math as pm


def configuration():
    return json.loads(files("scm_strategy.protocols").joinpath("pattern_v1.json").read_text())


def _finite(value):
    return value is not None and bool(np.isfinite(value))


def _safe(value):
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_safe(v) for v in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    return value


def _public_keys(value):
    if isinstance(value, dict):
        return {("participant_id" if k == "anonymized_id" else k): _public_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_public_keys(v) for v in value]
    return value


def _mean_pair(row, field):
    values = [row.get(field + "_left"), row.get(field + "_right")]
    return float(np.mean(values)) if all(_finite(v) for v in values) else None


def _standardize(bundle):
    body = {r["participant_id"]: dict(r, anonymized_id=r["participant_id"]) for r in bundle["participants"]}
    motion = bundle["motion"]
    traces = {str(pid): motion["values_deg"][motion["row_offsets"][i]:motion["row_offsets"][i + 1]] for i, pid in enumerate(motion["pair_ids"])}
    pairs = []
    for source in sorted(bundle["paired_trials"], key=lambda r: r["analysis_order"]):
        r = {**body[source["participant_id"]], **source, "anonymized_id": source["participant_id"], "zebris_trial_id": source["pair_id"],
             "raw_qc_status": source["qc_status"], "window_duration_s": source["window_end_s"] - source["window_start_s"]}
        for field in ("pressure_peak_N", "effective_area_cm2"):
            r[field] = _mean_pair(source, field)
        if r["motion_status"] == "valid":
            excursion = np.quantile(traces[r["pair_id"]], .95, axis=0, method="linear") - np.quantile(traces[r["pair_id"]], .05, axis=0, method="linear")
            r["knee_excursion_deg"] = float(np.mean(excursion[[0, 2]]))
            r["ankle_excursion_deg"] = float(np.mean(excursion[[1, 3]]))
        else:
            r["knee_excursion_deg"] = r["ankle_excursion_deg"] = None
        pairs.append(r)
    return body, pairs, traces


def _difference(a, b):
    return a - b if _finite(a) and _finite(b) else None


def _candidates(primary, scales, cfg):
    rows = sorted(primary, key=lambda r: r["anonymized_id"])
    edges = []
    fields = [*cfg["body_fields"], "contact_ms", "pressure_peak_N", "effective_area_cm2", "knee_excursion_deg", "ankle_excursion_deg"]
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            d = {"a": a["anonymized_id"], "b": b["anonymized_id"], "a_pair": a["pair_id"], "b_pair": b["pair_id"],
                 "technical_eligible": pm.technical_eligible(a) and pm.technical_eligible(b),
                 "speed_a_kmh": a["speed_kmh"], "speed_b_kmh": b["speed_kmh"],
                 "speed_difference_kmh": _difference(a["speed_kmh"], b["speed_kmh"])}
            d["speed_abs_difference_kmh"] = abs(d["speed_difference_kmh"]) if d["speed_difference_kmh"] is not None else None
            for field in fields:
                delta = _difference(a[field], b[field])
                d.update({field + "_a": a[field], field + "_b": b[field], field + "_difference": delta,
                          field + "_abs_difference": abs(delta) if delta is not None else None})
            if scales and all(_finite(d[f + "_difference"]) for f in cfg["body_fields"]):
                d["body_distance_full50_sd"] = float(np.linalg.norm([d[f + "_difference"] / scales[f]["sample_sd"] for f in cfg["body_fields"]]))
            else:
                d["body_distance_full50_sd"] = None
            angles = [d[f + "_difference"] for f in ("knee_excursion_deg", "ankle_excursion_deg")]
            d["v1_amplitude_distance_deg"] = float(np.sqrt(np.mean(np.square(angles)))) if all(_finite(v) for v in angles) else None
            edges.append(d)
    graphs = {}
    for caliper in cfg["speed_calipers_kmh"]:
        chosen = [r for r in edges if r["technical_eligible"] and _finite(r["speed_abs_difference_kmh"]) and r["speed_abs_difference_kmh"] <= caliper]
        graph = pm.graph_summary([r["anonymized_id"] for r in primary], chosen)
        matching = pm.body_only_matching(graph, chosen, cfg["maximum_matching_component_size"])
        graphs[str(caliper)] = {**graph, "matching": matching}
    chosen = [r for r in edges if r["technical_eligible"] and _finite(r["speed_abs_difference_kmh"]) and r["speed_abs_difference_kmh"] <= cfg["primary_speed_caliper_kmh"]]
    graph = graphs[str(cfg["primary_speed_caliper_kmh"])]
    matched = {(r["a"], r["b"]) for r in graph["matching"]["pairs"]}
    for r in chosen:
        r["body_only_matching"] = (r["a"], r["b"]) in matched
    return edges, chosen, graphs


def _describe(values):
    values = np.asarray(values, float)
    if not len(values):
        return {"status": "not_estimable", "n": 0}
    q = np.quantile(values, [.25, .5, .75])
    return {"n": len(values), "min": float(values.min()), "q25": q[0], "median": q[1], "q75": q[2], "max": float(values.max()),
            "range": float(np.ptp(values)), "sd": float(values.std(ddof=1)) if len(values) > 1 else None, "iqr": float(q[2] - q[0])}


def _group_pairs(pairs):
    grouped = defaultdict(list)
    for r in pairs:
        grouped[r["anonymized_id"]].append(r)
    return {pid: sorted(g, key=lambda r: (r["replicate_index"], r["pair_id"])) for pid, g in grouped.items()}


def _geometry(primary, pairs, traces, edges, cfg):
    lookup = {r["anonymized_id"]: r["pair_id"] for r in primary}
    repeat_pairs = [(pid, group[0]["pair_id"], group[-1]["pair_id"]) for pid, group in sorted(_group_pairs(pairs).items()) if len(group) > 1]
    candidate_rows, repeat_rows, summaries = [], [], {}
    for factor in cfg["sampling_factors"]:
        summaries[str(factor)] = {}
        for mode in cfg["geometry_modes"]:
            def distance(first, second):
                a, b = traces[first], traces[second]
                if not len(a) or not len(b):
                    return {"status": "not_estimable", "reason": "missing_motion"}
                if mode == "time_mean_centered":
                    a = a - a.mean(axis=0)
                    b = b - b.mean(axis=0)
                try:
                    return {"status": "estimated", **pm.bilateral_chamfer(a[::factor], b[::factor], False)}
                except (ValueError, np.linalg.LinAlgError) as exc:
                    return {"status": "not_estimable", "reason": str(exc)}
            current = [{"a": e["a"], "b": e["b"], "body_only_matching": e["body_only_matching"], "mode": mode, "sampling_factor": factor,
                        **distance(lookup[e["a"]], lookup[e["b"]])} for e in edges]
            own = [{"anonymized_id": pid, "first_pair_id": a, "last_pair_id": b, "mode": mode, "sampling_factor": factor, **distance(a, b)} for pid, a, b in repeat_pairs]
            candidate_rows.extend(current)
            repeat_rows.extend(own)
            good = [r for r in current if r["status"] == "estimated"]
            good_own = [r for r in own if r["status"] == "estimated"]
            maximum = max((r["chamfer_rms_deg"] for r in good_own), default=None)
            summaries[str(factor)][mode] = {"all_candidates": _describe([r["chamfer_rms_deg"] for r in good]),
                "body_only_matching": _describe([r["chamfer_rms_deg"] for r in good if r["body_only_matching"]]),
                "within_person_repeats": _describe([r["chamfer_rms_deg"] for r in good_own]),
                "failed_candidate_count": len(current) - len(good), "failed_repeat_count": len(own) - len(good_own),
                "n_above_observed_repeat_max": sum(r["chamfer_rms_deg"] > maximum for r in good) if maximum is not None else None}
    return {"candidate_rows": candidate_rows, "repeat_rows": repeat_rows, "summary": summaries}


def _pressure_repeats(bundle, cfg):
    records = []
    for source in bundle["pressure_repeats"]:
        row = dict(source, anonymized_id=source["participant_id"], zebris_trial_id=source["trial_id"])
        for field in ("pressure_peak_N", "effective_area_cm2"):
            row[field] = _mean_pair(source, field)
        records.append(row)
    return pm.pressure_noise_reference(records, cfg)


def _static_analysis(bundle, body, cfg):
    outcomes = {"area_log_lr": "effective_area_cm2", "peak_log_lr": "pressure_peak_N"}
    repeated, repeat_summary, details = {}, {}, []
    for outcome, field in outcomes.items():
        repeated[outcome] = {}
        for pid in sorted(body):
            trials = sorted([r for r in bundle["pressure_repeats"] if r["participant_id"] == pid], key=lambda r: (r["replicate_index"], r["trial_id"]))
            values = np.array([pm.log_ratio(pm.value(r, field + "_left"), pm.value(r, field + "_right")) for r in trials])
            speeds = np.array([pm.value(r, "speed_kmh") for r in trials])
            eligible = len(values) >= 2 and np.isfinite(values).all() and np.isfinite(speeds).all() and np.ptp(speeds) <= cfg["repeat_speed_range_kmh"] + 1e-12
            row = {"participant_id": pid, "outcome": outcome, "n_trials": len(values), "eligible": bool(eligible), "speed_range_kmh": float(np.ptp(speeds)) if len(speeds) else None}
            if eligible:
                repeated[outcome][pid] = values
                row.update(first=values[0], last=values[-1], mean=values.mean(), within_sd=values.std(ddof=1), difference=values[-1] - values[0], same_nonzero_sign=bool(values[0] * values[-1] > 0))
            else:
                row["reason"] = "insufficient_repeats_or_missing_or_speed_range"
            details.append(row)
        groups = list(repeated[outcome].values())
        repeat_summary[outcome] = {"n_participants": len(groups), "n_trials": sum(map(len, groups)),
            "statistics": pm.bootstrap_repeat(groups, cfg["bootstrap_replicates"], cfg["seed"]) if len(groups) >= 2 else {"status": "not_estimable", "reason": "insufficient_repeat_groups"},
            "sign_by_magnitude": pm.sign_summary(groups, cfg["sign_magnitude_thresholds_log_units"])}
    log_speeds = [math.log(r["speed_kmh"]) for r in bundle["pressure_index"] if _finite(r["speed_kmh"])]
    mean_log_speed = float(np.mean(log_speeds)) if len(log_speeds) == len(body) else float("nan")
    rows = []
    for index in bundle["pressure_index"]:
        b = body[index["participant_id"]]
        side = {k: pm.value(b, k) for k in b if k.endswith("_mm")}
        d = (side["navicular_height_left_mm"] / side["foot_length_left_mm"] - side["navicular_height_right_mm"] / side["foot_length_right_mm"]) / .01
        row = {"anonymized_id": index["participant_id"], "dRNH_per001": d,
            "centered_log_speed": math.log(index["speed_kmh"]) - mean_log_speed if _finite(index["speed_kmh"]) else float("nan"),
            "static_area_log_lr": pm.log_ratio(side["foot_length_left_mm"] * side["forefoot_width_left_mm"], side["foot_length_right_mm"] * side["forefoot_width_right_mm"])}
        for outcome, field in outcomes.items():
            row[outcome] = pm.log_ratio(pm.value(index, field + "_left"), pm.value(index, field + "_right"))
            values = repeated[outcome].get(index["participant_id"])
            row[outcome + "_repeat_mean"] = float(values.mean()) if values is not None else row[outcome]
        rows.append(row)
    models, coefficients, loo = [], [], []
    for outcome in outcomes:
        for spec in cfg["static_specs"]:
            result, coef, inf = pm.association(rows, outcome, spec, cfg)
            models.append(result)
            coefficients.extend(coef)
            loo.extend(inf)
    error_curves = []
    for result in models:
        if result["spec"] == "primary" and result["status"] == "estimated":
            c = result["coefficients"][1]
            for reliability in cfg["assumed_classical_exposure_reliability"]:
                error_curves.append({"outcome": result["outcome"], "assumed_reliability_lambda": reliability,
                    "conditional_beta": c["estimate"] / reliability, "conditional_hc3_low": c["hc3_ci95_low"] / reliability,
                    "conditional_hc3_high": c["hc3_ci95_high"] / reliability, "not_empirical_correction": True})
    return {"models": models, "coefficients": coefficients, "loo": loo, "index_rows": rows, "repeat_summary": repeat_summary, "repeat_details": details, "classical_error_scenarios": error_curves}


def _within_motion(trace, centered):
    if not len(trace):
        return {"status": "not_estimable", "reason": "missing_motion"}
    left, right = trace[:, :2].copy(), trace[:, 2:].copy()
    if centered:
        left -= left.mean(axis=0)
        right -= right.mean(axis=0)
    c = pm.chamfer_components(left, right)
    return {"status": "estimated", "D": float(np.sqrt(c.mean())), "knee_component": float(np.sqrt(c[0])), "ankle_component": float(np.sqrt(c[1]))}


def _motion_repeat(groups):
    if len(groups) < 2:
        return {"status": "not_estimable", "n_people": len(groups)}
    delta = np.array([v[-1] - v[0] for v in groups])
    return {"n_people": len(groups), "n_recordings": sum(len(v) for v in groups),
        "pooled_within_sd": float(np.sqrt(sum(float(np.square(v - np.mean(v)).sum()) for v in groups) / sum(len(v) - 1 for v in groups))),
        "first_last_bias": float(delta.mean()), "first_last_difference_sd": float(delta.std(ddof=1)), "median_absolute_change": float(np.median(abs(delta))),
        "max_absolute_change": float(np.max(abs(delta))), "minimum_change": float(delta.min()), "maximum_change": float(delta.max())}


def _motion_analysis(pairs, traces, cfg):
    features = []
    for row in pairs:
        r = {k: row[k] for k in ("pair_id", "anonymized_id", "replicate_index", "is_primary", "primary_order", "analysis_order", "speed_kmh")}
        for mode in ("centered", "raw"):
            d = _within_motion(traces[row["pair_id"]], mode == "centered")
            for field, target in (("D", "D_LR_deg"), ("knee_component", "knee_component_deg"), ("ankle_component", "ankle_component_deg")):
                r[mode + "_" + target] = d.get(field, float("nan"))
        dl = pm.value(row, "navicular_height_left_mm") / pm.value(row, "foot_length_left_mm")
        dr = pm.value(row, "navicular_height_right_mm") / pm.value(row, "foot_length_right_mm")
        r["abs_dRNH_per_001"] = abs(dl - dr) / .01
        for short, field in (("area", "effective_area_cm2"), ("peak", "pressure_peak_N")):
            signed = pm.log_ratio(pm.value(row, field + "_left"), pm.value(row, field + "_right"))
            r["signed_" + short + "_log_lr"] = signed
            r["abs_" + short + "_log_lr"] = abs(signed)
        features.append(r)
    primary = [r for r in features if r["is_primary"]]
    speed_mean = float(np.mean([pm.value(r, "speed_kmh") for r in primary]))
    for r in features:
        r["speed_centered_kmh"] = pm.value(r, "speed_kmh") - speed_mean
    rng = np.random.default_rng(cfg["seed"])
    draws = rng.integers(0, len(primary), size=(cfg["bootstrap_replicates"], len(primary)))
    definitions = {"primary": ("centered_D_LR_deg", "speed_centered_kmh"), "raw_motion": ("raw_D_LR_deg", "speed_centered_kmh"), "static_instead_of_speed": ("centered_D_LR_deg", "abs_dRNH_per_001")}
    models, coefficients, loo, arrays = {}, [], [], {"motion_bootstrap_indices": draws}
    for outcome in ("abs_area_log_lr", "abs_peak_log_lr"):
        y = np.array([r[outcome] for r in primary])
        for spec, (xkey, zkey) in definitions.items():
            key = outcome + "__" + spec
            x, z = (np.array([r[k] for r in primary]) for k in (xkey, zkey))
            try:
                fitted = pm.fit_model(x, y, z)
            except (ValueError, np.linalg.LinAlgError) as exc:
                models[key] = {"status": "not_estimable", "reason": str(exc), "n_people": len(primary), "excluded": [], "missing_person_ids": [r["anonymized_id"] for i, r in enumerate(primary) if not np.isfinite([x[i], y[i], z[i]]).all()]}
                continue
            boot = np.full((len(draws), 3), np.nan)
            failures = {}
            for i, draw in enumerate(draws):
                try:
                    boot[i] = pm.fit_model(x[draw], y[draw], z[draw], False)["beta"]
                except (ValueError, np.linalg.LinAlgError) as exc:
                    failures[str(exc)] = failures.get(str(exc), 0) + 1
            valid = np.isfinite(boot).all(axis=1)
            ci = np.quantile(boot[valid], [.025, .975], axis=0).T if valid.any() else np.full((3, 2), np.nan)
            arrays["motion_beta_" + key] = boot
            model = {"status": "estimated", "outcome": outcome, "spec": spec, "n_people": len(primary), "df": fitted["df"], "terms": ["intercept", xkey, zkey],
                "beta": fitted["beta"], "hc3_se": fitted["hc3_se"], "hc3_ci95": fitted["hc3_ci95"], "bootstrap_ci95": ci,
                "bootstrap_valid": int(valid.sum()), "bootstrap_failures": failures, "standardized_condition_number": fitted["standardized_condition_number"],
                "predictor_correlation": float(np.corrcoef(x, z)[0, 1]), "max_leverage": float(fitted["leverage"].max())}
            slopes = []
            for i, row in enumerate(primary):
                keep = np.arange(len(primary)) != i
                try:
                    one = pm.fit_model(x[keep], y[keep], z[keep])
                    slope = float(one["beta"][1]); slopes.append(slope)
                    loo.append({"outcome": outcome, "spec": spec, "left_out_id": row["anonymized_id"], "D_slope": slope,
                        "slope_change": slope - fitted["beta"][1], "sign_change_vs_full": bool(np.sign(slope) != np.sign(fitted["beta"][1])), "standardized_condition_number": one["standardized_condition_number"]})
                except (ValueError, np.linalg.LinAlgError) as exc:
                    loo.append({"outcome": outcome, "spec": spec, "left_out_id": row["anonymized_id"], "status": "not_estimable", "reason": str(exc)})
            model["leave_one_D_slope"] = {"min": min(slopes) if slopes else None, "max": max(slopes) if slopes else None, "sign_changes": sum(np.sign(v) != np.sign(fitted["beta"][1]) for v in slopes), "valid": len(slopes)}
            models[key] = model
            for j, term in enumerate(model["terms"]):
                coefficients.append({"outcome": outcome, "spec": spec, "term": term, "n_people": len(primary), "estimate": fitted["beta"][j], "hc3_se": fitted["hc3_se"][j],
                    "hc3_lower": fitted["hc3_ci95"][j, 0], "hc3_upper": fitted["hc3_ci95"][j, 1], "bootstrap_lower": ci[j, 0], "bootstrap_upper": ci[j, 1]})
    groups = [g for g in _group_pairs(features).values() if len(g) > 1]
    repeated = {}
    for field in ("centered_D_LR_deg", "raw_D_LR_deg", "abs_area_log_lr", "abs_peak_log_lr", "signed_area_log_lr", "signed_peak_log_lr"):
        good = [np.array([r[field] for r in g]) for g in groups if all(_finite(r[field]) for r in g)]
        repeated[field] = {**_motion_repeat(good), "excluded_repeat_groups": len(groups) - len(good)}
    distributions = {field: _describe([r[field] for r in primary if _finite(r[field])]) for field in
                     ("centered_D_LR_deg", "raw_D_LR_deg", "abs_area_log_lr", "abs_peak_log_lr", "speed_kmh", "abs_dRNH_per_001")}
    comparability = {}
    for mode in ("centered", "raw"):
        field = mode + "_D_LR_deg"; d, r = distributions[field], repeated[field]
        if r.get("pooled_within_sd") is not None and d.get("iqr", 0) > 0 and d.get("sd", 0) > 0:
            comparability[mode] = {"median_repeat_change_over_primary_iqr": r["median_absolute_change"] / d["iqr"],
                "max_repeat_change_over_primary_iqr": r["max_absolute_change"] / d["iqr"], "sw_over_primary_sd": r["pooled_within_sd"] / d["sd"]}
    return {"features": features, "models": models, "coefficients": coefficients, "loo": loo, "repeat": repeated,
            "primary_distribution": distributions, "repeat_vs_between": comparability,
            "primary_speed_mean_kmh": speed_mean, "bootstrap_distinct_people": _describe([len(np.unique(d)) for d in draws])}, arrays


def _body_motion(primary, edges, graph, geometry, scales, cfg):
    base = {"n_primary": len(primary), "n_graph_people": graph["n_subjects_with_edges"], "n_graph_edges": len(edges)}
    ordered = sorted(primary, key=lambda r: r["primary_order"])
    ids = [r["anonymized_id"] for r in ordered]
    positions = {pid: i for i, pid in enumerate(ids)}
    groups = graph["components_including_isolates"]
    group_of = {pid: i for i, g in enumerate(groups) for pid in g}
    effective = [g for g in groups if len(g) > 2]
    if not effective or not scales:
        return {**base, "status": "not_estimable", "reason": "no_informative_components_or_body_scale"}, {}
    vectors = np.array([[(pm.value(r, k) - scales[k]["mean"]) / scales[k]["sample_sd"] for k in cfg["body_fields"]] for r in ordered])
    ai = np.array([positions[e["a"]] for e in edges]); bi = np.array([positions[e["b"]] for e in edges])
    eg = np.array([group_of[e["a"]] for e in edges]); degrees = {r["anonymized_id"]: r["degree"] for r in graph["nodes"]}
    weights = np.array([.5 * (1 / degrees[e["a"]] + 1 / degrees[e["b"]]) for e in edges])
    active = np.array([len(groups[g]) > 2 for g in eg]); wa, ga = weights[active], eg[active]
    if not np.isfinite(vectors).all():
        return {**base, "status": "not_estimable", "reason": "missing_body_no_silent_graph_reduction"}, {}
    indices = pm.permute_vectors(vectors, [np.array([positions[p] for p in g]) for g in effective], cfg["permutations"], cfg["seed"])
    body = np.linalg.norm(vectors[ai] - vectors[bi], axis=1)
    body_null = np.linalg.norm(vectors[indices][:, ai] - vectors[indices][:, bi], axis=2)
    bc, centered_null = pm.center_within(body[active], ga, wa), pm.center_within(body_null[:, active], ga, wa)
    result = {**base, "status": "estimated", "n_effective_people": sum(map(len, effective)), "n_effective_groups": len(effective), "n_effective_edges": int(active.sum()),
              "excluded_two_person_groups": [g for g in groups if len(g) == 2], "statistics": {}, "edge_statistics": []}
    arrays = {"body_permutation_indices": indices.astype(np.int32), "body_participant_ids": np.array(ids, dtype=str),
              "body_edge_a_indices": ai, "body_edge_b_indices": bi, "body_edge_weights": weights, "body_active_edge_mask": active}
    null_columns = []
    for mode in ("time_mean_centered", "raw"):
        lookup = {(r["a"], r["b"]): r.get("chamfer_rms_deg", float("nan")) for r in geometry["candidate_rows"] if r["sampling_factor"] == 1 and r["mode"] == mode}
        y = np.array([lookup[(e["a"], e["b"])] for e in edges])
        try:
            if not np.isfinite(y).all():
                raise ValueError("missing_geometry_no_silent_graph_reduction")
            yc = pm.center_within(y[active], ga, wa)
            observed = float(pm.weighted_r(bc, yc, wa)); null = pm.weighted_r(centered_null, yc, wa)
            exceed = int(np.count_nonzero(abs(null) >= abs(observed) - 1e-12)); p = (1 + exceed) / (len(null) + 1)
            result["statistics"][mode] = {"status": "estimated", "role": "primary" if mode == "time_mean_centered" else "secondary",
                "unconditional_descriptive_r": float(pm.weighted_r(body, y, weights)), "conditional_r": observed, "two_sided_permutation_p": p,
                "permutation_exceedances": exceed, "permutations": len(null), "monte_carlo_se": float(np.sqrt(p * (1 - p) / (len(null) + 1))),
                "null_mean": float(null.mean()), "null_sd": float(null.std(ddof=1)), "null_quantiles": dict(zip(["min", "p025", "p25", "median", "p75", "p975", "max"], np.quantile(null, [0, .025, .25, .5, .75, .975, 1]).tolist())),
                "not_causal": True, "unadjusted_exploratory_secondary": mode == "raw"}
            null_columns.append(null)
            cb, cy = pm.center_within(body, eg, weights), pm.center_within(y, eg, weights)
            for i, edge in enumerate(edges):
                result["edge_statistics"].append({"mode": mode, "a": edge["a"], "b": edge["b"], "component": int(eg[i]), "weight": weights[i],
                    "included_in_conditional_statistic": bool(active[i]), "body_distance": body[i], "motion_distance_deg": y[i], "group_centered_body_distance": cb[i], "group_centered_motion_distance": cy[i]})
        except ValueError as exc:
            result["statistics"][mode] = {"status": "not_estimable", "reason": str(exc)}
            null_columns.append(np.full(cfg["permutations"], np.nan))
    arrays["body_null_statistics"] = np.column_stack(null_columns)
    arrays["body_statistic_names"] = np.array(["time_mean_centered", "raw"], dtype=str)
    return result, arrays


def run_pattern_study(bundle, *, bootstrap_replicates=None, permutations=None):
    bundle = validate_pattern_bundle(bundle)
    cfg = configuration()
    for key, value in (("bootstrap_replicates", bootstrap_replicates), ("permutations", permutations)):
        if value is not None:
            if not isinstance(value, int) or value < 2:
                raise ValueError("at_least_two_resamples_required")
            if bundle["metadata"]["dataset_kind"] != "synthetic" and value != cfg[key]:
                raise ValueError("empirical_resampling_must_match_frozen_protocol")
            cfg[key] = value
    body, pairs, traces = _standardize(bundle)
    primary = [r for r in pairs if r["is_primary"]]
    scale_failure = None
    try:
        scales = pm.body_scale(list(body.values()), cfg["body_fields"])
    except ValueError as exc:
        scales = {}; scale_failure = str(exc)
    all_edges, edges, graphs = _candidates(primary, scales, cfg)
    geometry = _geometry(primary, pairs, traces, edges, cfg)
    pressure_noise, noise_details = _pressure_repeats(bundle, cfg)
    static = _static_analysis(bundle, body, cfg)
    motion, arrays = _motion_analysis(pairs, traces, cfg)
    graph = graphs[str(cfg["primary_speed_caliper_kmh"])]
    body_result, body_arrays = _body_motion(primary, edges, graph, geometry, scales, cfg)
    arrays.update(body_arrays)
    weights = pm.degree_weights(edges, graph) if edges else np.array([])
    numeric_edges = [{k: (float("nan") if v is None else v) for k, v in r.items()} for r in edges]
    frontier = pm.joint_frontier(numeric_edges, weights) if edges else []
    repeat_frontier = {"status": "not_estimable", "reason": "repeat_scales_unavailable"}
    if all(pressure_noise.get(f, {}).get("status") == "estimated" and pressure_noise[f]["within_sd"] > 0 for f in ("pressure_peak_N", "effective_area_cm2")):
        common = []
        for e in edges:
            if all(_finite(e[f + "_abs_difference"]) for f in ("pressure_peak_N", "effective_area_cm2")):
                k = max(e[f + "_abs_difference"] / (math.sqrt(2) * pressure_noise[f]["within_sd"]) for f in ("pressure_peak_N", "effective_area_cm2"))
                common.append({"a": e["a"], "b": e["b"], "common_k": k})
        repeat_frontier = {"status": "estimated", "n_edges": len(edges), "n_edges_with_both": len(common),
            "minimum_common_k": min((r["common_k"] for r in common), default=None), "per_edge": common,
            "counts": [{"k": k, "n_edges": sum(r["common_k"] <= k for r in common)} for k in (1, 1.96, 2, 3, 4)],
            "interpretation": "descriptive repeat-scale reference, not a substantive equivalence threshold"}
    result = {"schema_version": "scm-strategy.pattern-result/1", "analysis_mode": "pattern-study", "package_version": __version__,
        "dataset_kind": bundle["metadata"]["dataset_kind"], "local_only": True, "exportable": False, "configuration": cfg,
        "input_scope": bundle["metadata"]["recording_scope"], "quality_summary": bundle["metadata"].get("quality_summary", {}),
        "quality_summary_origin": "producer-supplied, not source QC reconstructed by this command",
        "counts": {"participants": len(body), "primary": len(primary), "paired_trials": len(pairs), "pressure_repeats": len(bundle["pressure_repeats"])},
        "body_scales": scales, "body_scale_failure": scale_failure,
        "candidates": {"all_pairs": all_edges, "primary_edges": edges, "graphs": graphs, "joint_pressure_frontier": frontier, "joint_repeat_scale_frontier": repeat_frontier},
        "geometry": geometry, "pressure_repeat": {"summary": pressure_noise, "details": noise_details},
        "static_bilateral": static, "motion_bilateral": motion, "body_motion": body_result,
        "limitations": ["model-coordinate geometry, not independent kinematic truth", "same-session repeats, not longitudinal reliability", "pressure proxies share measurement and mathematical dependence", "no metabolic, injury, causal-adaptation or substantive-equivalence inference", "all planned specifications retained; missing data and failures reported"],
        "arrays": arrays}
    return result


def _write_csv(path, rows):
    if not rows:
        path.write_text("status\nno_rows\n"); return
    rows = _safe(_public_keys(rows))
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)


def save_pattern_study(result, directory):
    root = Path(directory); root.mkdir(parents=True, exist_ok=True)
    payload = _safe(_public_keys({k: v for k, v in result.items() if k != "arrays"}))
    (root / "pattern_study.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    np.savez_compressed(root / "resampling_arrays.npz", **result["arrays"])
    tables = {"all_pairs": result["candidates"]["all_pairs"], "candidate_edges": result["candidates"]["primary_edges"],
        "candidate_geometry": result["geometry"]["candidate_rows"], "repeat_geometry": result["geometry"]["repeat_rows"],
        "joint_pressure_frontier": result["candidates"]["joint_pressure_frontier"], "static_coefficients": result["static_bilateral"]["coefficients"],
        "static_loo": result["static_bilateral"]["loo"], "static_repeat_details": result["static_bilateral"]["repeat_details"],
        "motion_features": result["motion_bilateral"]["features"], "motion_coefficients": result["motion_bilateral"]["coefficients"],
        "motion_loo": result["motion_bilateral"]["loo"], "body_motion_edges": result["body_motion"].get("edge_statistics", [])}
    for name, rows in tables.items():
        _write_csv(root / (name + ".csv"), rows)
    lines = ["# Pattern study", "", f"Input kind: {result['dataset_kind']}. Local-only output; no public export permission.", "", 
        "Standardized coordinate/summary input only. Device reading, event selection and source QC are not repeated.", "",
        f"Participants: {result['counts']['participants']}; primary: {result['counts']['primary']}; paired records: {result['counts']['paired_trials']}.",
        "", "## Fixed association results", "", "|Family|Outcome|Spec|N|Slope|HC3 interval|Bootstrap interval|", "|---|---|---|---:|---:|---|---|"]
    for r in result["static_bilateral"]["models"]:
        if r["status"] == "estimated":
            c = r["coefficients"][1]
            lines.append(f"|static|{r['outcome']}|{r['spec']}|{r['n']}|{c['estimate']:.7g}|{c['hc3_ci95_low']:.7g}, {c['hc3_ci95_high']:.7g}|{c['bootstrap_ci95_low']:.7g}, {c['bootstrap_ci95_high']:.7g}|")
        else:
            lines.append(f"|static|{r['outcome']}|{r['spec']}|{r['n']}|not estimable|{r['reason']}||")
    for r in result["motion_bilateral"]["models"].values():
        if r["status"] == "estimated":
            lines.append(f"|motion|{r['outcome']}|{r['spec']}|{r['n_people']}|{r['beta'][1]:.7g}|{r['hc3_ci95'][1].tolist()}|{r['bootstrap_ci95'][1].tolist()}|")
        else:
            lines.append(f"|motion|unavailable|unavailable|{r['n_people']}|not estimable|{r['reason']}||")
    lines += ["", "## Body–motion permutations", "", json.dumps(_safe(result["body_motion"].get("statistics", result["body_motion"])), indent=2), "", "## Limits", ""] + ["- " + s for s in result["limitations"]]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    return payload
