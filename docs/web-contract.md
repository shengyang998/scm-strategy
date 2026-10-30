# Synthetic Web JSON contract

`export-web RUN --out FILE` emits `scm-strategy.web/1`, described by `schemas/web-v1.schema.json`. The object contains only:

- `schema_version` and `dataset_kind="synthetic"`;
- generator version, integer seed and participant-count parameter;
- the fixed units dictionary and equation-generated participant records;
- two named outcome summaries: fixed-term coefficients/intervals, aggregate CV errors, bootstrap improvement interval and synthetic observed/predicted values;
- a synthetic-data disclaimer.

No input/output hash, filesystem path, log, arbitrary metadata, caller-supplied report text or raw run object is forwarded. Export requires a synthetic run manifest and a complete input matching the supported generator recipe. It then regenerates records and recomputes the statistics; changing stored `analysis.json` cannot inject a different result.

The frontend should label every view as a synthetic demonstration. `records` use opaque `SYN-` keys. `analysis.contact_ms` and `analysis.pressure_peak_N` contain arrays of predictions with `participant_id`, `observed`, `baseline_prediction` and `augmented_prediction`; use those keys to join synthetic records. `cross_validation.delta_mae_baseline_minus_augmented` is in the outcome unit. Intervals can be null when too few bootstrap draws are valid. Do not show a pass/fail clinical assessment or imply these records describe measured people.

