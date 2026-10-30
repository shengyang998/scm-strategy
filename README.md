# SCM Strategy 0.2.0

Explicit-unit numerical features, the complete fixed paper-analysis workflow, and independent synthetic demonstrations. [Source repository](https://github.com/shengyang998/scm-strategy). This tree is a locally prepared 0.2.0 release candidate; packaging it does not upload or publish a release.

## Install and run a full synthetic study

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required. From a source checkout or extracted source archive:

```sh
uv sync --extra paper --frozen
uv run --no-sync scm-strategy paper-demo --out runs/paper-smoke --participants 50 --primary-participants 25 --seed 20261030 --bootstrap 40 --skip-design-audit --report --local-view runs/paper-smoke/local-view.json
```

This command generates an independent standardized multi-table bundle and executes all **22 fixed analyses**: 17 predictive configurations and five morphology associations. It produces tables, aggregate figures and a local-view payload. Forty bootstrap draws and an omitted design audit make this a quick installation check, not a full uncertainty analysis. Omit `--bootstrap 40 --skip-design-audit` to use the fixed 2,000 draws and full design audit. Reduced draws are accepted only for synthetic input.

The `paper` extra adds Matplotlib for reports; the numerical core requires only NumPy and SciPy. Synthetic equations, seed and parameters are explicit and do not sample or fit real participant data. The teaching bundle mirrors data *structure*, not empirical values.

## Reproduce the paper from authorized standardized data

Prepare the typed multi-table bundle described in [paper-study.md](docs/paper-study.md). It starts **after** lawful source decoding, synchronization, QC and feature construction. Pressure-only extension rows, repeated trials, fixed sensitivity specifications and optional cohort profiles have distinct schemas; missing values are explicit rather than imputed.

```sh
uv run --no-sync scm-strategy paper-study authorized_bundle --out runs/private-paper --report --local-view runs/private-paper/local-view.json
```

Empirical studies use the fixed 2,000 bootstrap draws. Every regression/CV specification uses the same paper seed. Outputs retain all analyses, failures, coefficient intervals, predictions, influence diagnostics, cases, repeatability and design checks. Reports generate T1–T4, S1–S4 and F1–F4 data; the calibration portion is explicitly unavailable until a computed calibration result is supplied.

To compute that separate, fixed Gaussian/lognormal calibration and include its panels/tables:

```sh
uv run --no-sync python -m scm_strategy.paper_report calibrate --out runs/calibration --datasets 100 --bootstrap 200 --mc-training 20000 --mc-test 1000 --workers 2
uv run --no-sync scm-strategy paper-study authorized_bundle --out runs/private-paper --report --calibration runs/calibration/calibration.json --local-view runs/private-paper/local-view.json
```

The calibration is a separate simulation, not the interactive teaching-cohort generator. [Full reproduction instructions](docs/paper-reproduction.md) describe the inputs, outputs, units, missingness, calibration, reporting and private-view contracts. A completed run can be rendered again through `write_paper_report` without refitting models.

## General numerical APIs and compact demonstrations

`features.py` provides array-only effective area, force-weighted event aggregation and bilateral percentile excursion. `statistics.py` provides centered/scaled OLS, HC3 intervals, training-only Duan retransformation, grouped LOSO and participant bootstrap. Importing the core does not load data or configuration files.

For the smaller single-table API:

```sh
uv run --no-sync scm-strategy demo --out runs/compact-demo --participants 60 --seed 20261030 --bootstrap 40
uv run --no-sync scm-strategy validate runs/compact-demo/participants.csv --metadata runs/compact-demo/metadata.json
uv run --no-sync scm-strategy analyze participants.csv --metadata metadata.json --out runs/private-compact
uv run --no-sync scm-strategy export-web runs/compact-demo --out runs/demo-web.json
```

The generic `analyze` command intentionally runs only the two main-model comparisons; use `paper-study` for the full paper. It defaults to `private_empirical`. Its [single-table contract](docs/data-contract.md) is separate from the paper bundle.

`export-web` only permits a complete input matching the supported independent synthetic recipe. It regenerates the data and recomputes the public results rather than forwarding stored reports, arbitrary metadata, paths, logs or private hashes. A `synthetic` label alone is insufficient. Full paper runs remain non-exportable through this command.

## Browser interface and local-only view

```sh
python -m http.server 8765 --directory web
```

Open the local server in a browser. The default data are synthetic. The separate local-file control can load a generated `local-view.json` into memory, with no upload or persistence; returning to the demonstration clears the local data. [Viewer instructions](web/README.md) and the [Web JSON contract](docs/web-contract.md) describe the boundary. Reviewed aggregate research figures are separate from synthetic participant records.

## Test and build

```sh
uv run --no-sync pytest
node --test web/app.test.cjs
uv build --out-dir wheelhouse
uv venv wheel-test
uv pip install --python wheel-test/bin/python 'wheelhouse/scm_strategy-0.2.0-py3-none-any.whl[paper]'
wheel-test/bin/scm-strategy paper-demo --out runs/installed-smoke --bootstrap 12 --skip-design-audit --report --local-view runs/installed-smoke/local-view.json
```

Development environments, caches, logs and runs are not release sources. The exact source allowlist and source-distribution inclusion list exclude them; a release audit must still check the actual wheel/archive and synthetic fixtures.

## Interpretation and data boundaries

Association, predictive improvement and repeatability are distinct. No output establishes causal compensation, metabolic economy, injury protection, a universal running score or substantive equivalence. [Methods](docs/methods.md) preserve these limits.

Device readers, raw data, real participant records, videos and private provenance are excluded. Standardized empirical inputs require authorization and a correct upstream adapter; the package does not recreate source-level QC or grant data access. [Data availability](docs/data-availability.md) distinguishes synthetic reproducibility from empirical reproducibility. The BSD-3-Clause license covers new project contributions only; [third-party notices](THIRD_PARTY_NOTICES.md) retain dependency boundaries. The collective citation author is a project placeholder, not a fabricated person or institution.
