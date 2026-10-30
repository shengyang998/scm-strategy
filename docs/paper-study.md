# Frozen paper study: standardized bundle → all analyses

`paper-study` is separate from the generic `analyze` command. Generic analysis and its synthetic web export retain their existing behavior; they are not the paper reproduction interface. Paper mode uses the same seed, 20261030, for **every** one of the 17 prediction configurations and five association models. The earlier two-model demonstration uses a different per-outcome seed policy.

This interface starts with already standardized, authorized feature tables. It does not open device XML/MOT files, reconstruct source QC, verify camera tracking, apply synchronization, or generate the 20-second windows. A private or independently licensed adapter is responsible for those operations. The package contains no copied device readers.

## Python API and CLI

```python
from scm_strategy.paper_bundle import read_paper_bundle, write_paper_bundle, validate_paper_bundle
from scm_strategy.paper_study import run_paper_study, save_paper_study

bundle = read_paper_bundle("authorized_bundle")
result = run_paper_study(bundle)  # 2,000 draws; all configurations and design audit
save_paper_study(result, "private_paper_run")
```

```sh
scm-strategy paper-study authorized_bundle --out private_paper_run
scm-strategy paper-study authorized_bundle --out private_paper_run --report
scm-strategy paper-demo --out synthetic_paper_run --bootstrap 20 --report
```

Rendering requires the `paper` extra: run `uv sync --extra paper --frozen` from a source checkout, or install the built local wheel with `[paper]`. `--calibration FILE` supplies an independently generated calibration result to the report; it never inserts old empirical or synthetic results. Reduced bootstrap counts are accepted only for explicitly synthetic input and are labeled as incomplete relative to the frozen draw count. `--skip-design-audit` marks the fold audit as not run; it does not pretend that the full diagnostic output exists.

`--local-view FILE` writes a separate local-only, non-exportable viewer payload. `paper-demo --seed` controls the independent input generator; it does not replace the fixed paper-analysis seed. Saved run manifests carry a private digest of the normalized input bundle for reproducibility.

`run_paper_study(bundle, *, bootstrap_replicates=None, progress=None, include_design_audit=True)` accepts a dictionary or a directory. The callback receives `(analysis_label, completed_draws, total_draws)`. The return object has:

- `schema_version="scm-strategy.paper-study/1"`, protocol ID, configuration, `dataset_kind="private_empirical"`, `input_dataset_kind`, and `exportable=false`;
- `analyses`: all 22 model objects, with names matching the paper's original result stems;
- `summary`: all analysis states, sample sizes, predictions and interval summaries;
- `case_selection`: fixed body/speed selection, selection metadata and private observed profiles;
- `measurement_summary`: full and primary-subset pressure repeatability, all declared exclusions, and optional descriptive motion repeats;
- `cohort_selection_summary`: separate cohort-profile SMDs and index-trial descriptive statistics;
- `numerical_design`: full, LOSO and bootstrap-fold rank/condition/distinct-person diagnostics, or an explicit `not_run` state;
- `input_validation`: missing values and table row counts. Missing values are never imputed.

Saving preserves the original per-model JSON names, `analysis_summary.json`, `case_selection.json`, `measurement_summary.json`, `cohort_selection_summary.json`, `numerical_design_audit.json`, a combined `paper_study.json`, all coefficient rows, and a private run manifest. `export-web` is deliberately not a paper-run exporter. Even a synthetic paper demonstration is saved with a private run manifest; its `input_dataset_kind` identifies its actual source.

## Bundle manifest

The directory contains `bundle.json` and table CSVs. Filenames may differ if explicitly mapped; absolute paths and paths escaping the bundle directory are rejected.

```json
{
  "schema_version": "scm-strategy.paper-bundle/1",
  "protocol_id": "scm-strategy-pressure/1.0.0",
  "dataset_kind": "private_empirical",
  "units": {"speed_kmh":"km/h", "height_cm":"cm", "weight_kg":"kg", "age_years":"year", "navicular_ratio":"1", "foot_size_proxy_cm2":"cm^2", "knee_excursion_deg":"degree", "ankle_excursion_deg":"degree", "contact_ms":"ms", "pressure_peak_N":"N", "effective_area_cm2":"cm^2", "bmi":"kg/m^2", "body_fat_pct":"%", "navicular_height_L_mm":"mm", "navicular_height_R_mm":"mm", "subject_median_speed_kmh":"km/h"},
  "tables": {
    "primary":"primary_participants.csv",
    "extension":"extension_participants.csv",
    "sensitivities":"sensitivity_participants.csv",
    "pressure_repeats":"nonfirst_backward_trials.csv",
    "paired_trials":"all_paired_trials.csv",
    "cohort_profiles":"cohort_profiles.csv"
  }
}
```

`dataset_kind` defaults to `private_empirical` if omitted. Optional metadata includes a synthetic generator recipe and explanatory notices, `cohort_counts`, and `quality_counts`. The in-memory equivalent is `{"metadata": <manifest without tables>, "primary": [...], ...}`. `paper_bundle_schema()` provides a JSON Schema; Python validation additionally enforces relational and conditional rules.

## Table grains and columns

The common trial columns are `participant_id`, `trial_id`, `trial_index`, `direction`, `available`, `exclusion_reason`. IDs are opaque local strings, not filenames or identities. `trial_index` is a positive integer. `direction` is exactly `backward`, the acquisition orientation used by this paper (not backward running). `available` is a typed boolean; CSV uses `True`/`False`. Unavailable records require a nonempty reason.

