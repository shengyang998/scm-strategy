# SPDX-License-Identifier: BSD-3-Clause
"""Typed, multi-table standardized inputs for the frozen paper workflow.

This boundary starts after authorized source decoding, synchronization and
feature extraction. It never opens device files or infers missing QC.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import re

from .schema import SchemaError, UNITS

BUNDLE_VERSION = "scm-strategy.paper-bundle/1"
PROTOCOL_ID = "scm-strategy-pressure/1.0.0"
SPECS = ("participant_mean", "p10_p90", "offset_m010", "offset_p010", "offset_m025", "offset_p025")
COHORT_UNITS = {"bmi": "kg/m^2", "body_fat_pct": "%", "navicular_height_L_mm": "mm",
                "navicular_height_R_mm": "mm", "subject_median_speed_kmh": "km/h"}
ALL_UNITS = {**UNITS, **COHORT_UNITS}
DEFAULT_FILES = {"primary": "primary_participants.csv", "extension": "extension_participants.csv",
                 "sensitivities": "sensitivity_participants.csv", "pressure_repeats": "nonfirst_backward_trials.csv",
                 "paired_trials": "all_paired_trials.csv", "cohort_profiles": "cohort_profiles.csv"}
REQUIRED_TABLES = ("primary", "extension", "sensitivities", "pressure_repeats")
COMMON = ("participant_id", "trial_id", "trial_index", "direction", "available", "exclusion_reason")
PRESSURE_NUMBERS = tuple(k for k in UNITS if k not in ("knee_excursion_deg", "ankle_excursion_deg"))
PROFILE_NUMBERS = ("height_cm", "weight_kg", "age_years", "bmi", "body_fat_pct", "navicular_height_L_mm",
                   "navicular_height_R_mm", "subject_median_speed_kmh")
NUMBERS = {"primary": tuple(UNITS), "extension": PRESSURE_NUMBERS, "sensitivities": tuple(UNITS),
           "pressure_repeats": ("speed_kmh", "effective_area_cm2"), "paired_trials": tuple(UNITS),
           "cohort_profiles": PROFILE_NUMBERS}
FIELDS = {key: (*COMMON, *values) for key, values in NUMBERS.items() if key != "cohort_profiles"}
FIELDS["primary"] += ("qc_status",)
FIELDS["paired_trials"] += ("qc_status",)
FIELDS["sensitivities"] += ("qc_status", "spec")
FIELDS["cohort_profiles"] = ("participant_id", *PROFILE_NUMBERS, "recorded_sex")
QC = {"PASS", "WARNING"}
FAILED_QC = {"FAIL-MINOR", "FAIL-MODERATE", "FAIL-SEVERE", "NOT_AVAILABLE"}
COUNT_KEYS = {"source_participants", "source_pressure_trials", "eligible_pressure_trials", "pressure_excluded_trials",
              "conservative_pair_count", "eligible_nonfirst_backward_trials"}
QUALITY_KEYS = {"min_complete_events_per_side", "primary_PASS_count", "primary_WARNING_count", "source_exclusions",
                "mot_participants_screened", "mot_channel_series_screened", "heuristic_review_participants", "automatic_exclusions"}


def _identifier(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:|;-]{1,256}", value):
        raise SchemaError("invalid_paper_identifier:" + field)
    return value


def _boolean(value):
    if value is True or value == "True" or value == "true": return True
    if value is False or value == "False" or value == "false": return False
    raise SchemaError("paper_available_must_be_boolean")


def _number(value, field):
    if value is None or value == "": return None
    if isinstance(value, bool): raise SchemaError("paper_number_is_boolean:" + field)
    try: result = float(value)
    except (ValueError, TypeError): raise SchemaError("invalid_paper_number:" + field) from None
    if not math.isfinite(result) or result <= 0:
        raise SchemaError("paper_number_not_positive_finite:" + field)
    return result


def _integer(value, nullable=False):
    if nullable and (value is None or value == ""): return None
    if isinstance(value, bool): raise SchemaError("paper_trial_index_is_boolean")
    try: number = float(value)
    except (ValueError, TypeError): raise SchemaError("invalid_paper_trial_index") from None
    if not math.isfinite(number) or number < 1 or int(number) != number:
        raise SchemaError("paper_trial_index_must_be_positive_integer")
    return int(number)


def validate_paper_bundle(bundle):
    """Return a normalized copy; preserve row order and explicitly retain nulls."""
    if not isinstance(bundle, dict) or "metadata" not in bundle: raise SchemaError("paper_bundle_metadata_required")
    if set(bundle) - {"metadata", *DEFAULT_FILES}: raise SchemaError("unknown_paper_bundle_table")
    if not isinstance(bundle["metadata"],dict):raise SchemaError("paper_metadata_must_be_object")
    metadata = dict(bundle["metadata"])
    if metadata.get("schema_version") != BUNDLE_VERSION: raise SchemaError("unsupported_paper_bundle_version")
    if metadata.get("protocol_id") != PROTOCOL_ID: raise SchemaError("paper_protocol_mismatch")
    metadata.setdefault("dataset_kind", "private_empirical")
    if metadata["dataset_kind"] not in {"private_empirical", "synthetic"}: raise SchemaError("invalid_paper_dataset_kind")
    allowed_meta = {"schema_version", "protocol_id", "dataset_kind", "units", "generator", "description", "cohort_counts", "quality_counts", "synthetic_notice", "sensitivity_notice", "cohort_profile_scope"}
    if set(metadata) - allowed_meta: raise SchemaError("unknown_paper_metadata_field")
    units = metadata.get("units", {})
    if not isinstance(units,dict):raise SchemaError("paper_units_must_be_object")
    required_units = {**UNITS, **(COHORT_UNITS if "cohort_profiles" in bundle else {})}
    if set(units) - set(ALL_UNITS) or any(units.get(k) != v for k, v in required_units.items()):
        raise SchemaError("paper_units_missing_or_mismatched")
    for name, keys in [("cohort_counts", COUNT_KEYS), ("quality_counts", QUALITY_KEYS)]:
        counts = metadata.get(name, {})
        if not isinstance(counts, dict) or set(counts) - keys: raise SchemaError("invalid_paper_count_keys:" + name)
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
            raise SchemaError("paper_counts_must_be_nonnegative_integers:" + name)
    result = {"metadata": metadata}
    missing = []
    for name in REQUIRED_TABLES:
        if name not in bundle: raise SchemaError("missing_paper_table:" + name)
    for name in DEFAULT_FILES:
        if name not in bundle: continue
        rows = bundle[name]
        if not isinstance(rows, list) or (name in REQUIRED_TABLES and not rows): raise SchemaError("empty_or_invalid_paper_table:" + name)
        normalized = []; seen = set(); orders = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(FIELDS[name]): raise SchemaError("paper_columns_mismatch:" + name)
            out = {"participant_id": _identifier(row["participant_id"], "participant_id")}
            if name == "cohort_profiles":
                sex = row["recorded_sex"]
                if sex == "": sex = None
                if sex not in {None, "F", "M", "other", "unknown"}: raise SchemaError("invalid_recorded_sex")
                out["recorded_sex"] = sex
            else:
                out["trial_id"] = _identifier(row["trial_id"], "trial_id")
                aggregate = name == "sensitivities" and row["spec"] == "participant_mean"
                out["trial_index"] = _integer(row["trial_index"], nullable=aggregate)
                if row["direction"] != "backward": raise SchemaError("paper_v1_requires_backward_condition")
                out["direction"] = "backward"; out["available"] = _boolean(row["available"])
                if not isinstance(row["exclusion_reason"], str): raise SchemaError("paper_exclusion_reason_must_be_string")
                if not out["available"] and not row["exclusion_reason"].strip(): raise SchemaError("unavailable_paper_row_requires_reason")
                out["exclusion_reason"] = row["exclusion_reason"]
                if name in {"primary", "paired_trials", "sensitivities"}:
                    allowed = QC | ({"MIXED_PASS_WARNING"} if aggregate else set()) | (FAILED_QC if not out["available"] else set())
                    if row["qc_status"] not in allowed: raise SchemaError("invalid_paper_qc_status:" + name)
                    out["qc_status"] = row["qc_status"]
                if name == "sensitivities":
                    if row["spec"] not in SPECS: raise SchemaError("unknown_paper_sensitivity_spec")
                    out["spec"] = row["spec"]
            for field in NUMBERS[name]:
                out[field] = _number(row[field], field)
                if out[field] is None: missing.append({"table": name, "participant_id": out["participant_id"], "field": field})
            if name in {"primary","paired_trials","sensitivities"} and out["available"] and any(out[k] is None for k in ("knee_excursion_deg","ankle_excursion_deg")):
                raise SchemaError("available_paired_row_requires_motion; use unavailable status with a reason")
            key = (out["spec"], out["participant_id"]) if name == "sensitivities" else (out["participant_id"], out["trial_id"]) if name in {"pressure_repeats", "paired_trials"} else out["participant_id"]
            if key in seen: raise SchemaError("duplicate_paper_key:" + name)
            seen.add(key)
            if name in {"pressure_repeats", "paired_trials"}:
                order = (out["participant_id"], out["trial_index"])
                if order in orders: raise SchemaError("duplicate_within_participant_trial_index:" + name)
                orders.add(order)
            normalized.append(out)
        result[name] = normalized
    primary_ids = {r["participant_id"] for r in result["primary"]}
    extension_ids = {r["participant_id"] for r in result["extension"]}
    if not primary_ids <= extension_ids: raise SchemaError("primary_not_subset_of_extension")
    for name in ("sensitivities", "paired_trials"):
        if name in result and not {r["participant_id"] for r in result[name]} <= primary_ids:
            raise SchemaError(name + "_participant_not_in_primary")
    if not {r["participant_id"] for r in result["pressure_repeats"]} <= extension_ids: raise SchemaError("repeat_participant_not_in_extension")
    if "cohort_profiles" in result and {r["participant_id"] for r in result["cohort_profiles"]} != extension_ids:
        raise SchemaError("cohort_profiles_must_cover_extension_exactly")
    for spec in SPECS:
        ids = {r["participant_id"] for r in result["sensitivities"] if r["spec"] == spec}
        if ids != primary_ids: raise SchemaError("sensitivity_must_record_every_primary_participant:" + spec)
    result["validation"] = {"missing_values": missing, "row_counts": {k: len(result[k]) for k in DEFAULT_FILES if k in result},
                            "source_qc_not_reconstructed": True}
    return result


def read_paper_bundle(directory):
    root = Path(directory).resolve()
    manifest = json.loads((root / "bundle.json").read_text())
    tables = manifest.pop("tables", None)
    if not isinstance(tables, dict) or set(tables) - set(DEFAULT_FILES): raise SchemaError("paper_table_manifest_required")
    result = {"metadata": manifest}
    for name, filename in tables.items():
        if not isinstance(filename, str): raise SchemaError("paper_table_filename_must_be_string")
        if Path(filename).is_absolute():raise SchemaError("paper_table_filename_must_be_relative")
        path = (root / filename).resolve()
        if not path.is_relative_to(root): raise SchemaError("paper_table_path_outside_bundle")
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise SchemaError("duplicate_or_missing_paper_header")
            result[name] = list(reader)
    return validate_paper_bundle(result)


def write_paper_bundle(bundle, directory):
    # Do not accept a prior validation object as user input.
    source = {k: v for k, v in bundle.items() if k != "validation"}
    normalized = validate_paper_bundle(source)
    root = Path(directory); root.mkdir(parents=True, exist_ok=True)
    tables = {}
    for name, filename in DEFAULT_FILES.items():
        if name not in normalized: continue
        with (root / filename).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS[name], lineterminator="\n"); writer.writeheader()
            for row in normalized[name]:
                writer.writerow({k: "" if row[k] is None else format(row[k], ".17g") if isinstance(row[k], float) else row[k] for k in FIELDS[name]})
        tables[name] = filename
    (root / "bundle.json").write_text(json.dumps({**normalized["metadata"], "tables": tables}, indent=2, allow_nan=False) + "\n")
    return root


def paper_bundle_schema():
    """JSON Schema for the in-memory bundle; relational checks remain Python-side."""
    tables = {}
    for name, fields in FIELDS.items():
        properties = {field: {"type": ["number", "null"], "exclusiveMinimum": 0} for field in NUMBERS[name]}
        properties["participant_id"] = {"type": "string", "minLength": 1}
        if name == "cohort_profiles": properties["recorded_sex"] = {"enum": [None, "F", "M", "other", "unknown"]}
        else:
            properties.update({"trial_id": {"type": "string", "minLength": 1}, "trial_index": {"type": ["integer", "null"] if name == "sensitivities" else "integer", "minimum": 1},
                               "direction": {"const": "backward"}, "available": {"type": "boolean"}, "exclusion_reason": {"type": "string"}})
            if "qc_status" in fields: properties["qc_status"] = {"enum": sorted(QC|FAILED_QC|({"MIXED_PASS_WARNING"} if name=="sensitivities" else set()))}
            if name == "sensitivities": properties["spec"] = {"enum": list(SPECS)}
        item={"type": "object", "additionalProperties": False, "required": list(fields), "properties": properties}
        if name!="cohort_profiles":
            item["allOf"]=[{"if":{"properties":{"available":{"const":False}}},"then":{"properties":{"exclusion_reason":{"type":"string","minLength":1}}}}]
        if name in {"primary","paired_trials","sensitivities"}:
            item["allOf"].append({"if":{"properties":{"available":{"const":True}}},"then":{"properties":{
                "knee_excursion_deg":{"type":"number","exclusiveMinimum":0},"ankle_excursion_deg":{"type":"number","exclusiveMinimum":0},
                "qc_status":{"enum":["PASS","WARNING","MIXED_PASS_WARNING"] if name=="sensitivities" else ["PASS","WARNING"]}}}})
        if name=="sensitivities":
            item["allOf"].append({"if":{"properties":{"spec":{"not":{"const":"participant_mean"}}}},"then":{"properties":{
                "trial_index":{"type":"integer","minimum":1},"qc_status":{"not":{"const":"MIXED_PASS_WARNING"}}}}})
        tables[name] = {"type": "array", "items": item}
    metadata = {"type": "object", "required": ["schema_version", "protocol_id", "units"], "properties": {
        "schema_version": {"const": BUNDLE_VERSION}, "protocol_id": {"const": PROTOCOL_ID}, "dataset_kind": {"enum": ["private_empirical", "synthetic"], "default": "private_empirical"},
        "units": {"type": "object", "required": list(UNITS), "properties": {k: {"const": v} for k, v in ALL_UNITS.items()}, "additionalProperties": False},
        "generator":{"type":"object"},"description":{"type":"string"},"synthetic_notice":{"type":"string"},
        "sensitivity_notice":{"type":"string"},"cohort_profile_scope":{"type":"string"},
        "cohort_counts":{"type":"object","properties":{k:{"type":"integer","minimum":0} for k in sorted(COUNT_KEYS)},"additionalProperties":False},
        "quality_counts":{"type":"object","properties":{k:{"type":"integer","minimum":0} for k in sorted(QUALITY_KEYS)},"additionalProperties":False}},"additionalProperties":False}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
            "required": ["metadata", *REQUIRED_TABLES], "properties": {"metadata": metadata, **tables},
            "allOf":[{"if":{"required":["cohort_profiles"]},"then":{"properties":{"metadata":{"properties":{"units":{"required":list(COHORT_UNITS)}}}}}}],
            "$comment": "Python additionally validates composite keys, cohort subsets, six-spec coverage, whitespace-only reasons and finite values."}
