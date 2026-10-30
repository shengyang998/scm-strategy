# SPDX-License-Identifier: BSD-3-Clause
"""Strict, local-only display projection; never source paths or arbitrary metadata."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .pattern_bundle import validate_pattern_bundle
from .pattern_study import _safe


def build_pattern_view(bundle, result, max_points=2400):
    bundle = validate_pattern_bundle(bundle)
    if result.get("analysis_mode") != "pattern-study" or result["dataset_kind"] != bundle["metadata"]["dataset_kind"]:
        raise ValueError("pattern_result_input_kind_mismatch")
    if result["configuration"].get("protocol_id") != "scm-strategy.pattern/1":
        raise ValueError("unexpected_pattern_protocol")
    if not isinstance(max_points, int) or not 20 <= max_points <= 2400:
        raise ValueError("display_point_limit_must_be_20_to_2400")
    people = {r["participant_id"]: r for r in bundle["participants"]}
    features = {r["pair_id"]: r for r in result["motion_bilateral"]["features"]}
    motion = bundle["motion"]
    traces = {str(pid): motion["values_deg"][motion["row_offsets"][i]:motion["row_offsets"][i + 1]] for i, pid in enumerate(motion["pair_ids"])}
    records = []
    for pair in sorted((r for r in bundle["paired_trials"] if r["is_primary"]), key=lambda r: r["primary_order"]):
        b = people[pair["participant_id"]]; trace = traces[pair["pair_id"]]
        record = {"participant_id": pair["participant_id"], **{k: b[k] for k in ("height_cm", "weight_kg", "navicular_ratio")},
                  "speed_kmh": pair["speed_kmh"], "contact_ms": pair["contact_ms"],
                  "qc_status": pair["qc_status"] if pair["qc_status"] in {"PASS", "WARNING", "SYNTHETIC", "NOT_AVAILABLE"} else "OTHER"}
        lengths = [b["foot_length_left_mm"], b["foot_length_right_mm"]]
        widths = [b["forefoot_width_left_mm"], b["forefoot_width_right_mm"]]
        record["foot_size_proxy_cm2"] = float(np.mean(lengths) * np.mean(widths) / 100) if None not in lengths + widths else None
        for field in ("pressure_peak_N", "effective_area_cm2"):
            values = [pair[field + "_left"], pair[field + "_right"]]
            record[field] = float(np.mean(values)) if None not in values else None
        if len(trace):
            excursion = np.quantile(trace, .95, axis=0) - np.quantile(trace, .05, axis=0)
            record.update(knee_excursion_deg=float(excursion[[0, 2]].mean()), ankle_excursion_deg=float(excursion[[1, 3]].mean()))
            positions = np.arange(len(trace)) if len(trace) <= max_points else np.unique(np.linspace(0, len(trace) - 1, max_points).astype(int))
            display = trace[positions]
            record["trajectories"] = {side: {"knee_deg": display[:, offset].tolist(), "ankle_deg": display[:, offset + 1].tolist()} for side, offset in (("left", 0), ("right", 2))}
        else:
            record.update(knee_excursion_deg=None, ankle_excursion_deg=None, trajectories=None)
        record["trajectory_sampling"] = {"source_points": len(trace), "display_points": min(max_points, len(trace)), "simplified": len(trace) > max_points}
        record["motion_summary"] = {k: features[pair["pair_id"]][k] for k in ("centered_D_LR_deg", "raw_D_LR_deg")}
        records.append(record)
    associations = []
    for model in result["static_bilateral"]["models"]:
        coefficients = [{"term": c["term"], "estimate": c["estimate"], "hc3_ci95": [c["hc3_ci95_low"], c["hc3_ci95_high"]], "bootstrap_ci95": [c["bootstrap_ci95_low"], c["bootstrap_ci95_high"]]} for c in model.get("coefficients", [])]
        associations.append({"family": "static_bilateral", "outcome": model["outcome"], "spec": model["spec"], "status": model["status"], "n": model["n"], "coefficients": coefficients,
            "condition_number": model.get("standardized_condition_number"), "bootstrap_valid": model.get("bootstrap_valid"), "bootstrap_failed": model.get("bootstrap_failed")})
    for key, model in result["motion_bilateral"]["models"].items():
        outcome, spec = key.split("__")
        coefficients = [{"term": term, "estimate": model["beta"][i], "hc3_ci95": model["hc3_ci95"][i], "bootstrap_ci95": model["bootstrap_ci95"][i]} for i, term in enumerate(model.get("terms", []))]
        associations.append({"family": "motion_bilateral", "outcome": outcome, "spec": spec, "status": model["status"], "n": model["n_people"], "coefficients": coefficients,
            "condition_number": model.get("standardized_condition_number"), "bootstrap_valid": model.get("bootstrap_valid"), "bootstrap_failed": sum(model.get("bootstrap_failures", {}).values())})
    body = result["body_motion"]
    counts = {k: body.get(k) for k in ("n_primary", "n_graph_people", "n_graph_edges", "n_effective_people", "n_effective_groups", "n_effective_edges")}
    statistics = {mode: {k: stat.get(k) for k in ("status", "conditional_r", "unconditional_descriptive_r", "two_sided_permutation_p", "monte_carlo_se", "null_mean")} for mode, stat in body.get("statistics", {}).items()}
    cfg = result["configuration"]
    generator = bundle["metadata"].get("generator", {})
    safe_generator = {}
    if result["dataset_kind"] == "synthetic" and generator.get("name") == "scm-strategy.pattern-equations/1":
        safe_generator["name"] = generator["name"]
        safe_generator.update({k: generator[k] for k in ("seed", "participants", "primary_participants", "samples_per_record") if isinstance(generator.get(k), int) and generator[k] >= 0})
    return _safe({"schema_version": "scm-strategy.pattern-local/1", "dataset_kind": result["dataset_kind"], "local_only": True, "exportable": False, "upload_allowed": False,
        "notice": "Standardized model-coordinate and pressure summaries; no source audit, physiological cost or clinical validation. Display retains original sample order; only over-cap traces are simplified. Analysis uses complete supplied arrays.",
        "protocol_id": cfg["protocol_id"], "generator": safe_generator,
        "units": {"height_cm": "cm", "weight_kg": "kg", "navicular_ratio": "1", "speed_kmh": "km/h", "contact_ms": "ms", "pressure_peak_N": "N", "effective_area_cm2": "cm^2", "foot_size_proxy_cm2": "cm^2", "knee_excursion_deg": "degree", "ankle_excursion_deg": "degree", "trajectories": "degree"},
        "configuration": {"seed": cfg["seed"], "bootstrap_replicates": cfg["bootstrap_replicates"], "permutations": cfg["permutations"], "primary_speed_caliper_kmh": cfg["primary_speed_caliper_kmh"], "display_max_points": max_points,
                          "full_frozen_counts": cfg["bootstrap_replicates"] == 2000 and cfg["permutations"] == 9999},
        "records": records, "associations": associations, "body_motion": {"counts": counts, "statistics": statistics},
        "geometry_summary": result["geometry"]["summary"]["1"], "repeat_summary": result["motion_bilateral"]["repeat"]})


def write_pattern_view(bundle, result, path):
    payload = build_pattern_view(bundle, result)
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return payload