The 11 numeric feature columns are `speed_kmh`, `height_cm`, `weight_kg`, `age_years`, `navicular_ratio`, `foot_size_proxy_cm2`, `knee_excursion_deg`, `ankle_excursion_deg`, `contact_ms`, `pressure_peak_N`, `effective_area_cm2`. Units must exactly match the manifest. A number, when supplied, must be finite and positive; empty CSV values or JSON null are retained as missing and reported. Zero is not a missing-value code.

| Table | Key / grain | Exact additional columns |
| --- | --- | --- |
| `primary` | one index pair per `participant_id` | All 11 numeric features; `qc_status` |
| `extension` | one pressure index trial per `participant_id` | The nine numeric features **excluding knee and ankle**; no motion/QC placeholders |
| `sensitivities` | one row per `(spec, participant_id)` | All 11 features; `qc_status`; `spec` |
| `pressure_repeats` | one row per `(participant_id, trial_id)` | Only `speed_kmh`, `effective_area_cm2` |
| `paired_trials` (optional) | one row per `(participant_id, trial_id)` | All 11 features; `qc_status` |
| `cohort_profiles` (optional but required for full Table 1/Figure 1) | one row per extension `participant_id` | `height_cm`, `weight_kg`, `age_years`, `recorded_sex`, `bmi`, `body_fat_pct`, `navicular_height_L_mm`, `navicular_height_R_mm`, `subject_median_speed_kmh`; **no common trial columns** |

Column sets are table-specific, not a relaxed primary-participant schema. Unknown columns, duplicate keys, duplicate within-person repeat indices, unsupported units, and invalid kinds are rejected. Primary IDs must be a subset of extension IDs; sensitivity and paired IDs must belong to primary; repeat IDs must belong to extension. Cohort profiles, when present, must cover the extension exactly. Primary and extension observations for the same person may legitimately use different index trials.

An available paired row must contain both motion features. If a paired signal cannot supply them, retain the row as unavailable with its reason; this is different from a pressure-only extension, which has no motion columns at all. Other nullable values produce explicit model-specific missingness records. `recorded_sex="unknown"` is treated as missing for sex proportions, not as a third observed sex category.

`qc_status` is PASS or WARNING for available primary/paired/sensitivity rows. `participant_mean` may use MIXED_PASS_WARNING. Unavailable records may explicitly carry FAIL-MINOR, FAIL-MODERATE, FAIL-SEVERE or NOT_AVAILABLE. No failed record becomes available merely because a file parsed.

Sensitivity names are exactly `participant_mean`, `p10_p90`, `offset_m010`, `offset_p010`, `offset_m025`, `offset_p025`. Every primary person must have a row for every spec, using `available=false` and a reason when unavailable. This preserves failures instead of silently losing a sensitivity. `participant_mean` is a supplied aggregation over all eligible near-speed pairs; its `trial_index` may be null and its `trial_id` may be an aggregate identifier. Other rows require a real ordered trial index.

Row order is part of seeded numerical reproduction. Validation and CSV serialization preserve it. Do not reorder primary, extension or sensitivity rows after freezing. Repeated groups are ordered by participant ID, then trial index and trial ID; this reproduces the declared first/last comparison.

## Counts, profiles and incomplete information

`cohort_counts` may contain nonnegative integers `source_participants`, `source_pressure_trials`, `eligible_pressure_trials`, `pressure_excluded_trials`, `conservative_pair_count`, `eligible_nonfirst_backward_trials`. `quality_counts` may contain `min_complete_events_per_side`, `primary_PASS_count`, `primary_WARNING_count`, `source_exclusions`, `mot_participants_screened`, `mot_channel_series_screened`, `heuristic_review_participants`, `automatic_exclusions`. These are **producer-supplied audited summaries**; the paper runner does not reconstruct source-level quality checks or invent missing counts.

`recorded_sex` is F, M, other, unknown or null. The profile median speed refers to all relevant eligible pressure trials. It is not replaced by one extension trial's speed. Profile SMDs and index-trial descriptions are separate outputs. If profiles are absent, that output is marked unavailable, so a partial bundle cannot masquerade as full table/figure reproduction.

## Fixed analysis and interpretation

The 17 prediction results are primary, PASS-only, participant-mean, P10–P90, four offset perturbations (each with contact and peak outcomes), and age-for-height (contact only). Five additional results are the two body-to-motion associations and three pressure-extension associations. Full numerical output includes baseline, augmented and secondary coefficients (159 rows when all 22 are estimable), uncertainty, influence diagnostics, case mean contrasts and additive containment frontiers.

Models use the packaged data-independent `protocols/paper_v1.json`. The standardized bundle must already encode the required central windows, bilateral summaries, units, eligibility and sensitivity transformations; the runner does not regenerate them from unknown device formats. Nulls and unavailable rows have explicit per-model exclusions. Insufficient rank/sample size or high condition number retains a failed/stopped interpretation state without selecting another model.

Pressure repeats use all comparable rows from a person, require at least two available values and the whole-group speed range ≤0.15 km/h, and resample people. Full-repeat intervals use seed 20261030; the primary-subset repeat intervals use the separately frozen measurement seed 20261031. This measurement convention is distinct from the **same 20261030 seed for all 22 regression/CV analyses**.

Case selection uses speed and body variables only. A 90% mean-difference interval's containment bound is not a substantive equivalence margin. Model mean intervals, individual prediction intervals and repeat-measurement variability remain separate. No result establishes causal compensation, metabolic economy, injury protection or a universal running score.

Complete paper compatibility is an external acceptance step: matching two OLS fits or passing synthetic tests is not sufficient. Compare all 22 statuses, all 17 seeded prediction intervals, 159 coefficients, cases, repeatability and design matrices against an authorized independent oracle before making a reproduction claim.
