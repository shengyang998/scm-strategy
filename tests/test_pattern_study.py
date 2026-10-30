"""Independent arithmetic, boundary, randomization and end-to-end checks."""
from copy import deepcopy
from fractions import Fraction
import json

import numpy as np
import pytest

from scm_strategy.cli import main
from scm_strategy.pattern_bundle import read_pattern_bundle, write_pattern_bundle, validate_pattern_bundle
from scm_strategy.pattern_synthetic import generate_pattern_bundle
from scm_strategy.pattern_study import run_pattern_study, save_pattern_study
from scm_strategy import pattern_math as pm
from scm_strategy.pattern_view import build_pattern_view


def test_chamfer_against_independent_all_pairs_and_posture_shift():
    a = np.array([[0., 0.], [2., 0.], [3., 2.]])
    b = np.array([[0., 1.], [3., 3.]])
    square = np.square(a[:, None] - b[None, :]).sum(axis=2)
    expected = (square.min(axis=1).mean() + square.min(axis=0).mean()) / 4
    assert pm.chamfer_components(a, b).mean() == pytest.approx(expected)
    assert pm.chamfer_components(b, a).mean() == pytest.approx(expected)
    trace = np.column_stack([a, a * 1.3])
    shifted = trace + np.array([8., -3., 2., 7.])
    assert pm.bilateral_chamfer(trace, shifted, True)["chamfer_rms_deg"] == pytest.approx(0., abs=1e-14)
    assert pm.bilateral_chamfer(trace, shifted, False)["chamfer_rms_deg"] > 0


def test_migrated_hc3_has_independent_rational_reference():
    fit = pm.fit_model(np.arange(4.), [1., 2., 2., 4.])
    vectors = [[Fraction(7, 10), Fraction(-3, 10)], [Fraction(4, 10), Fraction(-1, 10)],
               [Fraction(1, 10), Fraction(1, 10)], [Fraction(-2, 10), Fraction(3, 10)]]
    weights = [Fraction(1, 9), Fraction(4, 49), Fraction(1), Fraction(16, 9)]
    expected = [[float(sum(w * v[i] * v[j] for w, v in zip(weights, vectors))) for j in range(2)] for i in range(2)]
    np.testing.assert_allclose(fit["beta"], [.9, .9])
    np.testing.assert_allclose(fit["covariance"], expected, atol=1e-12)


def test_whole_vector_permutations_never_cross_components_and_center_weights():
    v = np.arange(18).reshape(6, 3)
    groups = [np.array([0, 2, 4]), np.array([1, 3])]
    indices = pm.permute_vectors(v, groups, 17, 100)
    for row in indices:
        assert set(row[[0, 2, 4]]) == {0, 2, 4}
        assert set(row[[1, 3]]) == {1, 3}
        assert row[5] == 5
    x = np.array([2., 6., 8., 4.]); g = np.array([0, 0, 1, 1]); w = np.array([1., 3., 2., 1.])
    centered = pm.center_within(x, g, w)
    np.testing.assert_allclose(centered, [-3., 1., 4 / 3, -8 / 3])
    assert pm.weighted_r(centered, centered, w) == pytest.approx(1.)


def test_pair_graph_cardinality_precedes_large_body_distance():
    edges = [{"a": "A", "b": "B", "body_distance_full50_sd": 1.},
             {"a": "B", "b": "C", "body_distance_full50_sd": 100.},
             {"a": "C", "b": "D", "body_distance_full50_sd": 1.}]
    graph = pm.graph_summary(["A", "B", "C", "D", "E"], edges)
    assert graph["n_isolates"] == 1
    match = pm.body_only_matching(graph, edges, 22)
    assert [(r["a"], r["b"]) for r in match["pairs"]] == [("A", "B"), ("C", "D")]


def test_table_specific_contract_roundtrip_and_rejections(tmp_path):
    bundle = generate_pattern_bundle(16, 10, 99, 40)
    write_pattern_bundle(bundle, tmp_path)
    loaded = read_pattern_bundle(tmp_path)
    assert len(loaded["pressure_repeats"]) > len(loaded["participants"])
    assert any(r["primary_order"] is None for r in loaded["paired_trials"])
    np.testing.assert_array_equal(bundle["motion"]["values_deg"], loaded["motion"]["values_deg"])
    bad = deepcopy(bundle); bad["pressure_index"].append(bad["pressure_index"][0])
    with pytest.raises(ValueError, match="duplicate_key"):
        validate_pattern_bundle(bad)
    bad = deepcopy(bundle); bad["motion"]["channel_names"] = np.array(["a", "b", "c", "d"])
    with pytest.raises(ValueError, match="channel_order"):
        validate_pattern_bundle(bad)
    bad = deepcopy(bundle); bad["metadata"]["units"] = {**bad["metadata"]["units"], "values_deg": "radian"}
    with pytest.raises(ValueError, match="units"):
        validate_pattern_bundle(bad)
    bad = deepcopy(bundle); bad["paired_trials"][0]["primary_order"] = 100
    with pytest.raises(ValueError, match="primary_order"):
        validate_pattern_bundle(bad)


