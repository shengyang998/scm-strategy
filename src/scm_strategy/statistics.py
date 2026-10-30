# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 SCM Research contributors. New project contribution.
"""Small-sample numerical core. No file I/O or data-dependent model selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.stats import t


class NumericalFailure(ValueError):
    pass


@dataclass
class OLS:
    beta: np.ndarray
    covariance_hc3: np.ndarray
    residual: np.ndarray
    fitted: np.ndarray
    leverage: np.ndarray
    sigma2: float
    df: int
    rank: int
    condition_number: float
    smear: float


def fit_ols(x: np.ndarray, y: np.ndarray, inference: bool = True) -> OLS:
    """Fit with an intercept in column zero; internally center and scale X.

    Returned coefficients and covariance use the ORIGINAL design coordinates.
    Replicated participant rows implement frequency weights exactly.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 2 or y.shape != (len(x),) or not len(x):
        raise NumericalFailure("invalid dimensions")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise NumericalFailure("nonfinite input")
    if not np.allclose(x[:, 0], 1):
        raise NumericalFailure("first design column must be intercept")
    n, p = x.shape
    means = x[:, 1:].mean(axis=0)
    scales = x[:, 1:].std(axis=0, ddof=0)
    if np.any(scales <= np.finfo(float).eps):
        raise NumericalFailure("constant non-intercept design column")
    z = np.column_stack([np.ones(n), (x[:, 1:] - means) / scales])
    gamma, _, rank, singular = np.linalg.lstsq(z, y, rcond=None)
    rank = int(rank)
    if rank < p or n <= p:
        raise NumericalFailure(f"rank/df failure: n={n}, p={p}, rank={rank}")
    transform = np.eye(p)
    if p > 1:
        transform[0, 1:] = -means / scales
        transform[1:, 1:] = np.diag(1 / scales)
    beta = transform @ gamma
    fitted = z @ gamma
    residual = y - fitted
    df = n - p
    sigma2 = float(residual @ residual / df)
    with np.errstate(over="ignore", invalid="ignore"):
        smear = float(np.exp(residual).mean())
    if not np.isfinite(smear):
        raise NumericalFailure("nonfinite Duan smearing factor")
    condition = float(singular[0] / singular[-1])
    cov = np.full((p, p), np.nan)
    leverage = np.full(n, np.nan)
    if inference:
        bread = np.linalg.inv(z.T @ z)
        leverage = np.sum((z @ bread) * z, axis=1)
        if np.any(1 - leverage <= 1e-10):
            raise NumericalFailure("unit leverage makes HC3 undefined")
        adjusted = residual / (1 - leverage)
        meat = (z * adjusted[:, None]).T @ (z * adjusted[:, None])
        cov = transform @ (bread @ meat @ bread) @ transform.T
        cov = (cov + cov.T) / 2
    return OLS(beta, cov, residual, fitted, leverage, sigma2, df, rank, condition, smear)


def coefficient_intervals(fit: OLS, level: float = .95) -> np.ndarray:
    se = np.sqrt(np.maximum(np.diag(fit.covariance_hc3), 0))
    radius = t.ppf((1 + level) / 2, fit.df) * se
    return np.column_stack([fit.beta - radius, fit.beta + radius])


