# SPDX-License-Identifier: BSD-3-Clause
"""Typed standardized tables and chronological coordinate arrays, without readers."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import re

import numpy as np

SCHEMA_VERSION = "scm-strategy.pattern-bundle/1"
CHANNELS = ["knee_left", "ankle_left", "knee_right", "ankle_right"]
PRESSURE = ["pressure_peak_N_left", "pressure_peak_N_right", "effective_area_cm2_left", "effective_area_cm2_right"]
BODY = ["height_cm", "weight_kg", "navicular_ratio", "navicular_height_left_mm", "navicular_height_right_mm", "foot_length_left_mm", "foot_length_right_mm", "forefoot_width_left_mm", "forefoot_width_right_mm"]
QUALITY = ["available", "direction", "n_left_events", "n_right_events"]
TABLE_FIELDS = {
    "participants": ["participant_id", *BODY],
    "pressure_index": ["participant_id", "trial_id", "speed_kmh", "contact_ms", *PRESSURE],
    "pressure_repeats": ["participant_id", "trial_id", "replicate_index", "speed_kmh", "contact_ms", *PRESSURE, *QUALITY, "window_duration_s"],
    "paired_trials": ["pair_id", "participant_id", "replicate_index", "speed_kmh", "is_primary", "primary_order", "analysis_order", "window_start_s", "window_end_s", "contact_ms", *PRESSURE, "motion_status", "qc_status", *QUALITY],
}
UNITS = {**{k: "mm" for k in BODY if k.endswith("_mm")}, "height_cm": "cm", "weight_kg": "kg", "navicular_ratio": "dimensionless", "speed_kmh": "km/h", "contact_ms": "ms", **{k: ("N" if k.startswith("pressure") else "cm2") for k in PRESSURE}, "window_start_s": "s", "window_end_s": "s", "window_duration_s": "s", "values_deg": "degree"}
TEXT = {"participant_id", "trial_id", "pair_id", "direction", "motion_status", "qc_status"}
BOOL = {"is_primary", "available"}
INT = {"primary_order", "analysis_order", "replicate_index", "n_left_events", "n_right_events"}
ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,79}\Z")


def _number(value, key):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"numeric_boolean:{key}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"nonfinite:{key}")
    if key in INT:
        if int(result) != result or result < 0:
            raise ValueError(f"nonnegative_integer_required:{key}")
        return int(result)
    if result <= 0 and key not in {"window_start_s", "window_end_s"}:
        raise ValueError(f"positive_value_required:{key}")
    return result


def _row(row, fields):
    if set(fields) - set(row):
        raise ValueError("missing_table_columns:" + ",".join(sorted(set(fields) - set(row))))
    result = {}
    for key in fields:
        value = row[key]
        if key in TEXT:
            if not isinstance(value, str) or not value:
                raise ValueError(f"text_required:{key}")
            if key.endswith("_id") and not ID.fullmatch(value):
                raise ValueError(f"opaque_key_required:{key}")
        elif key in BOOL:
            if value in ("true", "True"):
                value = True
            elif value in ("false", "False"):
                value = False
            if not isinstance(value, bool):
                raise ValueError(f"boolean_required:{key}")
        else:
            value = _number(value, key)
            if key in INT and value is None and key != "primary_order":
                raise ValueError(f"integer_required:{key}")
        result[key] = value
    return result


def validate_pattern_bundle(bundle):
    """Validate each table at its own grain; preserve missing scientific values."""
    meta = bundle.get("metadata", {})
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unknown_pattern_schema")
    if meta.get("dataset_kind", "private_empirical") not in {"private_empirical", "synthetic"}:
        raise ValueError("unknown_dataset_kind")
    if meta.get("units") != UNITS:
        raise ValueError("pattern_units_mismatch")
    if not isinstance(meta.get("recording_scope"), str) or not meta["recording_scope"]:
        raise ValueError("recording_scope_required")
    tables = {}
    for table, fields in TABLE_FIELDS.items():
        if table not in bundle or not isinstance(bundle[table], list):
            raise ValueError(f"table_required:{table}")
        tables[table] = [_row(r, fields) for r in bundle[table]]
    people = [r["participant_id"] for r in tables["participants"]]
    if len(people) < 2 or len(set(people)) != len(people):
        raise ValueError("unique_body_people_required")
    person_set = set(people)
    for table, keys in [("pressure_index", ["participant_id"]), ("pressure_repeats", ["participant_id", "trial_id"]), ("paired_trials", ["pair_id"])]:
        rows = tables[table]
        tuples = [tuple(r[k] for k in keys) for r in rows]
        if len(set(tuples)) != len(tuples):
            raise ValueError(f"duplicate_key:{table}")
        if any(r["participant_id"] not in person_set for r in rows):
            raise ValueError(f"unknown_person:{table}")
    if {r["participant_id"] for r in tables["pressure_index"]} != person_set:
        raise ValueError("pressure_index_must_cover_body_cohort")
    for r in tables["participants"]:
        keys = ["navicular_ratio", "navicular_height_left_mm", "navicular_height_right_mm", "foot_length_left_mm", "foot_length_right_mm"]
        if all(r[k] is not None for k in keys):
            actual = .5 * (r[keys[1]] / r[keys[3]] + r[keys[2]] / r[keys[4]])
            if not math.isclose(r["navicular_ratio"], actual, rel_tol=1e-8, abs_tol=1e-10):
                raise ValueError("stored_navicular_ratio_inconsistent")
    pairs = tables["paired_trials"]
    if len(pairs) < 2 or sorted(r["analysis_order"] for r in pairs) != list(range(len(pairs))):
        raise ValueError("contiguous_pair_analysis_order_required")
    primary = [r for r in pairs if r["is_primary"]]
    if len(primary) < 2 or len({r["participant_id"] for r in primary}) != len(primary):
        raise ValueError("one_primary_pair_per_selected_person_required")
    if any(r["primary_order"] is None for r in primary) or sorted(r["primary_order"] for r in primary) != list(range(len(primary))):
        raise ValueError("contiguous_primary_order_required")
    if any(r["primary_order"] is not None for r in pairs if not r["is_primary"]):
        raise ValueError("nonprimary_primary_order_must_be_null")
    for r in pairs:
        if r["motion_status"] not in {"valid", "missing"}:
            raise ValueError("unknown_motion_status")
        if r["window_start_s"] is None or r["window_end_s"] is None or not math.isclose(r["window_end_s"] - r["window_start_s"], 20., abs_tol=1e-8):
            raise ValueError("paired_common20_window_required")
    motion = bundle.get("motion", {})
    arrays = {k: np.asarray(motion[k]) for k in ("pair_ids", "row_offsets", "values_deg", "channel_names")}
    ids, offsets, values = arrays["pair_ids"], arrays["row_offsets"], arrays["values_deg"]
    if ids.dtype.kind not in "US" or ids.ndim != 1 or len(set(ids.tolist())) != len(ids) or set(ids.tolist()) != {r["pair_id"] for r in pairs}:
        raise ValueError("motion_pair_binding_mismatch")
    if arrays["channel_names"].tolist() != CHANNELS:
        raise ValueError("motion_channel_order_mismatch")
    if offsets.dtype.kind not in "iu" or offsets.shape != (len(ids) + 1,) or offsets[0] != 0 or np.any(np.diff(offsets) < 0):
        raise ValueError("invalid_motion_offsets")
    if values.dtype.kind not in "fiu" or values.ndim != 2 or values.shape[1] != 4 or offsets[-1] != len(values):
        raise ValueError("invalid_motion_shape")
    lookup = {r["pair_id"]: r for r in pairs}
    for i, pid in enumerate(ids.tolist()):
        part = values[offsets[i]:offsets[i + 1]]
        if lookup[pid]["motion_status"] == "valid":
            if not len(part) or not np.isfinite(part).all():
                raise ValueError("valid_motion_must_be_finite_nonempty")
        elif len(part):
            raise ValueError("missing_motion_requires_empty_slice")
    clean_meta = {k: meta[k] for k in ("schema_version", "units", "recording_scope", "quality_summary", "generator") if k in meta}
    clean_meta["dataset_kind"] = meta.get("dataset_kind", "private_empirical")
    return {"metadata": clean_meta, **tables, "motion": {**arrays, "values_deg": values.astype(float, copy=False)}}


def read_pattern_bundle(directory):
    root = Path(directory)
    bundle = {"metadata": json.loads((root / "bundle.json").read_text())}
    for table in TABLE_FIELDS:
        with (root / f"{table}.csv").open(newline="", encoding="utf-8-sig") as stream:
            bundle[table] = list(csv.DictReader(stream))
    with np.load(root / "motion.npz", allow_pickle=False) as arrays:
        bundle["motion"] = {k: arrays[k] for k in ("pair_ids", "row_offsets", "values_deg", "channel_names")}
    return validate_pattern_bundle(bundle)


def write_pattern_bundle(bundle, directory):
    bundle = validate_pattern_bundle(bundle)
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / "bundle.json").write_text(json.dumps(bundle["metadata"], indent=2, allow_nan=False) + "\n")
    for table, fields in TABLE_FIELDS.items():
        with (root / f"{table}.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fields)
            writer.writeheader()
            for row in bundle[table]:
                writer.writerow({k: (str(v).lower() if isinstance(v, bool) else v) for k, v in row.items()})
    np.savez_compressed(root / "motion.npz", **bundle["motion"])
