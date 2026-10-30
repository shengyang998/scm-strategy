# SPDX-License-Identifier: BSD-3-Clause
from copy import deepcopy
import csv
import json

import numpy as np
import pytest

from scm_strategy.paper_bundle import (
    validate_paper_bundle, read_paper_bundle, write_paper_bundle, paper_bundle_schema,
)
from scm_strategy.paper_study import (
    run_paper_study, save_paper_study, design, select_cases, select_complete,
    _repeat_statistics, cohort_selection_summary,
)
from scm_strategy.paper_synthetic import generate_paper_bundle
from scm_strategy.statistics import bootstrap_analysis, percentile_interval
from scm_strategy.schema import SchemaError
from scm_strategy.export import export_payload
from scm_strategy.cli import main


@pytest.fixture(scope="module")
def bundle():
    return generate_paper_bundle(total_participants=30,primary_participants=25,seed=72)


@pytest.fixture(scope="module")
def result(bundle):
    return run_paper_study(bundle,bootstrap_replicates=12,include_design_audit=True)


def test_table_grains_and_bundle_roundtrip(bundle,tmp_path):
    original=deepcopy(bundle)
    write_paper_bundle(bundle,tmp_path)
    reread=read_paper_bundle(tmp_path)
    normalized=validate_paper_bundle(bundle)
    assert reread==normalized
    assert bundle==original
    assert "knee_excursion_deg" not in reread["extension"][0]
    assert len({r["participant_id"] for r in reread["pressure_repeats"]})<len(reread["pressure_repeats"])
    assert paper_bundle_schema()["required"]==["metadata","primary","extension","sensitivities","pressure_repeats"]


def test_bundle_keys_units_and_subsets_are_enforced(bundle):
    for name in ["primary","extension","sensitivities","pressure_repeats"]:
        bad=deepcopy(bundle);del bad[name]
        with pytest.raises(SchemaError,match="missing_paper_table"):validate_paper_bundle(bad)
    bad=deepcopy(bundle);bad["metadata"]["units"]["contact_ms"]="s"
    with pytest.raises(SchemaError,match="units"):validate_paper_bundle(bad)
    bad=deepcopy(bundle);bad["extension"][0]["knee_excursion_deg"]=60
    with pytest.raises(SchemaError,match="columns"):validate_paper_bundle(bad)
    bad=deepcopy(bundle);bad["pressure_repeats"][0]["participant_id"]="OUTSIDE"
    with pytest.raises(SchemaError,match="not_in_extension"):validate_paper_bundle(bad)
    bad=deepcopy(bundle);bad["primary"].append(deepcopy(bad["primary"][0]))
    with pytest.raises(SchemaError,match="duplicate"):validate_paper_bundle(bad)


def test_every_sensitivity_person_has_explicit_row_and_aggregate_index_can_be_null(bundle):
    bad=deepcopy(bundle);bad["sensitivities"].pop()
    with pytest.raises(SchemaError,match="every_primary"):validate_paper_bundle(bad)
    good=deepcopy(bundle)
    row=next(r for r in good["sensitivities"] if r["spec"]=="participant_mean")
    row["trial_index"]=None;row["trial_id"]="aggregate:a|b"
    validate_paper_bundle(good)
    row["spec"]="p10_p90"
    with pytest.raises(SchemaError):validate_paper_bundle(good)


def test_missing_and_unavailable_rows_are_explicit_not_imputed(bundle):
    raw=deepcopy(bundle);raw["primary"][0]["contact_ms"]=None
    raw["primary"][1].update(available=False,exclusion_reason="QC failed",qc_status="FAIL-MINOR")
    normalized=validate_paper_bundle(raw)
    assert normalized["validation"]["missing_values"]
    rows,x,y,excluded=select_complete(normalized["primary"],["log_speed_kmh","log_height_cm"],"contact_ms")
    assert len(rows)==23 and len(excluded)==2
    assert "missing_or_invalid_outcome" in excluded[0]["reason"]
    assert "QC failed" in excluded[1]["reason"]
    assert np.isfinite(x).all() and np.isfinite(y).all()


def test_complete_synthetic_execution_has_22_analyses_17_cv_and_159_coefficients(result):
    assert len(result["analyses"])==22 and len(result["summary"])==22
    assert all(a["status"]=="estimated" for a in result["analyses"].values())
    assert sum("cv_metrics" in a for a in result["analyses"].values())==17
    coefficients=sum(len(a.get("baseline_coefficients",[]))+len(a.get("augmented_coefficients",[]))+len(a.get("coefficients",[])) for a in result["analyses"].values())
    assert coefficients==159
    assert result["configuration"]["seed"]==20261030
    assert result["configuration"]["full_frozen_draw_count"] is False
    assert result["dataset_kind"]=="private_empirical" and result["input_dataset_kind"]=="synthetic"
    assert result["exportable"] is False


