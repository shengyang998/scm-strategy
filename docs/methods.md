# Numerical methods and limits

`statistics.py` preserves the numerical semantics of the new research core: internal centering/scaling, coefficients and HC3 covariance mapped back to original coordinates, Student-t intervals with residual degrees of freedom, original-scale log-model predictions using training-only Duan smearing, and leave-one-participant-out validation. Bootstrap multiplicities are frequency weights; all copies of a held-out identity are removed from training. Rank, constant-column and undefined-leverage failures remain explicit, with bootstrap failures counted rather than replaced by favorable draws.

The generic `analyze` command runs two comparisons: `log(contact_ms) ~ log(speed_kmh)+log(height_cm)` and `log(pressure_peak_N) ~ log(speed_kmh)+log(weight_kg)`. Each augmented model adds knee and ankle excursion divided by ten. The separate `paper-study` workflow runs all 17 fixed predictive configurations, five association models, measurement summaries and numerical design checks. Its report regenerates the main/supplementary tables and four aggregate figures from standardized inputs; see [paper reproduction](paper-reproduction.md).

Reported improvement is baseline MAE minus augmented MAE, in the original outcome unit. Positive improvement is predictive information in this dataset, not an intervention effect. Sample size, poor conditioning, selection, correlated measurement errors and unmeasured conditions remain limitations. Source decoding, synchronization and source-level QC remain the responsibility of a lawful external adapter.

Effective area uses `F=a*sum(p)` and `Aeff=a*sum(p)^2/sum(p^2)`. Event area is `sum(F*Aeff*dt)/sum(F*dt)`; zero-load frames have no weight. It is invariant to zero padding, cell permutation and common pressure-amplitude scaling. It mixes active contact area and pressure concentration and does not measure tissue stress, injury dose or metabolic cost.

Motion amplitude is P95−P5 by default, using linear quantiles, separately per side and then equally averaged. It is not full range of motion. Model joint axes, coordinate definitions, quality, sampling, filtering and window interpretation remain the input producer's responsibility.

No absence-of-significance rule establishes equivalence. The low-level interval/frontier utilities retain the distinction between conditional mean uncertainty and an approximate individual prediction interval. No clinical equivalence margin, injury label, quality score or causal compensation claim is supplied.

The synthetic generator's explicit equations are software exercises, not evidence. Their designed coefficients, ranges and noise are independently chosen and must not be cited as population estimates.

