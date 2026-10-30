# SPDX-License-Identifier: BSD-3-Clause
"""Public JSON is reconstructed exclusively from a verified synthetic recipe."""
from __future__ import annotations

import json
from pathlib import Path
from .analysis import analyze,OUTCOME_MODELS
from .schema import UNITS,FIELDS,read_table,SchemaError
from .synthetic import generate,verify_recipe

WEB_SCHEMA_VERSION="scm-strategy.web/1"


def export_payload(run_directory):
    root=Path(run_directory)
    manifest=json.loads((root/"run_manifest.json").read_text())
    if manifest.get("dataset_kind")!="synthetic":
        raise SchemaError("public_export_requires_verified_synthetic_run")
    records,metadata=read_table(root/"participants.csv",root/"metadata.json")
    verified=verify_recipe(records,metadata)
    recipe=metadata["generator"]
    regenerated,clean_metadata=generate(recipe["parameters"]["participants"],recipe["seed"])
    # Never forward an existing analysis.json, log, input hash, path, metadata
    # extension or caller-supplied numerical result to a public file.
    configuration=manifest.get("configuration",{})
    result=analyze(regenerated,clean_metadata,dataset_kind="synthetic",
                   bootstrap_replicates=configuration.get("bootstrap_replicates",2000),seed=configuration.get("seed",20261030))
    outcomes={}
    for name,(unit,_) in OUTCOME_MODELS.items():
        source=result["outcomes"][name]
        outcomes[name]={"unit":unit,"cross_validation":dict(source["cross_validation"]),
                        "delta_mae_bootstrap_ci95":source["delta_mae_bootstrap_ci95"],
                        "coefficients":[{key:row[key] for key in ["term","estimate","hc3_ci95","bootstrap_ci95"]} for row in source["coefficients"]],
                        "predictions":[{key:row[key] for key in ["participant_id","observed","baseline_prediction","augmented_prediction"]} for row in source["predictions"]]}
    return {"schema_version":WEB_SCHEMA_VERSION,"dataset_kind":"synthetic",
            "generator":clean_metadata["generator"],"units":dict(UNITS),
            "records":[{key:row[key] for key in FIELDS} for row in verified],"analysis":outcomes,
            "disclaimer":"Independent equation-generated demonstration. No real participant data or empirical research findings."}


def export_web(run_directory,output_path):
    payload=export_payload(run_directory)
    path=Path(output_path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n")
    return payload