def test_second_outcome_uses_same_frozen_seed_not_generic_plus_one(bundle,result):
    rows=bundle["primary"];ids=[r["participant_id"] for r in rows]
    x1=design(rows,["log_speed_kmh","log_weight_kg","knee_excursion_deg_per10","ankle_excursion_deg_per10"])
    y=np.array([r["pressure_peak_N"] for r in rows]);x0=x1[:,:3]
    correct=bootstrap_analysis(y,x0,x1,ids,12,20261030)
    shifted=bootstrap_analysis(y,x0,x1,ids,12,20261031)
    expected=percentile_interval([r["delta_mae_baseline_minus_augmented"] for r in correct["metrics"]])
    wrong=percentile_interval([r["delta_mae_baseline_minus_augmented"] for r in shifted["metrics"]])
    actual=result["analyses"]["primary__pressure_peak_N"]["cv_metric_bootstrap_ci95"]["delta_mae_baseline_minus_augmented"]
    assert actual==expected and actual!=wrong


def test_case_selection_remains_blind_and_frontiers_are_additive(bundle,result):
    first,_=select_cases(bundle["primary"],.15,3)
    changed=deepcopy(bundle["primary"])
    for row in changed:row["knee_excursion_deg"]*=100;row["contact_ms"]*=1000
    second,_=select_cases(changed,.15,3)
    assert first==second
    for case in result["analyses"]["primary__contact_ms"]["case_comparisons"]:
        ci=case["conditional_mean_difference_bootstrap_ci90"]
        assert case["minimum_symmetric_additive_containment_bound"]==max(abs(ci[0]),abs(ci[1]))
        assert case["frontier_unit"]=="ms"
        assert case["frontier_is_not_a_substantive_equivalence_threshold"]


def test_repeat_variance_pooling_matches_independent_hand_calculation():
    stats=_repeat_statistics([np.array([1.,3.,5.]),np.array([2.,6.])])
    assert stats["pooled_within_sd_cm2"]==pytest.approx(np.sqrt(16/3))
    assert stats["participant_balanced_within_sd_cm2"]==pytest.approx(np.sqrt(6))
    assert stats["first_last_bias_cm2"]==4
    assert stats["first_last_loa_lower_cm2"]==4
    assert stats["repeatability_coefficient_cm2"]==pytest.approx(1.96*np.sqrt(2)*np.sqrt(16/3))


def test_profile_median_speed_not_substituted_with_index_speed(bundle,result):
    changed=deepcopy(bundle)
    for i,row in enumerate(changed["cohort_profiles"]):row["subject_median_speed_kmh"]=20+i
    cohort=cohort_selection_summary(validate_paper_bundle(changed))
    speed=next(r for r in cohort["variables"] if r["variable"]=="subject_median_speed_kmh")
    assert speed["full_mean"]==pytest.approx(34.5)
    observed=next(r for r in cohort["observed_descriptives"] if r["variable"]=="speed_kmh")
    assert observed["extension"]["mean"]<20
    assert result["cohort_selection_summary"]["observed_descriptives"]
    del changed["cohort_profiles"]
    assert cohort_selection_summary(validate_paper_bundle(changed))["status"]=="not_available"


def test_fold_design_audit_reports_counts_and_distinct_people(result):
    models=result["numerical_design"]["models"]
    assert len(models)==34
    for m in models:
        assert m["original_loso_training"]["matrix_count"]==m["n_source_participants"]
        hist=m["bootstrap_distinct_participant_histogram"]
        assert sum(hist.values())==12
        assert sum(int(k)*v for k,v in hist.items())==m["bootstrap_loso_training"]["matrix_count"]
        assert m["minimum_bootstrap_training_distinct_participants"]<m["n_source_participants"]


def test_private_outputs_and_cli_preserve_existing_export_boundary(bundle,result,tmp_path):
    save_paper_study(result,tmp_path/"saved")
    with pytest.raises(SchemaError,match="synthetic"):export_payload(tmp_path/"saved")
    with (tmp_path/"saved"/"coefficients.csv").open() as f:assert len(list(csv.DictReader(f)))==159
    write_paper_bundle(bundle,tmp_path/"input")
    assert main(["paper-study",str(tmp_path/"input"),"--out",str(tmp_path/"cli"),"--bootstrap","10","--skip-design-audit"])==0
    output=json.loads((tmp_path/"cli"/"paper_study.json").read_text())
    assert len(output["analyses"])==22
    assert output["numerical_design"]["status"]=="not_run"
    empirical=deepcopy(bundle);empirical["metadata"]["dataset_kind"]="private_empirical"
    with pytest.raises(ValueError,match="frozen"):run_paper_study(empirical,bootstrap_replicates=10)


def test_no_protocol_read_at_import_time():
    import subprocess,sys
    code="""
import numpy,scipy.stats
from pathlib import Path
def fail(*a,**k):raise AssertionError('import-time file read')
Path.read_text=fail
import scm_strategy.paper_bundle,scm_strategy.paper_study
"""
    subprocess.run([sys.executable,"-c",code],check=True,capture_output=True,text=True)
