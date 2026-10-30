# SPDX-License-Identifier: BSD-3-Clause
"""End-to-end public paper workflow checks on independent synthetic inputs."""
from copy import deepcopy
import csv
import json

import numpy as np
import pytest

from scm_strategy.paper_bundle import read_paper_bundle, validate_paper_bundle, write_paper_bundle
from scm_strategy.paper_synthetic import generate_paper_bundle, verify_paper_recipe, paper_synthetic_digest
from scm_strategy.paper_study import run_paper_study
from scm_strategy.paper_report import (
    build_local_view_payload, write_local_view, write_paper_report,
    run_calibration, _reference_fit,
)
from scm_strategy.schema import SchemaError
from scm_strategy.statistics import fit_ols


@pytest.fixture(scope="module")
def workflow():
    bundle=generate_paper_bundle(seed=4262)
    result=run_paper_study(bundle,bootstrap_replicates=12,include_design_audit=True)
    return bundle,result


def test_synthetic_recipe_roundtrip_and_tamper_rejection(tmp_path):
    bundle=generate_paper_bundle(seed=4262)
    assert bundle==generate_paper_bundle(seed=4262)
    assert paper_synthetic_digest(bundle)!=paper_synthetic_digest(generate_paper_bundle(seed=4263))
    assert validate_paper_bundle(bundle)["validation"]["row_counts"]=={
        "primary":25,"extension":50,"sensitivities":150,"pressure_repeats":97,"paired_trials":30,"cohort_profiles":50}
    write_paper_bundle(bundle,tmp_path)
    loaded=read_paper_bundle(tmp_path)
    verify_paper_recipe(loaded)
    damaged=deepcopy(loaded);damaged["primary"][0]["contact_ms"]+=.5
    with pytest.raises(SchemaError,match="does_not_match_recipe"):
        verify_paper_recipe(damaged)


def test_all_22_models_and_aggregate_report(workflow,tmp_path):
    bundle,result=workflow
    assert len(result["analyses"])==22
    assert all(a["status"]=="estimated" for a in result["analyses"].values())
    report=write_paper_report(result,tmp_path,figures=False)
    assert report["input_dataset_kind"]=="synthetic"
    assert report["exportable"] is False
    assert len(report["tables"]["T2"])==17
    assert len(report["tables"]["T3"])==5
    assert len(report["coefficients"])==159
    assert len(report["tables"]["T1"]["observed_descriptives"])==11
    assert any(r["variable"]=="bmi" for r in report["tables"]["T1"]["variables"])
    assert any(r["variable"]=="subject_median_speed_kmh" for r in report["tables"]["T1"]["variables"])
    assert report["tables"]["T4"]["full_pressure_cohort"]["repeatable_n"]==46
    assert "participant_balanced_within_sd_cm2" in report["tables"]["T4"]["full_pressure_cohort"]["statistics"]
    assert "first_last_loa_upper_cm2" in report["tables"]["T4"]["primary_motion_cohort"]["statistics"]
    assert "SYN-" not in (tmp_path/"paper-report.json").read_text()
    assert len(list(csv.DictReader((tmp_path/"tables/S2_all_coefficients.csv").open())))==159
    assert len(list(csv.DictReader((tmp_path/"tables/T2_prediction.csv").open())))==2
    assert len(list(csv.DictReader((tmp_path/"tables/S1_prediction_sensitivity.csv").open())))==17
    assert report["calibration_status"]=="not_run"
    assert "not_run" in (tmp_path/"tables/S4_calibration.csv").read_text()
    assert len(report["tables"]["T1"]["variables"])>=6


def test_private_kind_is_preserved_and_overwrite_refused(workflow,tmp_path):
    _,result=workflow
    write_paper_report(result,tmp_path,figures=False)
    private=deepcopy(result);private["input_dataset_kind"]="private_empirical"
    with pytest.raises(ValueError,match="overwrite_different"):
        write_paper_report(private,tmp_path,figures=False)
    report=write_paper_report(private,tmp_path/"private",figures=False)
    assert report["dataset_kind"]=="private_empirical" and report["exportable"] is False
    assert "not authorized" in report["notice"]


def test_missing_profiles_are_explicit_not_substituted(workflow,tmp_path):
    _,result=workflow
    missing=deepcopy(result)
    missing["cohort_selection_summary"]={"status":"not_available","variables":[],"categorical":[],"reason":"profiles absent"}
    report=write_paper_report(missing,tmp_path,figures=False)
    assert report["tables"]["T1"]["status"]=="not_available"
    assert "not_available" in (tmp_path/"tables/T1_cohort_profiles.csv").read_text()


