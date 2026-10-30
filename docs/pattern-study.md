# Pattern study: standardized-input reproduction

`pattern-study` is the exploratory pattern/pressure workflow. `paper-study` and
all 0.2 commands remain unchanged. This is a numerical reproduction boundary,
not a device reader, source-level QC reconstruction, or independent validation
of musculoskeletal coordinates. No input grants permission to publish records.

## Commands and API

```
scm-strategy pattern-demo --out runs/pattern-demo --bootstrap 40 --permutations 99
scm-strategy pattern-study authorized-pattern-bundle --out runs/private-pattern
scm-strategy pattern-study authorized-pattern-bundle --out runs/private-pattern --local-view runs/private-pattern/local-view.json
```

`read_pattern_bundle(directory)` / `write_pattern_bundle(bundle, directory)`
use `scm_strategy.pattern_bundle`. The in-memory bundle has `metadata`, four
row-list tables named below, and `motion` containing NumPy arrays. Call
`scm_strategy.pattern_study.run_pattern_study(bundle)` then
`save_pattern_study(result, directory)`. Results default to private empirical,
are local-only and non-exportable through `export-web`. Reduced resampling is
allowed only for independently generated synthetic input.

## Files, order, keys and units

`bundle.json` has `schema_version: scm-strategy.pattern-bundle/1`,
`dataset_kind: private_empirical | synthetic`, the exact `units` mapping from
`pattern_bundle.UNITS`, and `recording_scope` (plain text description).
Optional `quality_summary` contains aggregate producer-supplied counts only;
it does not certify a new source audit. Optional `generator` identifies the
independent synthetic equations/seed. No path, source hash, URL or raw signal
metadata is necessary. Table order is meaningful for reproducing random draws.

|Table|Unique key|Required fields besides key|
|---|---|---|
|`participants.csv`|`participant_id`|`height_cm`, `weight_kg`, `navicular_ratio`, `navicular_height_left_mm`, `navicular_height_right_mm`, `foot_length_left_mm`, `foot_length_right_mm`, `forefoot_width_left_mm`, `forefoot_width_right_mm`|
|`pressure_index.csv`|`participant_id` (one per body row)|`trial_id`, `speed_kmh`, `contact_ms`, four bilateral pressure fields below|
|`pressure_repeats.csv`|`participant_id, trial_id`|`replicate_index`, `speed_kmh`, `contact_ms`, four pressure fields, `available`, `direction`, `window_duration_s`, `n_left_events`, `n_right_events`|
|`paired_trials.csv`|`pair_id`|`participant_id`, `replicate_index`, `speed_kmh`, `is_primary`, `primary_order`, `analysis_order`, `window_start_s`, `window_end_s`, `contact_ms`, four pressure fields, `motion_status`, `qc_status`, `available`, `direction`, `n_left_events`, `n_right_events`|

Four bilateral pressure fields: `pressure_peak_N_left`,
`pressure_peak_N_right`, `effective_area_cm2_left`,
`effective_area_cm2_right`. They are already accepted-event side medians inside
the specified common window (or the selected pressure-index window). This tool
does **not** repeat event selection. Bilateral means are calculated here.

Body rows are the full pressure cohort used for sample SD (`ddof=1`); primary
rows are a subset. `navicular_ratio` is the stored bilateral mean relative
navicular height and is checked against the supplied side measurements.
The static exposure is recomputed from the side measurements. Other body
quantities are not substituted or selected from outcomes.

`primary_order` is the zero-based order in the original primary table used by
the body-label permutation; it is null for non-primary rows and contiguous for
primary rows. `analysis_order` preserves the original paired-table order used
for the bilateral motion bootstrap. `pressure_index` row order preserves its
own analysis draw order. `replicate_index` and opaque trial/pair keys give the
predeclared chronological/tie order. IDs must be consistently remapped while
preserving any original tie ordering required by the producer.

