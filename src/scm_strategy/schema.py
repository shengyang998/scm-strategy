# SPDX-License-Identifier: BSD-3-Clause
"""Strict standardized participant-table contract; no private device formats."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import re

SCHEMA_VERSION = "scm-strategy.participants/1"
UNITS = {
    "speed_kmh":"km/h", "height_cm":"cm", "weight_kg":"kg", "age_years":"year",
    "navicular_ratio":"1", "foot_size_proxy_cm2":"cm^2", "knee_excursion_deg":"degree",
    "ankle_excursion_deg":"degree", "contact_ms":"ms", "pressure_peak_N":"N", "effective_area_cm2":"cm^2",
}
FIELDS = ["participant_id", *UNITS]
KINDS = {"synthetic","private_empirical"}


class SchemaError(ValueError):
    """An explicit input-contract violation; never silently impute."""


def validate_records(records, metadata):
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("unsupported_schema_version")
    if metadata.get("dataset_kind") not in KINDS:
        raise SchemaError("dataset_kind_required")
    units=metadata.get("units",{})
    for field,unit in UNITS.items():
        if units.get(field)!=unit:
            raise SchemaError("missing_or_wrong_unit:"+field)
    if not records:
        raise SchemaError("empty_table")
    normalized=[];seen=set()
    for row in records:
        if set(row)!=set(FIELDS):
            raise SchemaError("columns_must_match_participant_contract")
        identifier=row.get("participant_id")
        if not isinstance(identifier,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",identifier):
            raise SchemaError("missing_or_invalid_participant_id")
        if identifier in seen:
            raise SchemaError("duplicate_participant_id")
        seen.add(identifier)
        result={"participant_id":identifier}
        for field in UNITS:
            try:value=float(row[field])
            except (ValueError,TypeError):raise SchemaError("invalid_number:"+field) from None
            if not math.isfinite(value) or value<=0:
                raise SchemaError("nonpositive_or_nonfinite:"+field)
            result[field]=value
        normalized.append(result)
    return normalized


def read_table(csv_path, metadata_path):
    with Path(csv_path).open(newline="",encoding="utf-8") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None or len(reader.fieldnames)!=len(set(reader.fieldnames)):
            raise SchemaError("duplicate_or_missing_header")
        rows=list(reader)
    metadata=json.loads(Path(metadata_path).read_text())
    return validate_records(rows,metadata),metadata


def canonical_csv(records):
    import io
    stream=io.StringIO(newline="")
    writer=csv.DictWriter(stream,fieldnames=FIELDS,lineterminator="\n")
    writer.writeheader()
    for row in records:
        writer.writerow({k:row[k] if k=="participant_id" else format(float(row[k]),".17g") for k in FIELDS})
    return stream.getvalue()


def write_table(records, metadata, csv_path, metadata_path):
    normalized=validate_records(records,metadata)
    Path(csv_path).write_text(canonical_csv(normalized))
    Path(metadata_path).write_text(json.dumps(metadata,indent=2,sort_keys=True)+"\n")

