# Local-view test fixture

`synthetic-local-study.json` is generated entirely from the independent `scm-strategy.paper-equations/1` equations. It contains 30 synthetic source participants, a 25-person primary subset, input seed 314159, and the paper-study analysis with 12 bootstrap draws. The local-view export identifies its input as synthetic and reports that the executed draw count does not match the full frozen run.

It exists only for local-file UI and Node contract tests. The application never fetches it automatically. It contains no empirical observations or real participant IDs. Tests may remap its synthetic IDs or declaration to exercise private-mode behavior without introducing real records.

The exact generation and analysis parameters are recorded in `synthetic-local-study.recipe.json` for release-time regeneration checks.

The package-owned `web/data/demo.json` is separate and remains the strict synthetic-only remote default.