def test_quality_count_table_preserves_source_and_missingness(workflow,tmp_path):
    result=deepcopy(workflow[1])
    result["cohort_selection_summary"]["producer_supplied_quality_counts"]={"min_complete_events_per_side":25,"heuristic_review_participants":14,"automatic_exclusions":0}
    report=write_paper_report(result,tmp_path,figures=False)
    rows={r["metric"]:r for r in csv.DictReader((tmp_path/"tables/S3_quality_counts.csv").open())}
    assert rows["primary_n"]["value"]=="25" and rows["primary_n"]["source"]=="bundle_count"
    assert rows["min_complete_events_per_side"]["value"]=="25" and rows["min_complete_events_per_side"]["source"]=="producer_supplied"
    assert rows["automatic_exclusions"]["value"]=="0"
    assert rows["mot_channel_series_screened"]["value"]=="" and rows["mot_channel_series_screened"]["source"]=="not_provided"
    assert len(report["numerical_diagnostics"]["quality_summary"])==len(rows)
    assert "does not independently recheck raw signals" in (tmp_path/"tables/S3_quality_counts.md").read_text()


def test_local_view_whitelist_has_no_raw_provenance(workflow,tmp_path):
    bundle,result=workflow
    contaminated=deepcopy(result)
    contaminated["source_path"]="/private/raw.xml"
    contaminated["source_sha256"]="not-to-be-copied"
    contaminated["external_link"]="https://example.invalid"
    contaminated["configuration"]["external_link"]="https://example.invalid"
    local=write_local_view(bundle,contaminated,tmp_path/"local.json")
    assert local["schema_version"]=="scm-strategy.local-study/1"
    assert local["local_only"] and local["exportable"] is False and local["upload_allowed"] is False
    assert len(local["primary_participants"])==25 and len(local["analyses"])==22
    assert local["configuration"]["executed_bootstrap_replicates"]==12
    assert "external_link" not in local["configuration"]
    serialized=json.dumps(local)
    assert "source_sha256" not in serialized and "raw.xml" not in serialized and "https://" not in serialized
    private_bundle=deepcopy(bundle);private_bundle["metadata"]["dataset_kind"]="private_empirical"
    with pytest.raises(ValueError,match="dataset_kind_mismatch"):
        build_local_view_payload(private_bundle,result)


def test_calibration_reference_is_independent_and_agrees():
    rng=np.random.default_rng(12)
    x=np.column_stack([np.ones(24),rng.normal(size=(24,4))]);y=x@np.array([5,.1,-.2,.05,.03])+rng.normal(0,.2,24)
    beta,smear=_reference_fit(x,y);fitted=fit_ols(x,y,inference=False)
    np.testing.assert_allclose(beta,fitted.beta,rtol=1e-10,atol=1e-10)
    np.testing.assert_allclose(smear,fitted.smear,rtol=1e-10,atol=1e-10)


def test_real_computation_for_small_calibration_and_all_four_figures(workflow,tmp_path):
    pytest.importorskip("matplotlib")
    calibration=run_calibration(tmp_path/"cal",datasets=2,bootstrap_replicates=10,mc_training_sets=20,mc_test_people=25,workers=1,figures=True)
    assert calibration["configuration"]["matches_full_paper_calibration_sizes"] is False
    assert len(calibration["summary"])==2
    assert all(s["datasets_with_interval"]==2 for s in calibration["summary"])
    assert len(list(csv.DictReader((tmp_path/"cal/calibration_datasets.csv").open())))==4
    report=write_paper_report(workflow[1],tmp_path/"report",calibration=tmp_path/"cal/calibration.json")
    assert report["figures"]["F4"]["panels"]==["A","B","C","D"]
    assert len(report["figures"]["F1"]["selection"])==9
    assert len(list(csv.DictReader((tmp_path/"report/tables/S4_calibration.csv").open())))==2
    assert all(r["dataset_kind"]=="synthetic" for r in csv.DictReader((tmp_path/"report/tables/S4_calibration.csv").open()))
    for name in ["F1_cohort_flow_selection","F2_prediction_sensitivity","F3_morphology_associations","F4_measurement_calibration"]:
        assert (tmp_path/"report/figures"/(name+".png")).stat().st_size>1000
        assert (tmp_path/"report/figures"/(name+".svg")).stat().st_size>1000


def test_cli_one_command_report_and_local_view(tmp_path):
    pytest.importorskip("matplotlib")
    from scm_strategy.cli import main
    out=tmp_path/"one-command"
    local=out/"local-view.json"
    code=main(["paper-demo","--out",str(out),"--bootstrap","10","--skip-design-audit", "--report","--local-view",str(local)])
    assert code==0
    report=json.loads((out/"paper-report.json").read_text())
    view=json.loads(local.read_text())
    assert len(report["tables"]["T2"])==17 and len(report["coefficients"])==159
    assert view["dataset_kind"]=="synthetic" and view["exportable"] is False
    assert report["figures"]["F4"]["calibration_status"]=="not_run_no_values_imputed"