def test_all_fixed_families_and_missing_remain_explicit(tmp_path):
    bundle = generate_pattern_bundle(16, 10, 35, 40)
    result = run_pattern_study(bundle, bootstrap_replicates=8, permutations=19)
    assert len(result["static_bilateral"]["models"]) == 8
    assert len(result["motion_bilateral"]["models"]) == 6
    assert len(result["candidates"]["all_pairs"]) == 45
    assert result["arrays"]["body_permutation_indices"].shape == (19, 10)
    assert result["arrays"]["body_null_statistics"].shape == (19, 2)
    assert len(result["geometry"]["candidate_rows"]) == 6 * len(result["candidates"]["primary_edges"])
    payload = save_pattern_study(result, tmp_path)
    assert payload["exportable"] is False and "arrays" not in payload
    assert (tmp_path / "resampling_arrays.npz").exists()
    bad = deepcopy(bundle); bad["paired_trials"][0]["pressure_peak_N_left"] = None
    incomplete = run_pattern_study(bad, bootstrap_replicates=3, permutations=7)
    models = incomplete["motion_bilateral"]["models"]
    assert models["abs_peak_log_lr__primary"]["status"] == "not_estimable"
    assert models["abs_peak_log_lr__primary"]["n_people"] == 10
    assert incomplete["counts"]["primary"] == 10
    assert models["abs_area_log_lr__primary"]["status"] == "estimated"
    bad["metadata"]["dataset_kind"] = "private_empirical"
    with pytest.raises(ValueError, match="frozen_protocol"):
        run_pattern_study(bad, bootstrap_replicates=3)


def test_cli_demo_and_standardized_run(tmp_path, capsys):
    assert main(["pattern-demo", "--out", str(tmp_path / "demo"), "--participants", "16", "--primary-participants", "10", "--bootstrap", "3", "--permutations", "7", "--local-view", str(tmp_path / "local.json")]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["static_models"] == 8 and response["motion_models"] == 6
    assert response["dataset_kind"] == "synthetic"
    assert main(["pattern-study", str(tmp_path / "demo/input_bundle"), "--out", str(tmp_path / "replayed"), "--bootstrap", "3", "--permutations", "7"]) == 0
    capsys.readouterr()
    first = json.loads((tmp_path / "demo/pattern_study.json").read_text())
    second = json.loads((tmp_path / "replayed/pattern_study.json").read_text())
    assert first == second
    view = json.loads((tmp_path / "local.json").read_text())
    assert view["schema_version"] == "scm-strategy.pattern-local/1"
    assert len(view["associations"]) == 14
    assert len(view["records"][0]["trajectories"]["left"]["knee_deg"]) <= 2400


def test_display_projection_retains_kind_and_drops_arbitrary_metadata():
    bundle = generate_pattern_bundle(16, 10, 103, 40)
    result = run_pattern_study(bundle, bootstrap_replicates=3, permutations=7)
    bundle["metadata"]["description"] = "UNRELATED_PRIVATE_TEXT"
    bundle["metadata"]["quality_summary"] = {"unexpected": "UNRELATED_PRIVATE_TEXT"}
    result["dataset_kind"] = bundle["metadata"]["dataset_kind"] = "private_empirical"
    payload = build_pattern_view(bundle, result, 20)
    text = json.dumps(payload)
    assert payload["dataset_kind"] == "private_empirical"
    assert payload["local_only"] and not payload["exportable"] and not payload["upload_allowed"]
    assert payload["generator"] == {}
    assert "UNRELATED_PRIVATE_TEXT" not in text and "pair_id" not in text
    assert len(payload["records"][0]["trajectories"]["left"]["knee_deg"]) == 20


def test_default_display_preserves_2400_native_points_and_marks_real_simplification():
    bundle = generate_pattern_bundle(12, 8, 108, 2400)
    result = run_pattern_study(bundle, bootstrap_replicates=2, permutations=3)
    payload = build_pattern_view(bundle, result)
    record = payload["records"][0]
    assert len(record["trajectories"]["left"]["knee_deg"]) == 2400
    np.testing.assert_array_equal(record["trajectories"]["left"]["knee_deg"], bundle["motion"]["values_deg"][:2400, 0])
    assert record["trajectory_sampling"] == {"source_points": 2400, "display_points": 2400, "simplified": False}
    fewer = build_pattern_view(bundle, result, max_points=1200)["records"][0]
    assert fewer["trajectory_sampling"] == {"source_points": 2400, "display_points": 1200, "simplified": True}
    assert fewer["trajectories"]["left"]["knee_deg"][0] == record["trajectories"]["left"]["knee_deg"][0]
    assert fewer["trajectories"]["left"]["knee_deg"][-1] == record["trajectories"]["left"]["knee_deg"][-1]
    with pytest.raises(ValueError, match="display_point_limit"):
        build_pattern_view(bundle, result, max_points=2401)
