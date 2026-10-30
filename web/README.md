# SCM research workbench frontend

Buildless Chinese research interface using local HTML/CSS/JavaScript. The remote default remains synthetic-only. A separate, explicit file picker supports local private study viewing entirely in memory. No framework, third-party CDN, webfont, tracker, database, authentication, upload, persistence or data export is included. Site registration, browser QA and deployment belong to the project owner and are not performed here.

## Files and data boundary

- `index.html`, `styles.css`, `app.js`: interface and native SVG interactions.
- `data/demo.json`: package-owned output of the verified synthetic `export-web` command. This frontend does not generate or modify it. Supported schema: `scm-strategy.web/1`; dataset kind must be `synthetic`.
- `assets/F1...F4...png`: reviewed aggregate research figures copied byte-for-byte from the research figures directory. They contain no participant IDs or individual data points. Figure 4 includes explicitly labeled synthetic calibration panels.
- `assets/favicon.svg`: a self-authored local icon; include it in hosting staging.
- `fixtures/synthetic-local-study.json`: independent equation-generated local-view fixture, never automatically loaded by the app. It contains no empirical records.
- `app.test.cjs`, `test-dom.cjs`: dependency-free Node checks for both contracts, filters, selection limits, null values, DOM behavior, FileReader errors, storage/network isolation and clearing private state. The DOM double is not a browser implementation.

Run checks from this directory:

```sh
node --check app.js
node --test app.test.cjs
```

For the owner's local HTTP preview, serve this directory. Direct `file://` opening is not the supported data-loading path. The app requests only its own `data/demo.json` and static assets. A loading error does not fall back to fabricated records or hand-written model results.

## Interaction behavior

The sticky header marks the default interface **Synthetic demo / 合成演示**. In explicit local mode it changes to **本地私有研究 · 仅内存** and also states whether the file declares synthetic or private empirical input. Record counts, generator/seed or available protocol parameters are read from the active payload. Exact units are validated before rendering.

Speed and one selected body characteristic filter the fixed knee-versus-ankle SVG scatter. Axes and color scales use the full synthetic dataset, so filtering does not silently change their meaning. Numeric range limits are inclusive; missing or inverted limits give an explanatory empty state. The reset button restores the full view and clears comparison.

Click a point, or use the native participant picker, to add/remove a person. At most two synthetic records may be selected. A third selection prompts the user to remove one; it never silently replaces a record. Filtering retains selected records and labels those outside the current range. A/B comparison reports body, motion and pressure values with signed A-minus-B differences. The focus metric highlights one table row without hiding other measures.

The scatter has a roving keyboard focus: Tab enters, Left/Right browse by knee excursion, Home/End jump, Enter/Space select, and Escape clears comparison. Each point announces its synthetic ID, coordinates, color metric and selected state. The native dropdown offers an alternative on small touch screens. All other controls have labels and visible focus states. Motion respects reduced-motion settings.

Model summaries use the **whole synthetic dataset** and do not refit under filters. The outcome tabs display mean-only/M0/M1 MAE, signed ΔMAE, and nullable approximate bootstrap intervals. Positive/negative interval wording always stays within the synthetic-data scope. Null intervals are displayed as unavailable, never zero. A coefficient table explicitly remains on the log-outcome scale.

The default Research findings area is separately labeled **真实研究 · 仅聚合结果**. Its F1–F4 images are not synthetic participant outputs and are not changed by interactive filters. Native image dialogs support zoomed review, keyboard focus and Escape dismissal. Local mode hides these fixed figures so they cannot be mistaken for results of the loaded study.

## Local private study mode

Create the file with the package's `paper-study ... --local-view FILE` command. The picker accepts only `scm-strategy.local-study/1`, with `local_only=true`, `exportable=false`, `upload_allowed=false`, explicit units, standardized primary records and all 22 analysis states. This format is never accepted by the remote demo loader.

The user-selected file is size-checked (10 MiB maximum), then read through `FileReader` and parsed in memory. No upload or storage API is used; URLs in payload text are never turned into network requests, links, image sources or script resources. Only fixed, same-origin default assets are part of page loading. The file picker is cleared after each attempt. Invalid files leave the current view unchanged.

Local primary records drive the same scatter and two-person comparison. Missing motion/filter fields do not produce invented plotted values; affected records are absent from the current plotted subset, with full primary counts retained. The local study section lists all 17 predictive configurations and five morphology associations, coefficient/uncertainty tables, declared protocol parameters and aggregate repeated-measurement summaries. Non-estimable analyses and absent intervals/parameters are displayed explicitly. The UI does not refit models or infer absent execution settings from the protocol name.

“重置全部” resets filters and comparison within the current data source. “返回合成演示并清除私有数据” discards the local payload, records, selections and local result DOM, and restores the cached default demo. If the demo was not previously loaded, that explicit return may fetch the fixed demo URL. Returning also invalidates any pending local read. Refreshing the page naturally discards local state.

## Scientific limits retained in the interface

There is no good/bad running score, clinical classification or recommended intervention. Equal task speed does not establish equal outcomes. Contact time, pressure-derived peak load and effective loaded area are distinct observations, not measures of metabolic economy, injury risk or whole-body center of mass. Associations and within-session repeatability do not establish adaptation or causality. No practical equivalence threshold is invented.

## Browser QA handoff

For the 0.2.0 candidate, the project owner reported successful real-browser checks of desktop and 390px layouts, filtering and two-record selection, third-record rejection, Arrow/Enter/Escape interaction, outcome switching, figure dialogs, local-file loading of all 22 analyses, clearing back to the demonstration, and invalid-schema handling. The owner did not change the Web code or relax CSP. The checks below remain useful for subsequent releases.

The owner should verify desktop and phone layouts, keyboard point selection, range errors and reset, a third-person selection attempt, retained out-of-filter comparisons, outcome tabs, loading/retry failure, all four image dialogs, local-file error handling, local source labels and clearing on return. Automated checks do not substitute for browser interaction or screen-reader review. No browser was opened by this frontend task.