def raw_predictions(fit: OLS, x: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore", invalid="ignore"):
        predictions = np.exp(np.asarray(x) @ fit.beta) * fit.smear
    if not np.isfinite(predictions).all():
        raise NumericalFailure("nonfinite original-scale predictions")
    return predictions


def loso(
    y_original: np.ndarray,
    x0: np.ndarray,
    x1: np.ndarray,
    ids: list[str],
    counts: np.ndarray | None = None,
    trace: bool = False,
) -> dict:
    """All copies of a bootstrap participant are held out together.

    Input rows must be unique participants. Counts represent bootstrap draws.
    Each fitted transformation and smear uses only the expanded TRAIN rows.
    """
    if len(ids) != len(set(ids)):
        raise NumericalFailure("source participant ids must be unique")
    y_original = np.asarray(y_original, float)
    if not np.isfinite(y_original).all() or np.any(y_original <= 0):
        raise NumericalFailure("log outcome must be positive")
    counts = np.ones(len(ids), dtype=int) if counts is None else np.asarray(counts, int)
    if counts.shape != (len(ids),) or np.any(counts < 0) or counts.sum() == 0:
        raise NumericalFailure("invalid participant multiplicities")
    active = np.flatnonzero(counts)
    log_y = np.log(y_original)
    predictions, traces = [], []
    for held in active:
        training = np.repeat(np.arange(len(ids)), counts * (np.arange(len(ids)) != held))
        base = fit_ols(x0[training], log_y[training], inference=False)
        aug = fit_ols(x1[training], log_y[training], inference=False)
        row = {
            "anonymized_id": ids[held], "multiplicity": int(counts[held]),
            "observed": float(y_original[held]),
            "mean_prediction": float(y_original[training].mean()),
            "baseline_prediction": float(raw_predictions(base, x0[held])),
            "augmented_prediction": float(raw_predictions(aug, x1[held])),
            "baseline_smear": base.smear, "augmented_smear": aug.smear,
            "training_n": len(training), "training_unique_n": len(set(training)),
        }
        predictions.append(row)
        if trace:
            traces.append({"heldout_id": ids[held], "training_ids": [ids[j] for j in training]})
    weights = np.array([r["multiplicity"] for r in predictions])
    actual = np.array([r["observed"] for r in predictions])
    metrics = {}
    for name in ("mean", "baseline", "augmented"):
        error = np.array([r[f"{name}_prediction"] for r in predictions]) - actual
        metrics[f"{name}_mae"] = float(np.average(np.abs(error), weights=weights))
        metrics[f"{name}_rmse"] = float(np.sqrt(np.average(error**2, weights=weights)))
    metrics["delta_mae_baseline_minus_augmented"] = metrics["baseline_mae"] - metrics["augmented_mae"]
    return {"metrics": metrics, "predictions": predictions, "trace": traces}


def bootstrap_analysis(
    y: np.ndarray,
    x0: np.ndarray,
    x1: np.ndarray,
    ids: list[str],
    replicates: int,
    seed: int,
    contrasts: list[tuple[np.ndarray, np.ndarray]] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    rng = np.random.default_rng(seed)
    n = len(ids)
    coefficients0, coefficients1, metrics, case_differences = [], [], [], []
    failures: dict[str, int] = {}
    distinct_ids = []
    for b in range(replicates):
        selected = rng.integers(n, size=n)
        counts = np.bincount(selected, minlength=n)
        distinct_ids.append(int(np.count_nonzero(counts)))
        try:
            cv = loso(y, x0, x1, ids, counts)
            f0 = fit_ols(x0[selected], np.log(y[selected]), inference=False)
            f1 = fit_ols(x1[selected], np.log(y[selected]), inference=False)
            coefficients0.append(f0.beta)
            coefficients1.append(f1.beta)
            metrics.append(cv["metrics"])
            case_differences.append([
                float(raw_predictions(f1, a) - raw_predictions(f1, c))
                for a, c in (contrasts or [])
            ])
        except (NumericalFailure, np.linalg.LinAlgError, FloatingPointError) as exc:
            key = str(exc)
            failures[key] = failures.get(key, 0) + 1
        if progress and ((b + 1) % 100 == 0 or b + 1 == replicates):
            progress(b + 1, replicates)
    return {
        "requested": replicates, "valid": len(metrics), "failures": failures,
        "bootstrap_distinct_participants": distinct_ids,
        "coefficients_baseline": np.asarray(coefficients0),
        "coefficients_augmented": np.asarray(coefficients1),
        "metrics": metrics, "case_differences": np.asarray(case_differences),
    }


def percentile_interval(values: np.ndarray, level: float = .95) -> list[float] | None:
    values = np.asarray(values)
    if len(values) < 10 or not np.isfinite(values).all():
        return None
    return np.quantile(values, [(1 - level) / 2, (1 + level) / 2], method="linear").tolist()


def containment_frontier(ci: list[float]) -> float:
    """Only for an additive difference whose null is ZERO, never a raw ratio."""
    return float(max(abs(ci[0]), abs(ci[1])))


def log_ratio_intervals(fit: OLS, a: np.ndarray, b: np.ndarray, level: float = .90) -> dict:
    """HC3 conditional geometric-mean ratio CI versus approximate individual PI.

    PI additionally assumes independent people, homoscedastic normal log errors.
    It is NOT an arithmetic-mean CI or a personal equivalence certificate.
    """
    contrast = np.asarray(a) - np.asarray(b)
    value = float(contrast @ fit.beta)
    var_mean = max(float(contrast @ fit.covariance_hc3 @ contrast), 0.)
    critical = float(t.ppf((1 + level) / 2, fit.df))
    r_mean = critical * np.sqrt(var_mean)
    r_individual = critical * np.sqrt(var_mean + 2 * fit.sigma2)
    return {
        "geometric_mean_ratio": float(np.exp(value)),
        "geometric_mean_ratio_ci90_hc3": np.exp([value - r_mean, value + r_mean]).tolist(),
        "approx_independent_individual_ratio_prediction_interval90": np.exp([value - r_individual, value + r_individual]).tolist(),
        "individual_prediction_assumptions": "independent individuals; homoscedastic normal log residuals; approximate t interval",
    }
