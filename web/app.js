/* SPDX-License-Identifier: BSD-3-Clause */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SCMResearch = api;
  if (typeof document !== "undefined") {
    const start = () => api.mount(document);
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
    else start();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const METRICS = Object.freeze({
    speed_kmh: { label: "跑台速度", unit: "km/h", digits: 2, step: .1, group: "任务条件" },
    height_cm: { label: "身高", unit: "cm", digits: 1, step: .5, group: "身体条件" },
    weight_kg: { label: "体重", unit: "kg", digits: 1, step: .5, group: "身体条件" },
    age_years: { label: "年龄", unit: "岁", digits: 1, step: 1, group: "身体条件" },
    navicular_ratio: { label: "舟骨高度 / 足长", unit: "比值", digits: 3, step: .005, group: "身体条件" },
    foot_size_proxy_cm2: { label: "足部尺寸代理", unit: "cm²", digits: 1, step: 1, group: "身体条件" },
    knee_excursion_deg: { label: "膝幅度 P95 − P5", unit: "°", digits: 1, group: "动作指标" },
    ankle_excursion_deg: { label: "踝幅度 P95 − P5", unit: "°", digits: 1, group: "动作指标" },
    contact_ms: { label: "接触时长", unit: "ms", digits: 1, group: "压力结果" },
    pressure_peak_N: { label: "压力导出峰值", unit: "N", digits: 1, group: "压力结果" },
    effective_area_cm2: { label: "有效承载面积", unit: "cm²", digits: 1, group: "压力结果" }
  });
  const EXPECTED_UNITS = Object.freeze({ speed_kmh: "km/h", height_cm: "cm", weight_kg: "kg", age_years: "year", navicular_ratio: "1", foot_size_proxy_cm2: "cm^2", knee_excursion_deg: "degree", ankle_excursion_deg: "degree", contact_ms: "ms", pressure_peak_N: "N", effective_area_cm2: "cm^2" });
  const CV_KEYS = ["mean_mae", "mean_rmse", "baseline_mae", "baseline_rmse", "augmented_mae", "augmented_rmse", "delta_mae_baseline_minus_augmented"];
  const OUTCOMES = ["contact_ms", "pressure_peak_N"];
  const TERMS = { intercept: "截距", log_speed_kmh: "log 速度", log_height_cm: "log 身高", log_weight_kg: "log 体重", knee_excursion_deg_per10: "膝幅度 / 10°", ankle_excursion_deg_per10: "踝幅度 / 10°", age_years_per10: "年龄 / 10岁", navicular_ratio_per001: "舟骨比值 / 0.01", log_foot_size_proxy_cm2: "log 足部尺寸代理" };
  const LOCAL_MAX_BYTES = 10 * 1024 * 1024;
  const PREDICTION_SPECS = ["primary", "PASS_only", "participant_mean", "p10_p90", "offset_m010", "offset_p010", "offset_m025", "offset_p025", "primary_height_replaced_by_age"];
  const ASSOCIATIONS = ["body_to_knee", "body_to_ankle", "extension_contact", "extension_peak", "extension_area"];
  const LOCAL_ANALYSES = [...PREDICTION_SPECS.flatMap(spec => (spec === "primary_height_replaced_by_age" ? ["contact_ms"] : OUTCOMES).map(outcome => `${spec}__${outcome}`)), ...ASSOCIATIONS];
  const SPEC_LABELS = { primary: "主分析", PASS_only: "仅 PASS", participant_mean: "同人合格配对均值", p10_p90: "P10–P90 幅度", offset_m010: "偏移 −0.10 s", offset_p010: "偏移 +0.10 s", offset_m025: "偏移 −0.25 s", offset_p025: "偏移 +0.25 s", primary_height_replaced_by_age: "年龄替代身高", body_to_knee: "舟骨比值 → 膝幅度", body_to_ankle: "舟骨比值 → 踝幅度", extension_contact: "舟骨比值 → 接触时长", extension_peak: "舟骨比值 → 压力峰值", extension_area: "舟骨比值 → 有效面积" };
  const CONFIG_KEYS = ["seed", "bootstrap_replicates", "executed_bootstrap_replicates", "full_frozen_draw_count", "minimum_main_participants", "maximum_standardized_design_condition_number", "case_speed_caliper_kmh", "window_seconds"];
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const validInterval = value => value === null || (Array.isArray(value) && value.length === 2 && value.every(finite) && value[0] <= value[1]);

  function validateDataset(data) {
    const fail = message => { throw new Error(message); };
    if (!data || data.schema_version !== "scm-strategy.web/1" || data.dataset_kind !== "synthetic") fail("Only the supported synthetic dataset is accepted.");
    const top = ["schema_version", "dataset_kind", "generator", "units", "records", "analysis", "disclaimer"];
    if (Object.keys(data).some(key => !top.includes(key)) || top.some(key => !(key in data))) fail("Unexpected dataset envelope.");
    if (data.generator?.version !== "scm-strategy.equations/1" || !Number.isInteger(data.generator.seed) || data.generator.seed < 0) fail("Invalid synthetic generator.");
    const n = data.generator.parameters?.participants;
    if (!Number.isInteger(n) || n < 20 || n > 10000 || !Array.isArray(data.records) || data.records.length !== n) fail("Invalid synthetic participant count.");
    if (!data.units || Object.keys(EXPECTED_UNITS).some(key => data.units[key] !== EXPECTED_UNITS[key]) || Object.keys(data.units).length !== Object.keys(EXPECTED_UNITS).length) fail("Unexpected measurement units.");
    const ids = new Set();
    for (const row of data.records) {
      if (!row || !/^SYN-\d{5}$/.test(row.participant_id) || ids.has(row.participant_id)) fail("Invalid or duplicate synthetic ID.");
      ids.add(row.participant_id);
      if (Object.keys(row).some(key => key !== "participant_id" && !Object.hasOwn(METRICS, key))) fail("Unexpected participant fields.");
      if (Object.keys(METRICS).some(key => !finite(row[key]) || row[key] <= 0)) fail("Nonfinite or nonpositive measurement.");
    }
    for (const outcome of OUTCOMES) {
      const result = data.analysis?.[outcome];
      if (!result || result.unit !== METRICS[outcome].unit || CV_KEYS.some(key => !finite(result.cross_validation?.[key]))) fail("Invalid model summary.");
      if (CV_KEYS.filter(key => key !== "delta_mae_baseline_minus_augmented").some(key => result.cross_validation[key] < 0)) fail("Negative prediction error.");
      if (!validInterval(result.delta_mae_bootstrap_ci95) || !Array.isArray(result.coefficients) || !result.coefficients.length) fail("Invalid model interval.");
      if (result.coefficients.some(row => typeof row.term !== "string" || !finite(row.estimate) || !validInterval(row.hc3_ci95) || !validInterval(row.bootstrap_ci95))) fail("Invalid coefficient.");
      if (!Array.isArray(result.predictions) || result.predictions.length !== n) fail("Invalid prediction coverage.");
      const seen = new Set();
      for (const row of result.predictions) {
        if (!ids.has(row.participant_id) || seen.has(row.participant_id) || [row.observed, row.baseline_prediction, row.augmented_prediction].some(value => !finite(value) || value <= 0)) fail("Invalid synthetic prediction.");
        seen.add(row.participant_id);
      }
    }
    if (typeof data.disclaimer !== "string") fail("Missing synthetic disclaimer.");
    return data;
  }

  function extent(records, key) {
    const values = records.map(row => row[key]).filter(finite);
    if (!values.length) return [0, 1];
    let min = Infinity, max = -Infinity;
    for (const value of values) { min = Math.min(min, value); max = Math.max(max, value); }
    return [min, max];
  }

  function paddedExtent(records, key, fraction = .08) {
    const [min, max] = extent(records, key);
    const pad = (max - min || Math.max(Math.abs(min), 1) * .1) * fraction;
    return [min - pad, max + pad];
  }

  function filterRecords(records, filters) {
    if (![filters.speedMin, filters.speedMax, filters.bodyMin, filters.bodyMax].every(finite) || filters.speedMin > filters.speedMax || filters.bodyMin > filters.bodyMax || !METRICS[filters.bodyMetric]) return [];
    return records.filter(row => finite(row.speed_kmh) && finite(row[filters.bodyMetric]) && finite(row.knee_excursion_deg) && finite(row.ankle_excursion_deg) && row.speed_kmh >= filters.speedMin && row.speed_kmh <= filters.speedMax && row[filters.bodyMetric] >= filters.bodyMin && row[filters.bodyMetric] <= filters.bodyMax);
  }

  function toggleSelection(selection, id) {
    if (selection.includes(id)) return { ids: selection.filter(value => value !== id), full: false };
    if (selection.length >= 2) return { ids: selection.slice(), full: true };
    return { ids: [...selection, id], full: false };
  }

  function intervalSummary(interval) {
    if (interval === null) return "missing";
    if (!validInterval(interval)) throw new Error("Invalid interval.");
    return interval[0] > 0 ? "positive" : interval[1] < 0 ? "negative" : "uncertain";
  }

  function colorFor(value, domain) {
    if (!finite(value)) return "rgb(170,181,187)";
    const t = domain[1] === domain[0] ? .5 : Math.max(0, Math.min(1, (value - domain[0]) / (domain[1] - domain[0])));
    return `rgb(${[193, 222, 230].map((start, i) => Math.round(start + ([0, 88, 112][i] - start) * t)).join(",")})`;
  }

  function comparisonRows(a, b) {
    return Object.entries(METRICS).map(([key, metric]) => ({ key, ...metric, a: a?.[key] ?? null, b: b?.[key] ?? null, delta: finite(a?.[key]) && finite(b?.[key]) ? a[key] - b[key] : null }));
  }

  function format(value, digits = 1, signed = false) {
    if (!finite(value)) return "—";
    return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: 0, signDisplay: signed ? "exceptZero" : "auto" }).format(value);
  }

  function validateLocalPayload(data) {
    const fail = message => { throw new Error(message); };
    const object = value => value && typeof value === "object" && !Array.isArray(value);
    const exact = (value, allowed) => object(value) && Object.keys(value).every(key => allowed.includes(key));
    const top = ["schema_version", "dataset_kind", "local_only", "exportable", "upload_allowed", "notice", "protocol_id", "units", "primary_participants", "analyses", "measurement_summary", "cohort_selection_summary", "configuration"];
    if (!exact(data, top) || data.schema_version !== "scm-strategy.local-study/1" || !["synthetic", "private_empirical"].includes(data.dataset_kind) || data.local_only !== true || data.exportable !== false || data.upload_allowed !== false) fail("不支持的本地研究格式或隐私标志。");
    if (data.protocol_id !== "scm-strategy-pressure/1.0.0" || typeof data.notice !== "string" || data.notice.length > 4096) fail("本地研究协议或说明无效。");
    if (!object(data.units) || Object.keys(data.units).length !== Object.keys(EXPECTED_UNITS).length || Object.keys(EXPECTED_UNITS).some(key => data.units[key] !== EXPECTED_UNITS[key])) fail("本地研究单位不匹配。");
    if (!Array.isArray(data.primary_participants) || !data.primary_participants.length || data.primary_participants.length > 10000) fail("本地主表记录数无效。");
    const ids = new Set();
    for (const row of data.primary_participants) {
      if (!exact(row, ["participant_id", ...Object.keys(METRICS), "qc_status"]) || typeof row.participant_id !== "string" || !/^[A-Za-z0-9_.:|;-]{1,256}$/.test(row.participant_id) || ids.has(row.participant_id)) fail("本地主表编号无效或重复。");
      ids.add(row.participant_id);
      if (Object.keys(METRICS).some(key => !Object.hasOwn(row, key) || (row[key] !== null && (!finite(row[key]) || row[key] <= 0)))) fail("本地主表包含无效数值。");
      if (!["PASS", "WARNING", "FAIL-MINOR", "FAIL-MODERATE", "FAIL-SEVERE", "NOT_AVAILABLE"].includes(row.qc_status)) fail("本地主表缺少有效的 QC 状态。");
    }
    if (!object(data.analyses) || Object.keys(data.analyses).length !== 22 || LOCAL_ANALYSES.some(name => !Object.hasOwn(data.analyses, name))) fail("本地载荷必须保留全部 22 项分析状态。");
    const modelKeys = ["analysis", "outcome", "n", "input_n", "status", "controls", "strategy_terms", "terms", "outcome_logged", "cv_metrics", "cv_metric_bootstrap_ci95", "baseline_coefficients", "augmented_coefficients", "coefficients", "baseline_diagnostics", "augmented_diagnostics", "diagnostics", "predictions"];
    const coefKeys = ["term", "estimate", "hc3_se", "hc3_ci95", "hc3_ci90", "participant_bootstrap_ci95", "conditional_geometric_mean_ratio", "geometric_ratio_hc3_ci95"];
    for (const name of LOCAL_ANALYSES) {
      const model = data.analyses[name];
      if (!exact(model, modelKeys) || model.analysis !== name || !METRICS[model.outcome] || !Number.isInteger(model.n) || model.n < 0 || model.n > 100000 || !["estimated", "numerically_not_estimable", "not_estimable", "not_available"].includes(model.status)) fail("本地分析状态无效。");
      for (const field of ["controls", "strategy_terms", "terms"]) if (model[field] && (!Array.isArray(model[field]) || model[field].length > 32 || model[field].some(value => typeof value !== "string" || value.length > 128))) fail("本地模型项无效。");
      if (model.status === "estimated" && name.includes("__") && !model.cv_metrics) fail("已估计的本地预测模型缺少结果。");
      if (model.cv_metrics && (!exact(model.cv_metrics, CV_KEYS) || CV_KEYS.some(key => !finite(model.cv_metrics[key])))) fail("本地预测指标无效。");
      if (model.cv_metric_bootstrap_ci95 && (!exact(model.cv_metric_bootstrap_ci95, CV_KEYS) || Object.values(model.cv_metric_bootstrap_ci95).some(value => !validInterval(value)))) fail("本地预测区间无效。");
      for (const field of ["baseline_coefficients", "augmented_coefficients", "coefficients"]) if (model[field]) {
        if (!Array.isArray(model[field]) || model[field].length > 32 || model[field].some(row => !exact(row, coefKeys) || typeof row.term !== "string" || !finite(row.estimate) || ["hc3_ci95", "hc3_ci90", "participant_bootstrap_ci95", "geometric_ratio_hc3_ci95"].some(key => key in row && !validInterval(row[key])))) fail("本地回归系数无效。");
      }
      for (const field of ["baseline_diagnostics", "augmented_diagnostics", "diagnostics"]) if (model[field]) {
        const d = model[field], allowed = ["rank", "n_parameters", "residual_df", "standardized_design_condition_number", "max_leverage", "interpretation_gate_passed"];
        if (!exact(d, allowed) || Object.entries(d).some(([key, value]) => key === "interpretation_gate_passed" ? typeof value !== "boolean" : !finite(value))) fail("本地设计诊断无效。");
      }
      if (model.predictions) {
        if (!Array.isArray(model.predictions) || model.predictions.length > data.primary_participants.length) fail("本地预测记录数无效。");
        const seen = new Set();
        for (const row of model.predictions) { if (!exact(row, ["participant_id", "observed", "mean_prediction", "baseline_prediction", "augmented_prediction"]) || !ids.has(row.participant_id) || seen.has(row.participant_id) || ["observed", "baseline_prediction", "augmented_prediction"].some(key => !finite(row[key]))) fail("本地预测记录无效。"); seen.add(row.participant_id); }
      }
    }
    if (data.configuration !== undefined && (!exact(data.configuration, CONFIG_KEYS) || Object.entries(data.configuration).some(([key, value]) => key === "full_frozen_draw_count" ? typeof value !== "boolean" : !finite(value) || value < 0))) fail("本地协议参数无效。");
    if (data.configuration?.full_frozen_draw_count === true && data.configuration.executed_bootstrap_replicates !== undefined && data.configuration.bootstrap_replicates !== undefined && data.configuration.executed_bootstrap_replicates !== data.configuration.bootstrap_replicates) fail("本地运行次数与冻结标志矛盾。");
    if (!object(data.measurement_summary) || !object(data.cohort_selection_summary)) fail("本地聚合摘要无效。");
    return data;
  }

  function localDataView(payload) {
    const analysis = {};
    for (const outcome of OUTCOMES) {
      const model = payload.analyses[`primary__${outcome}`];
      analysis[outcome] = { unit: METRICS[outcome].unit, status: model.status, n: model.n, cross_validation: model.cv_metrics || {}, delta_mae_bootstrap_ci95: model.cv_metric_bootstrap_ci95?.delta_mae_baseline_minus_augmented ?? null, coefficients: (model.augmented_coefficients || []).map(row => ({ ...row, bootstrap_ci95: row.participant_bootstrap_ci95 ?? null })) };
    }
    return { records: payload.primary_participants, units: payload.units, analysis };
  }

  function readLocalFile(file, Reader = globalThis.FileReader) {
    if (!file || !finite(file.size) || file.size <= 0) return Promise.reject(new Error("请选择非空 JSON 文件。"));
    if (file.size > LOCAL_MAX_BYTES) return Promise.reject(new Error("文件超过 10 MiB 上限，未读取任何内容。"));
    if (typeof Reader !== "function") return Promise.reject(new Error("此浏览器不能读取本地文件。"));
    return new Promise((resolve, reject) => {
      const reader = new Reader();
      reader.onerror = () => reject(new Error("本地文件读取失败。"));
      reader.onabort = () => reject(new Error("本地文件读取已取消。"));
      reader.onload = () => { try { if (typeof reader.result !== "string") throw new Error(); resolve(validateLocalPayload(JSON.parse(reader.result))); } catch (error) { reject(new Error(error instanceof SyntaxError ? "文件不是有效 JSON。" : error.message || "本地研究载荷未通过检查。")); } };
      reader.readAsText(file, "utf-8");
    });
  }

  function mount(doc) {
    const $ = id => doc.getElementById(id);
    const create = (tag, text, className) => { const node = doc.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
    const svgNode = (tag, attrs, text) => { const node = doc.createElementNS("http://www.w3.org/2000/svg", tag); for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value); if (text !== undefined) node.textContent = text; return node; };
    const state = { data: null, remoteData: null, localPayload: null, mode: "demo", filtered: [], selected: [], bodyMetric: "height_cm", colorMetric: "contact_ms", detailMetric: "pressure_peak_N", outcome: "contact_ms", focusId: null, lastWidth: 0, request: 0, fileRequest: 0 };
    const ids = ["speed-min", "speed-max", "body-min", "body-max"];
    const recordKind = () => state.mode === "local" ? "本地记录" : "合成参与者";

    function renderMode() {
      const local = state.mode === "local";
      $("mode-badge").textContent = local ? "● 本地私有研究 · 仅内存" : "● Synthetic demo · 合成演示";
      $("mode-badge").classList[local ? "add" : "remove"]("is-local");
      $("return-demo").hidden = !local;
      $("intro-source-note").textContent = local ? "正在查看主动选择的本地研究文件。数据仅留在当前页面内存，不上传、不保存；返回合成演示会清除私有记录。" : "交互探索与模型演示使用方程生成的合成参与者；“研究发现”单独展示真实队列的聚合图表。";
      $("explorer-eyebrow").textContent = local ? "01 / LOCAL PRIVATE EXPLORER" : "01 / SYNTHETIC EXPLORER";
      $("explorer-description").textContent = `按任务速度与身体条件筛选，选择最多两名${recordKind()}进行描述性比较。`;
      $("explorer-source-tag").textContent = local ? "本地私有数据 · 不上传" : "合成个体 · 非测量数据";
      $("dataset-origin").textContent = local ? "本地文件 · 浏览器内存" : "方程生成的合成数据";
      $("filter-footnote").textContent = local ? "筛选更新散点与比较，不重拟合本地文件中的22项分析。缺少绘图字段的记录不显示为散点。" : "筛选更新散点与比较。下方模型结果始终来自完整合成样本。";
      $("empty-title").textContent = `没有匹配的${recordKind()}`;
      $("comparison-source-tag").textContent = local ? "Local / private" : "Synthetic";
      $("models-eyebrow").textContent = local ? "02 / LOCAL STUDY RESULTS" : "02 / SYNTHETIC MODEL RESULTS";
      $("models-title").textContent = local ? "本地主分析的模型表现" : "完整合成样本的模型表现";
      $("models-source-tag").textContent = local ? "文件中的结果 · 不重拟合" : "合成分析 · 不随筛选重拟合";
      $("coefficient-caption").textContent = local ? "当前本地主模型系数 · log 结果尺度" : "当前合成模型系数 · log 结果尺度";
      $("findings").hidden = local;
      $("local-study-results").hidden = !local;
      $("study-nav").textContent = local ? "全部分析" : "研究发现";
      $("study-nav").setAttribute("href", local ? "#local-study-results" : "#findings");
      if (!local) for (const id of ["local-protocol", "local-analysis-tables", "local-measurement", "local-model-details"]) $(id).replaceChildren();
    }

    function activateData(data, mode, payload = null) {
      state.data = data; state.mode = mode; state.localPayload = payload; state.outcome = "contact_ms";
      $("load-state").hidden = true; $("explorer-content").hidden = false; $("model-content").hidden = false; $("model-loading").hidden = true;
      $("dataset-meta").textContent = mode === "local" ? `主表 n = ${data.records.length} · 文件声明来源：${payload.dataset_kind === "synthetic" ? "独立合成" : "私有实证"}` : `n = ${data.records.length} · seed ${data.generator.seed} · ${data.generator.version}`;
      renderMode(); reset(); renderModels();
      if (mode === "local") renderLocalStudy(payload);
    }

    async function importFile(file) {
      const token = ++state.fileRequest;
      $("local-file-status").textContent = "正在内存中读取本地文件…"; $("local-file-status").classList.remove("is-error");
      try {
        const payload = await readLocalFile(file);
        if (token !== state.fileRequest) return false;
        ++state.request; // Ignore an older in-flight remote response.
        activateData(localDataView(payload), "local", payload);
        $("local-file-status").textContent = "本地私有研究已载入，仅在内存中查看。返回演示或刷新页面可清除。";
        $("local-file").value = "";
        return true;
      } catch (error) {
        if (token !== state.fileRequest) return false;
        $("local-file-status").classList.add("is-error");
        $("local-file-status").textContent = `${error.message} 当前视图未更改。`;
        $("local-file").value = "";
        return false;
      }
    }

    function returnToDemo() {
      ++state.fileRequest; ++state.request;
      state.localPayload = null; state.data = null; state.selected = []; state.filtered = []; state.focusId = null;
      $("local-file").value = ""; $("local-file-status").classList.remove("is-error");
      $("local-file-status").textContent = "私有记录与选择已从当前视图清除，正在使用合成演示。";
      for (const id of ["comparison-cards", "comparison-body", "point-details", "local-protocol", "local-analysis-tables", "local-measurement", "local-model-details", "scatter", "coefficient-body"]) $(id).replaceChildren();
      if (state.remoteData) activateData(state.remoteData, "demo");
      else { state.mode = "demo"; renderMode(); load(); }
    }

    function boundsFor(key) {
      const [min, max] = extent(state.data.records, key);
      const places = key === "navicular_ratio" ? 4 : 2;
      const factor = 10 ** places;
      return [Math.floor(min * factor) / factor, Math.ceil(max * factor) / factor];
    }

    function setBodyBounds() {
      const [min, max] = boundsFor(state.bodyMetric);
      for (const suffix of ["min", "max"]) {
        const input = $(`body-${suffix}`); input.step = METRICS[state.bodyMetric].step || 1;
        input.min = min; input.max = max; input.value = suffix === "min" ? min : max;
        input.setAttribute("aria-label", `${METRICS[state.bodyMetric].label}${suffix === "min" ? "最低" : "最高"}值，${METRICS[state.bodyMetric].unit}`);
      }
    }

    function reset() {
      if (!state.data) return;
      state.bodyMetric = "height_cm"; state.colorMetric = "contact_ms"; state.detailMetric = "pressure_peak_N";
      state.selected = []; state.focusId = null;
      $("body-metric").value = state.bodyMetric; $("color-metric").value = state.colorMetric; $("detail-metric").value = state.detailMetric; $("show-labels").checked = false;
      const speed = boundsFor("speed_kmh"); $("speed-min").value = speed[0]; $("speed-max").value = speed[1];
      $("speed-min").min = speed[0]; $("speed-max").max = speed[1];
      setBodyBounds(); update();
    }

    function currentFilters() {
      const values = ids.map(id => $(id).value.trim() === "" ? NaN : Number($(id).value));
      return { speedMin: values[0], speedMax: values[1], bodyMin: values[2], bodyMax: values[3], bodyMetric: state.bodyMetric };
    }

    function update() {
      if (!state.data) return;
      const filters = currentFilters(); state.filtered = filterRecords(state.data.records, filters);
      const invalid = ![filters.speedMin, filters.speedMax, filters.bodyMin, filters.bodyMax].every(finite) || filters.speedMin > filters.speedMax || filters.bodyMin > filters.bodyMax;
      const missingAxes = state.data.records.filter(row => !finite(row.knee_excursion_deg) || !finite(row.ankle_excursion_deg)).length;
      $("filter-feedback").textContent = invalid ? "请填写有效范围，最低值不能高于最高值。" : missingAxes ? `${missingAxes} 条主表记录缺少动作绘图字段，未绘为散点。` : "";
      $("visible-count").textContent = `${state.filtered.length} / ${state.data.records.length} 人`;
      $("filter-summary").textContent = invalid ? "筛选范围待修正" : `速度 ${format(filters.speedMin, 2)}–${format(filters.speedMax, 2)} km/h · ${METRICS[state.bodyMetric].label} ${format(filters.bodyMin, METRICS[state.bodyMetric].digits)}–${format(filters.bodyMax, METRICS[state.bodyMetric].digits)} ${METRICS[state.bodyMetric].unit}`;
      $("empty-state").hidden = state.filtered.length > 0;
      renderPicker(); renderChart(); renderSelection();
    }

    function renderPicker() {
      const picker = $("point-select"), previous = picker.value;
      picker.replaceChildren();
      for (const row of state.filtered) { const option = create("option", `${row.participant_id} · ${format(row.speed_kmh, 2)} km/h`); option.value = row.participant_id; picker.append(option); }
      if (state.filtered.some(row => row.participant_id === previous)) picker.value = previous;
      picker.disabled = !state.filtered.length; $("pick-person").disabled = !state.filtered.length;
    }

    function showPoint(row) {
      const node = $("point-details"), metric = METRICS[state.detailMetric]; node.replaceChildren();
      node.append(create("strong", `${row.participant_id} · ${state.mode === "local" ? "本地" : "合成"}`));
      node.append(create("span", `速度 ${format(row.speed_kmh, 2)} km/h`));
      node.append(create("span", `膝 ${format(row.knee_excursion_deg)}° / 踝 ${format(row.ankle_excursion_deg)}°`));
      if (state.mode === "local") node.append(create("span", `输入 QC：${row.qc_status}`));
      node.append(create("span", `${metric.label} ${format(row[state.detailMetric], metric.digits)} ${metric.unit}`, "detail-primary"));
    }

    function choose(id, keepFocus = false) {
      const changed = toggleSelection(state.selected, id);
      if (changed.full) { $("selection-status").textContent = `已选择两人。请先移出其中一人，再加入新的${recordKind()}。`; return; }
      state.selected = changed.ids; state.focusId = id;
      const row = state.data.records.find(row => row.participant_id === id); if (row) showPoint(row);
      renderChart(); renderSelection();
      if (keepFocus) focusPoint(id);
    }

    function focusPoint(id) {
      const circle = $("scatter").querySelector(`[data-record="${id}"]`);
      if (!circle) return;
      for (const point of $("scatter").querySelectorAll("[data-record]")) point.setAttribute("tabindex", "-1");
      circle.setAttribute("tabindex", "0"); circle.focus();
    }

    function renderChart() {
      const chart = $("scatter");
      const active = doc.activeElement?.getAttribute?.("data-record");
      const width = Math.max(260, $("scatter-container").clientWidth || 650), height = Math.max(300, Math.min(450, width * .57)); state.lastWidth = width;
      const margin = { left: 51, right: 18, top: 22, bottom: 52 }, plotWidth = width - margin.left - margin.right, plotHeight = height - margin.top - margin.bottom;
      chart.setAttribute("viewBox", `0 0 ${width} ${height}`); chart.style.height = `${height}px`; chart.replaceChildren();
      chart.setAttribute("aria-label", `${recordKind()}膝幅度与踝幅度散点图`);
      chart.append(svgNode("title", {}, `膝与踝幅度：${recordKind()}`));
      const xd = paddedExtent(state.data.records, "knee_excursion_deg"), yd = paddedExtent(state.data.records, "ankle_excursion_deg");
      const x = value => margin.left + (value - xd[0]) / (xd[1] - xd[0]) * plotWidth;
      const y = value => margin.top + (yd[1] - value) / (yd[1] - yd[0]) * plotHeight;
      for (let tick = 0; tick <= 4; tick++) {
        const xv = xd[0] + (xd[1] - xd[0]) * tick / 4, yv = yd[0] + (yd[1] - yd[0]) * tick / 4;
        chart.append(svgNode("line", { x1: x(xv), y1: margin.top, x2: x(xv), y2: height - margin.bottom, stroke: "#e8eef1" }));
        chart.append(svgNode("line", { x1: margin.left, y1: y(yv), x2: width - margin.right, y2: y(yv), stroke: "#e8eef1" }));
        chart.append(svgNode("text", { x: x(xv), y: height - margin.bottom + 20, "text-anchor": "middle", fill: "#71838d", "font-size": 11 }, format(xv, 0)));
        chart.append(svgNode("text", { x: margin.left - 10, y: y(yv) + 4, "text-anchor": "end", fill: "#71838d", "font-size": 11 }, format(yv, 0)));
      }
      chart.append(svgNode("text", { x: margin.left + plotWidth / 2, y: height - 8, "text-anchor": "middle", fill: "#536874", "font-size": 12 }, "膝幅度（°）"));
      chart.append(svgNode("text", { transform: `translate(13 ${margin.top + plotHeight / 2}) rotate(-90)`, "text-anchor": "middle", fill: "#536874", "font-size": 12 }, "踝幅度（°）"));
      const domain = extent(state.data.records, state.colorMetric);
      const ordered = state.filtered.slice().sort((a, b) => a.knee_excursion_deg - b.knee_excursion_deg || a.participant_id.localeCompare(b.participant_id));
      const focusId = ordered.some(row => row.participant_id === state.focusId) ? state.focusId : ordered[0]?.participant_id;
      state.focusId = focusId;
      for (const row of ordered.slice().sort((a, b) => Number(state.selected.includes(a.participant_id)) - Number(state.selected.includes(b.participant_id)))) {
        const selected = state.selected.indexOf(row.participant_id), label = selected >= 0 ? ["A", "B"][selected] : row.participant_id;
        const point = svgNode("circle", { cx: x(row.knee_excursion_deg), cy: y(row.ankle_excursion_deg), r: selected >= 0 ? 7 : 5,
          fill: colorFor(row[state.colorMetric], domain), class: `data-point${selected >= 0 ? " is-selected" : ""}`, role: "button", tabindex: row.participant_id === focusId ? 0 : -1,
          "data-record": row.participant_id, "aria-pressed": selected >= 0 ? "true" : "false", "aria-label": `${row.participant_id}，${recordKind()}，膝${format(row.knee_excursion_deg)}度，踝${format(row.ankle_excursion_deg)}度，${METRICS[state.colorMetric].label}${format(row[state.colorMetric], METRICS[state.colorMetric].digits)}${METRICS[state.colorMetric].unit}${selected >= 0 ? "，已选为" + label : "，未选择"}` });
        point.append(svgNode("title", {}, `${row.participant_id} · ${state.mode === "local" ? "本地数据" : "合成数据"}`));
        point.addEventListener("mouseenter", () => showPoint(row));
        point.addEventListener("focus", () => { state.focusId = row.participant_id; showPoint(row); });
        point.addEventListener("click", () => choose(row.participant_id, true));
        point.addEventListener("keydown", event => {
          const index = ordered.findIndex(item => item.participant_id === row.participant_id);
          if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? ordered.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + ordered.length) % ordered.length;
            focusPoint(ordered[next].participant_id);
          } else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(row.participant_id, true); }
          else if (event.key === "Escape") { event.preventDefault(); state.selected = []; renderChart(); renderSelection(); focusPoint(row.participant_id); }
        });
        chart.append(point);
        if (selected >= 0 || $("show-labels").checked) chart.append(svgNode("text", { x: x(row.knee_excursion_deg) + 9, y: y(row.ankle_excursion_deg) - 8, fill: "#183443", "font-size": selected >= 0 ? 12 : 9, "font-weight": selected >= 0 ? 700 : 400, "pointer-events": "none" }, label));
      }
      $("legend-title").textContent = METRICS[state.colorMetric].label;
      $("legend-min").textContent = `${format(domain[0], METRICS[state.colorMetric].digits)} ${METRICS[state.colorMetric].unit}`;
      $("legend-max").textContent = `${format(domain[1], METRICS[state.colorMetric].digits)} ${METRICS[state.colorMetric].unit}`;
      $("legend-note").textContent = `颜色刻度固定为全样本范围\n颜色不表示好坏${state.filtered.some(row => !finite(row[state.colorMetric])) ? "\n灰色：该指标缺失" : ""}`;
      const current = ordered.find(row => row.participant_id === state.focusId);
      if (current) showPoint(current); else $("point-details").textContent = `当前筛选范围内没有可浏览的${recordKind()}。`;
      if (active && ordered.length) focusPoint(ordered.some(row => row.participant_id === active) ? active : ordered[0].participant_id);
    }

    function renderSelection() {
      const selected = state.selected.map(id => state.data.records.find(row => row.participant_id === id));
      const visible = new Set(state.filtered.map(row => row.participant_id)), hiddenCount = selected.filter(row => !visible.has(row.participant_id)).length;
      $("selection-status").textContent = !selected.length ? `尚未选择${recordKind()}。点选散点或使用列表，最多比较两人。` : `已选择 ${selected.length} / 2 人${hiddenCount ? `，其中 ${hiddenCount} 人在当前筛选范围外，仍保留比较` : ""}。`;
      $("clear-selection").disabled = !selected.length;
      const cards = $("comparison-cards"); cards.replaceChildren();
      [0, 1].forEach(index => {
        const row = selected[index], card = create("article", undefined, `person-card${row ? "" : " is-empty"}`); card.dataset.slot = ["A", "B"][index];
        if (!row) card.append(create("p", `选择${recordKind()} ${["A", "B"][index]}`));
        else {
          const heading = create("h4"); heading.append(create("span", ["A", "B"][index], "person-letter"), create("span", row.participant_id));
          if (!visible.has(row.participant_id)) heading.append(create("span", "筛选外", "outside-filter"));
          const remove = create("button", "×", "remove-person"); remove.setAttribute("aria-label", `移出${recordKind()}${row.participant_id}`); remove.addEventListener("click", () => { choose(row.participant_id); $("point-select").focus(); });
          const metric = METRICS[state.detailMetric]; card.append(heading, remove, create("p", `${metric.label} · ${state.mode === "local" ? "本地" : "合成"}`), create("p", `${format(row[state.detailMetric], metric.digits)} ${metric.unit}`, "person-focus"), create("p", `速度 ${format(row.speed_kmh, 2)} km/h`));
        }
        cards.append(card);
      });
      $("comparison-table-wrap").hidden = !selected.length;
      $("compare-head-a").textContent = selected[0] ? `A · ${selected[0].participant_id}` : "A";
      $("compare-head-b").textContent = selected[1] ? `B · ${selected[1].participant_id}` : "B（待选）";
      const body = $("comparison-body"); body.replaceChildren(); let group = "";
      for (const item of comparisonRows(selected[0], selected[1])) {
        if (item.group !== group) { group = item.group; const tr = create("tr", undefined, "group-row"), th = create("th", group); th.colSpan = 4; th.scope = "colgroup"; tr.append(th); body.append(tr); }
        const tr = create("tr", undefined, item.key === state.detailMetric ? "is-emphasized" : "");
        const th = create("th", `${item.label} `); th.scope = "row"; th.append(create("small", item.unit)); tr.append(th);
        for (const key of ["a", "b", "delta"]) tr.append(create("td", format(item[key], item.digits, key === "delta")));
        body.append(tr);
      }
    }

    function renderModels() {
      const data = state.data.analysis[state.outcome], metric = METRICS[state.outcome];
      for (const button of doc.querySelectorAll("[data-outcome]")) { const on = button.dataset.outcome === state.outcome; button.setAttribute("aria-selected", on); button.tabIndex = on ? 0 : -1; }
      $("model-view").setAttribute("aria-labelledby", state.outcome === "contact_ms" ? "tab-contact" : "tab-peak");
      $("model-cohort").textContent = state.mode === "local" ? `本地主表 n = ${state.data.records.length} · 当前模型 n = ${data.n ?? "未提供"} · 筛选不重拟合` : `完整合成样本 n = ${state.data.records.length} · 当前筛选不改变模型`;
      $("mae-unit").textContent = metric.unit;
      const bars = $("mae-bars"); bars.replaceChildren();
      const rows = [["均值基线", "mean_mae"], ["M0 · 条件", "baseline_mae"], ["M1 · 加动作", "augmented_mae"]];
      const max = Math.max(1, ...rows.map(row => data.cross_validation[row[1]]).filter(finite));
      for (const [label, key] of rows) { const row = create("div", undefined, "mae-row"), track = create("div", undefined, "mae-track"), fill = create("div", undefined, "mae-bar"); fill.style.width = `${finite(data.cross_validation[key]) ? data.cross_validation[key] / max * 100 : 0}%`; track.setAttribute("aria-hidden", "true"); track.append(fill); row.append(create("span", label), track, create("span", `${format(data.cross_validation[key], 2)} ${metric.unit}`, "mae-value")); bars.append(row); }
      const delta = data.cross_validation.delta_mae_baseline_minus_augmented, interval = data.delta_mae_bootstrap_ci95;
      $("delta-estimate").textContent = format(delta, 2, true); $("delta-unit").textContent = metric.unit;
      $("delta-interval").textContent = interval ? `近似 bootstrap 敏感性区间（标称 95%）：[${format(interval[0], 2)}, ${format(interval[1], 2)}] ${metric.unit}` : "当前导出未提供可用的区间。";
      const scope = state.mode === "local" ? "当前本地研究" : "这一合成机制";
      const reading = { missing: "没有可用区间，不能仅据点估计判断明确改善。", uncertain: `区间跨越或接触 0：${scope}的增量方向未明确。`, positive: `区间位于 0 以上：${scope}中 M1 误差较低；这不是因果或临床验证。`, negative: `区间位于 0 以下：${scope}中 M1 误差较高；不代表任何人的动作质量。` };
      $("interval-reading").textContent = finite(delta) ? reading[intervalSummary(interval)] : "该配置未提供可估计的预测结果；请查看全部分析中的状态。";
      const chart = $("interval-chart"); chart.replaceChildren(); chart.setAttribute("viewBox", "0 0 360 86");
      chart.hidden = !finite(delta);
      const plotDelta = finite(delta) ? delta : 0;
      const lower = Math.min(0, plotDelta, ...(interval || [])), upper = Math.max(0, plotDelta, ...(interval || [])), pad = (upper - lower || 1) * .15;
      const scale = value => 22 + (value - lower + pad) / (upper - lower + pad * 2) * 316;
      chart.append(svgNode("line", { x1: 22, y1: 32, x2: 338, y2: 32, stroke: "#e1e9ed", "stroke-width": 2 }));
      chart.append(svgNode("line", { x1: scale(0), y1: 12, x2: scale(0), y2: 48, stroke: "#8497a2", "stroke-dasharray": "3 3" }));
      if (interval) chart.append(svgNode("line", { x1: scale(interval[0]), y1: 32, x2: scale(interval[1]), y2: 32, stroke: "#007787", "stroke-width": 4 }));
      chart.append(svgNode("circle", { cx: scale(plotDelta), cy: 32, r: 5, fill: "#183443" }));
      chart.append(svgNode("text", { x: 22, y: 72, fill: "#71838d", "font-size": 11 }, "M1 误差更高"), svgNode("text", { x: 338, y: 72, "text-anchor": "end", fill: "#71838d", "font-size": 11 }, "M1 误差更低"));
      chart.setAttribute("aria-label", `${metric.label}${state.mode === "local" ? "本地" : "合成"}模型，增量${format(delta, 2)}${metric.unit}。${$("delta-interval").textContent}`);
      const coefficients = $("coefficient-body"); coefficients.replaceChildren();
      for (const item of data.coefficients) { const row = create("tr"); row.append(create("td", TERMS[item.term] || item.term), create("td", format(item.estimate, 4)), create("td", item.hc3_ci95 ? `[${format(item.hc3_ci95[0], 4)}, ${format(item.hc3_ci95[1], 4)}]` : "未提供")); coefficients.append(row); }
      if (!data.coefficients.length) { const row = create("tr"), cell = create("td", "没有可用系数。"); cell.colSpan = 3; row.append(cell); coefficients.append(row); }
    }

    function analysisLabel(name) {
      if (ASSOCIATIONS.includes(name)) return SPEC_LABELS[name];
      const [spec, outcome] = name.split("__");
      return `${SPEC_LABELS[spec] || spec} · ${METRICS[outcome]?.label || outcome}`;
    }

    function intervalText(value, digits = 3) { return value ? `[${format(value[0], digits)}, ${format(value[1], digits)}]` : "未提供"; }

    function addStudyTable(container, caption, headers, rows) {
      const wrap = create("div", undefined, "table-scroll"), table = create("table", undefined, "study-table");
      table.append(create("caption", caption));
      const head = create("thead"), tr = create("tr"); for (const label of headers) { const th = create("th", label); th.scope = "col"; tr.append(th); } head.append(tr); table.append(head);
      const body = create("tbody");
      for (const values of rows) { const line = create("tr"); values.forEach((value, index) => { const cell = create(index === 0 ? "th" : "td", String(value ?? "未提供")); if (index === 0) cell.scope = "row"; line.append(cell); }); body.append(line); }
      table.append(body); wrap.append(table); container.append(wrap);
    }

    function designText(model) {
      const d = model.augmented_diagnostics || model.diagnostics || model.baseline_diagnostics;
      if (!d) return "未提供";
      return `${d.interpretation_gate_passed === true ? "数值门槛通过" : d.interpretation_gate_passed === false ? "解释门槛未过" : "状态未提供"}；rank ${format(d.rank, 0)} / ${format(d.n_parameters, 0)}；condition ${format(d.standardized_design_condition_number, 2)}`;
    }

    function renderLocalStudy(payload) {
      const configuration = payload.configuration || {};
      $("local-origin-note").textContent = `来源：用户主动选择的本地文件；输入类型由文件声明为${payload.dataset_kind === "synthetic" ? "独立合成数据" : "私有实证数据"}。主表 ${payload.primary_participants.length} 条，完整保留 22 个分析配置。${payload.notice}`;
      const protocol = $("local-protocol"); protocol.replaceChildren();
      const params = [["协议", payload.protocol_id], ["分析种子", configuration.seed], ["冻结 bootstrap 次数", configuration.bootstrap_replicates], ["实际 bootstrap 次数", configuration.executed_bootstrap_replicates], ["实际次数匹配冻结值", configuration.full_frozen_draw_count === undefined ? undefined : configuration.full_frozen_draw_count ? "是" : "否（检查运行）"], ["最少主分析人数", configuration.minimum_main_participants], ["设计 condition 门槛", configuration.maximum_standardized_design_condition_number], ["共同窗口（秒）", configuration.window_seconds], ["病例速度卡尺（km/h）", configuration.case_speed_caliper_kmh]];
      for (const [label, value] of params) { const box = create("div"); box.append(create("dt", label), create("dd", value === undefined ? "未提供" : String(value))); protocol.append(box); }
      const container = $("local-analysis-tables"); container.replaceChildren();
      const predictionRows = [], associationRows = [];
      for (const name of LOCAL_ANALYSES) {
        const model = payload.analyses[name], stateLabel = model.status === "estimated" ? "已估计" : `未估计 · ${model.status}`;
        if (!ASSOCIATIONS.includes(name)) predictionRows.push([analysisLabel(name), model.n, stateLabel, `${format(model.cv_metrics?.delta_mae_baseline_minus_augmented, 3, true)} ${METRICS[model.outcome].unit}`, intervalText(model.cv_metric_bootstrap_ci95?.delta_mae_baseline_minus_augmented), designText(model)]);
        else {
          const coef = (model.coefficients || []).find(row => row.term === "navicular_ratio_per001");
          associationRows.push([analysisLabel(name), model.n, stateLabel, model.outcome_logged ? "log(结果) / 比值+0.01" : "度 / 比值+0.01", format(coef?.estimate, 5, true), intervalText(coef?.hc3_ci95, 5), intervalText(coef?.participant_bootstrap_ci95, 5)]);
        }
      }
      addStudyTable(container, "17 个预测配置 · ΔMAE = M0 − M1；区间为近似敏感性区间，标称 95%", ["配置", "独立 n", "状态", "ΔMAE", "近似区间", "设计诊断"], predictionRows);
      addStudyTable(container, "5 个足形关联配置 · 比值增加 0.01，不是相对增加 1%", ["配置", "独立 n", "状态", "系数单位", "系数", "HC3 95%", "人级 bootstrap 95%"], associationRows);
      const measurement = $("local-measurement"); measurement.replaceChildren();
      const measureRows = [["full_pressure_cohort", "压力队列"], ["primary_motion_cohort", "主分析子集"]].map(([key, label]) => {
        const group = payload.measurement_summary[key] || {}, stats = group.statistics || {};
        return [label, group.cohort_n, group.repeatable_n, group.repeat_trial_n, `${format(stats.pooled_within_sd_cm2?.estimate, 3)} ${intervalText(stats.pooled_within_sd_cm2?.bootstrap_ci95)}`, `${format(stats.first_last_bias_cm2?.estimate, 3, true)} ${intervalText(stats.first_last_bias_cm2?.bootstrap_ci95)}`, `[${format(stats.first_last_loa_lower_cm2?.estimate, 3)}, ${format(stats.first_last_loa_upper_cm2?.estimate, 3)}]`];
      });
      addStudyTable(measurement, "有效承载面积的同次重复测量 · 单位 cm²；两个队列可能重叠", ["队列", "队列 n", "重复者 n", "试验数", "组内 SD [区间]", "首末偏差 [区间]", "近似一致性界限"], measureRows);
      measurement.append(create("p", "SD 和偏差后的区间是人级 bootstrap 区间。一致性界限不是置信区间，也不是临床等效阈值。未提供的量保持为空，不使用演示数值填补。", "card-note"));
      const cohort = payload.cohort_selection_summary;
      measurement.append(create("p", `队列描述来源：${typeof cohort.source_scope === "string" ? cohort.source_scope : "文件未提供"}`, "card-note"));
      const details = $("local-model-details"); details.replaceChildren();
      for (const name of LOCAL_ANALYSES) {
        const model = payload.analyses[name], box = create("details", undefined, "analysis-detail");
        box.append(create("summary", `${analysisLabel(name)} · n=${model.n} · ${model.status === "estimated" ? "已估计" : "未估计"}`));
        box.append(create("p", `模型项：${[...(model.controls || []), ...(model.strategy_terms || []), ...(model.terms || [])].map(term => TERMS[term] || term).join("；") || "未提供"}。${designText(model)}。`));
        for (const [key, label] of [["baseline_coefficients", "M0 基线"], ["augmented_coefficients", "M1 加动作"], ["coefficients", "关联模型"]]) if (model[key]?.length) addStudyTable(box, `${label} · 系数保持拟合尺度`, ["项", "系数", "HC3 95%", "人级 bootstrap 95%"], model[key].map(coef => [TERMS[coef.term] || coef.term, format(coef.estimate, 5), intervalText(coef.hc3_ci95, 5), intervalText(coef.participant_bootstrap_ci95, 5)]));
        details.append(box);
      }
    }

    async function load() {
      const request = ++state.request; $("load-state").hidden = false; $("load-state").classList.remove("is-error"); $("retry-load").hidden = true; $("load-message").textContent = "正在载入合成数据…";
      try {
        const response = await fetch("data/demo.json", { credentials: "same-origin", cache: "no-cache" });
        if (!response.ok) throw new Error("Dataset unavailable.");
        const data = validateDataset(await response.json()); if (request !== state.request) return;
        state.remoteData = data; activateData(data, "demo");
      } catch (error) {
        if (request !== state.request) return;
        state.data = null; $("explorer-content").hidden = true; $("model-content").hidden = true; $("model-loading").hidden = false;
        $("load-state").classList.add("is-error"); $("load-message").textContent = "暂时无法载入通过检查的合成数据。请重试，或使用网站预览地址打开。"; $("retry-load").hidden = false;
      }
    }

    for (const id of ids) $(id).addEventListener("input", update);
    $("body-metric").addEventListener("change", event => { state.bodyMetric = event.target.value; if (state.data) { setBodyBounds(); update(); } });
    $("color-metric").addEventListener("change", event => { state.colorMetric = event.target.value; if (state.data) renderChart(); });
    $("detail-metric").addEventListener("change", event => { state.detailMetric = event.target.value; if (state.data) { renderSelection(); const row = state.data.records.find(row => row.participant_id === state.focusId); if (row) showPoint(row); } });
    $("show-labels").addEventListener("change", () => { if (state.data) renderChart(); });
    $("local-file").addEventListener("change", event => { const file = event.target.files?.[0]; if (file) importFile(file); });
    $("return-demo").addEventListener("click", returnToDemo);
    $("reset-all").addEventListener("click", reset); $("empty-reset").addEventListener("click", reset); $("retry-load").addEventListener("click", load);
    $("clear-selection").addEventListener("click", () => { state.selected = []; renderChart(); renderSelection(); $("point-select").focus(); });
    $("pick-person").addEventListener("click", () => { if ($("point-select").value) choose($("point-select").value); });
    $("point-select").addEventListener("change", event => { const row = state.filtered.find(row => row.participant_id === event.target.value); if (row) showPoint(row); });
    for (const button of doc.querySelectorAll("[data-outcome]")) {
      button.addEventListener("click", () => { state.outcome = button.dataset.outcome; if (state.data) renderModels(); });
      button.addEventListener("keydown", event => { if (["ArrowLeft", "ArrowRight"].includes(event.key)) { event.preventDefault(); const next = state.outcome === "contact_ms" ? $("tab-peak") : $("tab-contact"); next.click(); next.focus(); } });
    }
    const dialog = $("figure-dialog");
    for (const button of doc.querySelectorAll("[data-figure]")) button.addEventListener("click", () => { $("dialog-image").src = `assets/${button.dataset.figure}`; $("dialog-image").alt = button.dataset.title; $("figure-dialog-title").textContent = button.dataset.title; if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", ""); });
    $("close-dialog").addEventListener("click", () => { if (typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open"); });
    dialog.addEventListener("click", event => { if (event.target === dialog) { if (typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open"); } });
    let resizeFrame = null;
    const onResize = () => { if (state.data && Math.abs($("scatter-container").clientWidth - state.lastWidth) > 1) { cancelAnimationFrame(resizeFrame); resizeFrame = requestAnimationFrame(renderChart); } };
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(onResize).observe($("scatter-container")); else globalThis.addEventListener("resize", onResize);
    load();
    return { reload: load, importFile, returnToDemo };
  }

  return { METRICS, EXPECTED_UNITS, LOCAL_MAX_BYTES, LOCAL_ANALYSES, validateDataset, validateLocalPayload, localDataView, readLocalFile, extent, paddedExtent, filterRecords, toggleSelection, intervalSummary, colorFor, comparisonRows, format, mount };
});