`motion.npz` uses `allow_pickle=False`: `pair_ids[M]` strings,
`row_offsets[M+1]` integers, `values_deg[N,4]` float64, and
`channel_names = [knee_left, ankle_left, knee_right, ankle_right]`.
Each slice is the unchanged chronological, uniformly sampled common-window
model-coordinate data. No phase normalization, filtering, registration,
rotation or scaling is performed. Hip is not required. A missing motion row
has an empty slice and `motion_status=missing`; valid rows must be finite and
nonempty. This is an explicit preprocessed-array interface, not raw MOT/TRC.

Numeric nulls are blank CSV cells and remain missing. NaN/Inf text is rejected.
Booleans are `true`/`false`. IDs, linkage, counts and orders cannot be null;
`primary_order` is nullable only for non-primary rows. Positive physical values
are validated where present; signed model angles are allowed. Missing values
produce explicit row/spec failures or exclusions, never a hidden smaller graph.
No cohort is silently inferred from which outcomes happen to be present.

## Reproduction map and fixed numerical rules

|Existing result family|This workflow reproduces|Boundary|
|---|---|---|
|Candidate coverage|all primary unordered pairs; 0.10/0.15/0.25 km/h graphs, components/degrees; B+speed-only maximum-cardinality matching; raw differences|Eligibility is producer-supplied, not source QC. Edges are not independent people.|
|Angle-cloud geometry|raw/time-mean-centered bilateral knee–ankle Chamfer components; all near-speed edges and first/last true repeats; fixed 2×/4× subsampling after full-window centering|Ignores point order; same model coordinates, no independent kinematic validity.|
|Pressure proximity|whole-foot peak/area differences, same-session repeat scales and joint tolerance frontier|Descriptive, no SESOI or equivalence claim; common pressure origin.|
|Static bilateral analysis|two signed log(L/R) outcomes × primary/repeat-mean/log-speed/static-geometry models (8); HC3, 2,000 participant draws, primary LOO; repeat Sw/bias/LoA/sign tables|Uses standardized index/repeat summaries and measured side body values.|
|Motion bilateral analysis|raw/centered same-record L/R Chamfer; two absolute log(L/R) outcomes × three fixed specs (6); HC3, common 2,000 draws, LOO, paired repeats|Same-window pressure summaries must be supplied; never substitutes pressure-only index windows.|
|Final B–S test|full-cohort SD; fixed 0.15 graph; degree weights, within-component centering, complete body-vector permutations; centered primary/raw secondary; 9,999 indices and nulls|Whole-person labels within informative speed components; not independent edge tests or causal identification.|

Seed is 20261030 for each frozen family; it is not incremented by outcome.
Static outcomes each restart that seed; the six motion models share one draw
matrix. Body permutations preserve primary order and sorted graph-component
order. All configurations, failures and actual denominators are retained.
The runtime protocol is a data-independent package resource. Its historical
exploratory status does not become preregistration when packaged.

The scope excludes phase-anchored waveforms/clock stress, source marker
geometry, original XML integration, the external dataset pilot and clinical or
metabolic costs. Those are separate upstream or review artifacts, not silently
reproduced by reading derived pairwise distances. Here Chamfer is calculated
from the numeric coordinate arrays, not supplied pairwise answers.

All outputs are written locally. The package supplies no upload or private-data
export into a public demo. Synthetic demonstrations use independent equations
with visibly synthetic IDs; they are not estimates of real effects.

## Local display projection

`--local-view FILE` writes `scm-strategy.pattern-local/1`: fixed privacy flags,
input kind, necessary primary-record body/speed/pressure summaries, display-only
left/right knee–ankle traces, all 14 association states and coefficients,
aggregate geometry/repeats and the two body-label statistics. It does not
contain trial keys, source paths/hashes, raw signals or arbitrary URLs. At most
2,400 original-order points per trace are retained; only longer traces are simplified and labeled. The full arrays still
produce the statistics. It supplies no cost score and does not infer missing
metabolic data.

The browser accepts private projections only through explicit FileReader
selection. The fixed remote demo must declare the independent synthetic
generator and synthetic IDs. `export-web` retains its existing strict
legacy-recipe behavior and does not export pattern empirical data.
