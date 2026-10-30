/* SPDX-License-Identifier: BSD-3-Clause */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SCMPattern = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const SCHEMA = "scm-strategy.pattern-local/1";
  const RECORD_FIELDS = ["height_cm", "weight_kg", "navicular_ratio", "speed_kmh", "contact_ms", "pressure_peak_N", "effective_area_cm2", "foot_size_proxy_cm2", "knee_excursion_deg", "ankle_excursion_deg"];
  const UNITS = { height_cm: "cm", weight_kg: "kg", navicular_ratio: "1", speed_kmh: "km/h", contact_ms: "ms", pressure_peak_N: "N", effective_area_cm2: "cm^2", foot_size_proxy_cm2: "cm^2", knee_excursion_deg: "degree", ankle_excursion_deg: "degree", trajectories: "degree" };
  const finite = x => typeof x === "number" && Number.isFinite(x);
  const object = x => x && typeof x === "object" && !Array.isArray(x);
  const exact = (x, keys) => object(x) && Object.keys(x).every(k => keys.includes(k));
  const nullable = x => x === null || finite(x);
  const interval = x => x === null || (Array.isArray(x) && x.length === 2 && x.every(nullable) && ((x[0] === null && x[1] === null) || (x.every(finite) && x[0] <= x[1])));

  function validate(data, remote = false) {
    const fail = text => { throw new Error(text); };
    const top = ["schema_version", "dataset_kind", "local_only", "exportable", "upload_allowed", "notice", "protocol_id", "generator", "units", "configuration", "records", "associations", "body_motion", "geometry_summary", "repeat_summary"];
    if (!exact(data, top) || data.schema_version !== SCHEMA || !["private_empirical", "synthetic"].includes(data.dataset_kind) || data.local_only !== true || data.exportable !== false || data.upload_allowed !== false) fail("不支持的动作研究格式或隐私标志。");
    if (data.protocol_id !== "scm-strategy.pattern/1" || typeof data.notice !== "string" || data.notice.length > 4096) fail("动作研究协议无效。");
    if (!object(data.units) || Object.keys(data.units).length !== Object.keys(UNITS).length || Object.keys(UNITS).some(k => data.units[k] !== UNITS[k])) fail("动作研究单位不匹配。");
    const cfgKeys = ["seed", "bootstrap_replicates", "permutations", "primary_speed_caliper_kmh", "display_max_points", "full_frozen_counts"];
    if (!exact(data.configuration, cfgKeys) || cfgKeys.some(k => k === "full_frozen_counts" ? typeof data.configuration[k] !== "boolean" : !finite(data.configuration[k]) || data.configuration[k] < 0)) fail("动作研究配置无效。");
    if (data.configuration.display_max_points > 2400 || data.configuration.display_max_points < 20) fail("显示点数超限。");
    if (data.configuration.full_frozen_counts && (data.configuration.bootstrap_replicates !== 2000 || data.configuration.permutations !== 9999)) fail("重采样次数与完整标志矛盾。");
    if (!exact(data.generator, ["name", "seed", "participants", "primary_participants", "samples_per_record"]) || (data.generator.name !== undefined && data.generator.name !== "scm-strategy.pattern-equations/1") || Object.entries(data.generator).some(([k, v]) => k !== "name" && (!Number.isInteger(v) || v < 0))) fail("合成来源字段无效。");
    if (!Array.isArray(data.records) || !data.records.length || data.records.length > 10000) fail("动作研究人数无效。");
    const ids = new Set();
    for (const r of data.records) {
      if (!exact(r, ["participant_id", ...RECORD_FIELDS, "qc_status", "trajectories", "trajectory_sampling", "motion_summary"]) || typeof r.participant_id !== "string" || !/^[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(r.participant_id) || ids.has(r.participant_id)) fail("动作记录编号无效或重复。");
      ids.add(r.participant_id);
      if (RECORD_FIELDS.some(k => !Object.hasOwn(r, k) || !nullable(r[k]) || (r[k] !== null && r[k] <= 0))) fail("动作记录包含无效数值。");
      if (typeof r.qc_status !== "string" || r.qc_status.length > 100 || !exact(r.motion_summary, ["centered_D_LR_deg", "raw_D_LR_deg"]) || Object.values(r.motion_summary).some(x => !nullable(x) || (finite(x) && x < 0))) fail("动作摘要无效。");
      if (r.trajectories !== null) {
        if (!exact(r.trajectories, ["left", "right"])) fail("轨迹侧别无效。");
        for (const side of ["left", "right"]) {
          const curve = r.trajectories[side];
          if (!exact(curve, ["knee_deg", "ankle_deg"]) || !Array.isArray(curve.knee_deg) || !Array.isArray(curve.ankle_deg) || !curve.knee_deg.length || curve.knee_deg.length !== curve.ankle_deg.length || curve.knee_deg.length > data.configuration.display_max_points || !curve.knee_deg.every(finite) || !curve.ankle_deg.every(finite)) fail("显示轨迹无效或超限。");
        }
      }
      if (r.trajectory_sampling !== undefined) {
        const s = r.trajectory_sampling, actual = r.trajectories?.left.knee_deg.length || 0;
        if (!exact(s, ["source_points", "display_points", "simplified"]) || !Number.isInteger(s.source_points) || !Number.isInteger(s.display_points) || s.source_points < s.display_points || s.display_points < 0 || s.display_points !== actual || s.display_points !== (r.trajectories?.right.knee_deg.length || 0) || s.simplified !== (s.source_points > s.display_points)) fail("显示采样记录无效或矛盾。");
      }
    }
    const expected = new Set([...["area_log_lr", "peak_log_lr"].flatMap(y => ["primary", "repeat_mean", "speed_adjusted", "geometry_adjusted"].map(s => `static_bilateral:${y}:${s}`)), ...["abs_area_log_lr", "abs_peak_log_lr"].flatMap(y => ["primary", "raw_motion", "static_instead_of_speed"].map(s => `motion_bilateral:${y}:${s}`))]);
    if (!Array.isArray(data.associations) || data.associations.length !== 14) fail("应保留全部14个关联状态。");
    for (const m of data.associations) {
      const key = `${m.family}:${m.outcome}:${m.spec}`;
      if (!expected.delete(key) || !exact(m, ["family", "outcome", "spec", "status", "n", "coefficients", "condition_number", "bootstrap_valid", "bootstrap_failed"]) || !["estimated", "not_estimable"].includes(m.status) || !Number.isInteger(m.n) || m.n < 0 || !Array.isArray(m.coefficients) || m.coefficients.length > 3) fail("关联配置无效。");
      for (const c of m.coefficients) if (!exact(c, ["term", "estimate", "hc3_ci95", "bootstrap_ci95"]) || typeof c.term !== "string" || c.term.length > 100 || !finite(c.estimate) || !interval(c.hc3_ci95) || !interval(c.bootstrap_ci95)) fail("关联区间无效。");
      for (const k of ["condition_number", "bootstrap_valid", "bootstrap_failed"]) if (!nullable(m[k]) || (finite(m[k]) && m[k] < 0)) fail("关联诊断无效。");
    }
    if (!exact(data.body_motion, ["counts", "statistics"]) || !object(data.body_motion.counts) || Object.values(data.body_motion.counts).some(x => !nullable(x) || (finite(x) && x < 0)) || !exact(data.body_motion.statistics, ["time_mean_centered", "raw"])) fail("身体—动作摘要无效。");
    for (const s of Object.values(data.body_motion.statistics)) if (!exact(s, ["status", "conditional_r", "unconditional_descriptive_r", "two_sided_permutation_p", "monte_carlo_se", "null_mean"]) || !["estimated", "not_estimable"].includes(s.status) || Object.entries(s).some(([k, x]) => k !== "status" && !nullable(x))) fail("置换摘要无效。");
    // The aggregate trees are never rendered as HTML and may contain only bounded numeric summaries/statuses.
    function aggregate(x, depth = 0) {
      if (depth > 5) return false;
      if (x === null || finite(x)) return true;
      if (typeof x === "string") return x.length < 120 && /^[A-Za-z0-9 _.,:;=()/-]+$/.test(x) && !x.includes("://");
      if (Array.isArray(x)) return x.length < 100 && x.every(v => aggregate(v, depth + 1));
      return object(x) && Object.keys(x).length < 30 && Object.entries(x).every(([k, v]) => /^[A-Za-z0-9_]+$/.test(k) && aggregate(v, depth + 1));
    }
    if (!aggregate(data.geometry_summary) || !aggregate(data.repeat_summary)) fail("聚合摘要格式无效。");
    if (remote && (data.dataset_kind !== "synthetic" || data.generator?.name !== "scm-strategy.pattern-equations/1" || !Number.isInteger(data.generator.seed) || data.generator.primary_participants !== data.records.length || !data.records.every(r => /^SYN-\d{5}$/.test(r.participant_id)))) fail("远端演示仅接受固定独立合成来源。");
    return data;
  }

  function dataView(payload) { return { records: payload.records, units: payload.units, analysis: {}, patternPayload: payload, generator: payload.generator }; }
  return { SCHEMA, RECORD_FIELDS, UNITS, validate, dataView };
});
