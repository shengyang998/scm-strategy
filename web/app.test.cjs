/* SPDX-License-Identifier: BSD-3-Clause */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const app = require("./app.js");
const payload = JSON.parse(fs.readFileSync(path.join(__dirname, "data/demo.json"), "utf8"));
const clone = () => structuredClone(payload);
const localFixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/synthetic-local-study.json"), "utf8"));
function localClone() {
  const local = structuredClone(localFixture), mapping = new Map(local.primary_participants.map(row => [row.participant_id, `LOCAL-${row.participant_id}`]));
  for (const row of local.primary_participants) row.participant_id = mapping.get(row.participant_id);
  for (const model of Object.values(local.analyses)) for (const row of model.predictions || []) row.participant_id = mapping.get(row.participant_id);
  return local;
}
class ReaderDouble {
  readAsText(file) { this.result = file.content; queueMicrotask(() => this.onload()); }
}

test("accepts the package-owned synthetic export without changing it", () => {
  const before = JSON.stringify(payload);
  assert.equal(app.validateDataset(payload), payload);
  assert.equal(JSON.stringify(payload), before);
  assert.equal(payload.records.length, payload.generator.parameters.participants);
});

test("rejects real or unsupported dataset envelopes", () => {
  const bad = clone(); bad.dataset_kind = "private_empirical";
  assert.throws(() => app.validateDataset(bad), /synthetic/);
  const version = clone(); version.schema_version = "unknown";
  assert.throws(() => app.validateDataset(version), /synthetic/);
  const extra = clone(); extra.private_path = "/private/record";
  assert.throws(() => app.validateDataset(extra), /envelope/);
});

test("rejects nonfinite values, duplicate IDs and unexpected personal fields", () => {
  const duplicate = clone(); duplicate.records[1].participant_id = duplicate.records[0].participant_id;
  assert.throws(() => app.validateDataset(duplicate), /duplicate/);
  const nonfinite = clone(); nonfinite.records[0].height_cm = Infinity;
  assert.throws(() => app.validateDataset(nonfinite), /measurement/);
  const personal = clone(); personal.records[0].name = "Unexpected";
  assert.throws(() => app.validateDataset(personal), /fields/);
});

test("null intervals are accepted and ordered finite intervals are required", () => {
  const missing = clone(); missing.analysis.contact_ms.delta_mae_bootstrap_ci95 = null;
  assert.equal(app.validateDataset(missing), missing);
  const reversed = clone(); reversed.analysis.contact_ms.delta_mae_bootstrap_ci95 = [5, 1];
  assert.throws(() => app.validateDataset(reversed), /interval/);
});

test("model units and prediction joins must match the contract", () => {
  const units = clone(); units.analysis.contact_ms.unit = "N";
  assert.throws(() => app.validateDataset(units), /summary/);
  const predictions = clone(); predictions.analysis.contact_ms.predictions[0].participant_id = "SYN-99999";
  assert.throws(() => app.validateDataset(predictions), /prediction/);
});

test("filters use inclusive ranges and reject empty or inverted input", () => {
  const rows = payload.records.slice(0, 3);
  const target = rows[0];
  const filters = { speedMin: target.speed_kmh, speedMax: target.speed_kmh, bodyMetric: "height_cm", bodyMin: target.height_cm, bodyMax: target.height_cm };
  assert.deepEqual(app.filterRecords(rows, filters), [target]);
  assert.deepEqual(app.filterRecords(rows, { ...filters, speedMin: Infinity }), []);
  assert.deepEqual(app.filterRecords(rows, { ...filters, bodyMin: target.height_cm + 1 }), []);
  assert.equal(rows.length, 3);
});

test("two-person selection is bounded, reversible and immutable", () => {
  const original = ["SYN-00001", "SYN-00002"];
  assert.deepEqual(app.toggleSelection(original, "SYN-00003"), { ids: original, full: true });
  assert.deepEqual(app.toggleSelection(original, "SYN-00001"), { ids: ["SYN-00002"], full: false });
  assert.deepEqual(original, ["SYN-00001", "SYN-00002"]);
  assert.deepEqual(app.toggleSelection([], "SYN-00001").ids, ["SYN-00001"]);
});

test("comparison reports signed A-minus-B values in source units", () => {
  const [a, b] = payload.records;
  const rows = app.comparisonRows(a, b);
  const contact = rows.find(row => row.key === "contact_ms");
  assert.equal(contact.delta, a.contact_ms - b.contact_ms);
  assert.equal(contact.unit, "ms");
  assert.equal(app.comparisonRows(a, null).find(row => row.key === "contact_ms").delta, null);
  assert.equal(app.comparisonRows({ ...a, contact_ms: null }, b).find(row => row.key === "contact_ms").delta, null);
});

test("interval wording treats touching zero as uncertain", () => {
  assert.equal(app.intervalSummary(null), "missing");
  assert.equal(app.intervalSummary([-1, 2]), "uncertain");
  assert.equal(app.intervalSummary([0, 2]), "uncertain");
  assert.equal(app.intervalSummary([.1, 2]), "positive");
  assert.equal(app.intervalSummary([-2, -.1]), "negative");
});

test("constant domains remain finite and colors clamp to a fixed scale", () => {
  const domain = app.paddedExtent([{ knee_excursion_deg: 50 }], "knee_excursion_deg");
  assert.ok(domain[0] < 50 && domain[1] > 50);
  assert.equal(app.colorFor(-100, [0, 1]), app.colorFor(0, [0, 1]));
  assert.equal(app.colorFor(100, [0, 1]), app.colorFor(1, [0, 1]));
  assert.ok(!app.colorFor(1, [1, 1]).includes("NaN"));
});

test("filtering does not mutate or refit aggregate model results", () => {
  const before = JSON.stringify(payload.analysis);
  const [min, max] = app.extent(payload.records, "speed_kmh");
  app.filterRecords(payload.records, { speedMin: min, speedMax: (min + max) / 2, bodyMetric: "weight_kg", bodyMin: 0, bodyMax: 1000 });
  assert.equal(JSON.stringify(payload.analysis), before);
});

test("static DOM hooks exist and interface has no dynamic HTML injection", () => {
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  const js = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
  assert.equal(ids.size, [...html.matchAll(/\bid="([^"]+)"/g)].length);
  for (const match of js.matchAll(/\$\("([^"]+)"\)/g)) assert.ok(ids.has(match[1]), `Missing DOM hook ${match[1]}`);
  assert.ok(!js.includes("innerHTML"));
  assert.ok(html.includes('lang="zh-CN"'));
  assert.ok(html.includes('id="point-select"'));
  assert.ok(!/<script[^>]+src="https?:/i.test(html));
});

test("DOM smoke: load, select two, reject a third, empty filter, reset and outcome switch", async () => {
  const { createDocument } = require("./test-dom.cjs");
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  const doc = createDocument(html), $ = id => doc.getElementById(id);
  const oldFetch = global.fetch, oldObserver = global.ResizeObserver;
  global.fetch = async () => ({ ok: true, json: async () => clone() });
  global.ResizeObserver = class { observe() {} };
  try {
    app.mount(doc);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal($("explorer-content").hidden, false);
    assert.equal($("scatter").querySelectorAll("[data-record]").length, payload.records.length);
    for (const row of payload.records.slice(0, 3)) { $("point-select").value = row.participant_id; $("pick-person").click(); }
    assert.ok($("selection-status").textContent.includes("已选择两人"));
    assert.equal($("comparison-cards").children.length, 2);
    assert.ok(!$("comparison-cards").textContent.includes(payload.records[2].participant_id));
    $("speed-max").value = "0"; $("speed-max").emit("input");
    assert.equal($("empty-state").hidden, false);
    assert.ok($("selection-status").textContent.includes("筛选范围外"));
    assert.equal($("scatter").querySelectorAll("[data-record]").length, 0);
    $("empty-reset").click();
    assert.equal($("empty-state").hidden, true);
    assert.ok($("selection-status").textContent.includes("尚未选择"));
    $("tab-peak").click();
    assert.equal($("delta-unit").textContent, "N");
    assert.equal($("tab-peak").getAttribute("aria-selected"), "true");
  } finally { global.fetch = oldFetch; global.ResizeObserver = oldObserver; }
});

test("DOM smoke: failed or non-synthetic data stays behind the error state", async () => {
  const { createDocument } = require("./test-dom.cjs");
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8"), doc = createDocument(html);
  const oldFetch = global.fetch, oldObserver = global.ResizeObserver;
  global.fetch = async () => ({ ok: true, json: async () => ({ ...clone(), dataset_kind: "private_empirical" }) });
  global.ResizeObserver = class { observe() {} };
  try {
    app.mount(doc); await new Promise(resolve => setImmediate(resolve));
    assert.equal(doc.getElementById("explorer-content").hidden, true);
    assert.equal(doc.getElementById("retry-load").hidden, false);
    assert.equal(doc.getElementById("load-state").classList.contains("is-error"), true);
  } finally { global.fetch = oldFetch; global.ResizeObserver = oldObserver; }
});

test("independent synthetic local fixture validates but is rejected as a remote demo", () => {
  assert.equal(localFixture.dataset_kind, "synthetic");
  assert.ok(localFixture.primary_participants.every(row => /^SYN-/.test(row.participant_id)));
  assert.equal(app.validateLocalPayload(localFixture), localFixture);
  assert.throws(() => app.validateDataset(localFixture), /synthetic/);
  assert.equal(Object.keys(localFixture.analyses).length, 22);
});

test("remote loader never activates a local-only payload", async () => {
  const { createDocument } = require("./test-dom.cjs");
  const doc = createDocument(fs.readFileSync(path.join(__dirname, "index.html"), "utf8"));
  const oldFetch = global.fetch, oldObserver = global.ResizeObserver;
  global.fetch = async () => ({ ok: true, json: async () => localClone() }); global.ResizeObserver = class { observe() {} };
  try {
    app.mount(doc); await new Promise(resolve => setImmediate(resolve));
    assert.equal(doc.getElementById("explorer-content").hidden, true);
    assert.equal(doc.getElementById("local-study-results").hidden, true);
    assert.equal(doc.getElementById("load-state").classList.contains("is-error"), true);
  } finally { global.fetch = oldFetch; global.ResizeObserver = oldObserver; }
});

test("local validation rejects schema/flags/extra URL fields and missing analyses", () => {
  for (const mutation of [local => { local.schema_version = "unknown"; }, local => { local.upload_allowed = true; }, local => { local.exportable = true; }, local => { local.url = "https://example.invalid"; }, local => { delete local.analyses.body_to_knee; }]) {
    const local = localClone(); mutation(local); assert.throws(() => app.validateLocalPayload(local));
  }
});

test("FileReader checks size before reading and rejects malformed or unknown JSON", async () => {
  let reads = 0;
  class CountingReader extends ReaderDouble { readAsText(file) { reads++; super.readAsText(file); } }
  await assert.rejects(app.readLocalFile({ size: app.LOCAL_MAX_BYTES + 1 }, CountingReader), /10 MiB/);
  assert.equal(reads, 0);
  await assert.rejects(app.readLocalFile({ size: 2, content: "{" }, CountingReader), /JSON/);
  await assert.rejects(app.readLocalFile({ size: 20, content: JSON.stringify({ schema_version: "unknown" }) }, CountingReader));
  assert.equal(reads, 2);
});

test("local file import uses memory only, preserves two-person limit and clears on return", async () => {
  const { createDocument } = require("./test-dom.cjs");
  const doc = createDocument(fs.readFileSync(path.join(__dirname, "index.html"), "utf8")), $ = id => doc.getElementById(id);
  const oldFetch = global.fetch, oldObserver = global.ResizeObserver, oldReader = global.FileReader;
  const storageDescriptors = Object.fromEntries(["localStorage", "sessionStorage", "indexedDB"].map(key => [key, Object.getOwnPropertyDescriptor(global, key)]));
  let requests = 0, storageAccesses = 0;
  global.fetch = async () => { requests++; return { ok: true, json: async () => clone() }; };
  global.ResizeObserver = class { observe() {} }; global.FileReader = ReaderDouble;
  for (const key of Object.keys(storageDescriptors)) Object.defineProperty(global, key, { configurable: true, get() { storageAccesses++; throw new Error("storage forbidden"); } });
  try {
    const controller = app.mount(doc); await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests, 1);
    const local = localClone(); local.notice = "Reference text https://example.invalid/not-a-request";
    const content = JSON.stringify(local);
    assert.equal(await controller.importFile({ size: Buffer.byteLength(content), content }), true);
    assert.equal(requests, 1); assert.equal(storageAccesses, 0);
    assert.ok($("mode-badge").textContent.includes("本地私有研究"));
    assert.equal($("local-study-results").hidden, false); assert.equal($("findings").hidden, true);
    assert.ok($("local-origin-note").textContent.includes("https://example.invalid/not-a-request"));
    assert.equal($("local-model-details").children.length, 22);
    assert.ok($("local-protocol").textContent.includes("实际 bootstrap 次数12"));
    for (const row of local.primary_participants.slice(0, 3)) { $("point-select").value = row.participant_id; $("pick-person").click(); }
    assert.ok($("selection-status").textContent.includes("已选择两人"));
    assert.ok(!$("comparison-cards").textContent.includes(local.primary_participants[2].participant_id));
    $("reset-all").click();
    assert.ok($("selection-status").textContent.includes("尚未选择本地记录"));
    assert.ok($("mode-badge").textContent.includes("本地私有研究"));
    controller.returnToDemo();
    assert.equal(requests, 1); assert.equal(storageAccesses, 0);
    assert.ok($("mode-badge").textContent.includes("Synthetic demo"));
    assert.equal($("local-study-results").hidden, true); assert.equal($("findings").hidden, false);
    assert.equal($("local-protocol").children.length, 0); assert.equal($("local-model-details").children.length, 0);
    assert.ok(!$("comparison-cards").textContent.includes("LOCAL-"));
    assert.ok($("scatter").querySelectorAll("[data-record]").every(point => !point.dataset.record.startsWith("LOCAL-")));
    assert.equal($("local-file").value, "");
  } finally {
    global.fetch = oldFetch; global.ResizeObserver = oldObserver; global.FileReader = oldReader;
    for (const [key, descriptor] of Object.entries(storageDescriptors)) { if (descriptor) Object.defineProperty(global, key, descriptor); else delete global[key]; }
  }
});

test("local unavailable models and nullable plotting fields remain explicit", async () => {
  const { createDocument } = require("./test-dom.cjs");
  const doc = createDocument(fs.readFileSync(path.join(__dirname, "index.html"), "utf8")), $ = id => doc.getElementById(id);
  const oldFetch = global.fetch, oldObserver = global.ResizeObserver, oldReader = global.FileReader;
  global.fetch = async () => ({ ok: true, json: async () => clone() }); global.ResizeObserver = class { observe() {} }; global.FileReader = ReaderDouble;
  try {
    const controller = app.mount(doc); await new Promise(resolve => setImmediate(resolve));
    const local = localClone(); delete local.configuration;
    local.primary_participants[0].knee_excursion_deg = null;
    const model = local.analyses.primary__contact_ms; model.status = "numerically_not_estimable"; model.n = 0;
    for (const key of ["cv_metrics", "cv_metric_bootstrap_ci95", "augmented_coefficients", "baseline_coefficients", "predictions"]) delete model[key];
    const content = JSON.stringify(local); assert.equal(await controller.importFile({ size: content.length, content }), true);
    assert.equal($("scatter").querySelectorAll("[data-record]").length, local.primary_participants.length - 1);
    assert.equal($("delta-estimate").textContent, "—");
    assert.ok(!$("mae-bars").textContent.includes("NaN"));
    assert.ok($("local-analysis-tables").textContent.includes("未估计"));
    assert.ok($("local-protocol").textContent.includes("未提供"));
    assert.equal(await controller.importFile({ size: app.LOCAL_MAX_BYTES + 1 }), false);
    assert.ok($("mode-badge").textContent.includes("本地私有研究"));
  } finally { global.fetch = oldFetch; global.ResizeObserver = oldObserver; global.FileReader = oldReader; }
});

test("returning to demo invalidates a still-pending local read", async () => {
  const { createDocument } = require("./test-dom.cjs");
  const doc = createDocument(fs.readFileSync(path.join(__dirname, "index.html"), "utf8"));
  const oldFetch = global.fetch, oldObserver = global.ResizeObserver, oldReader = global.FileReader;
  let reader;
  class DelayedReader { readAsText(file) { this.result = file.content; reader = this; } }
  global.fetch = async () => ({ ok: true, json: async () => clone() }); global.ResizeObserver = class { observe() {} }; global.FileReader = DelayedReader;
  try {
    const controller = app.mount(doc); await new Promise(resolve => setImmediate(resolve));
    const content = JSON.stringify(localClone()), pending = controller.importFile({ size: content.length, content });
    controller.returnToDemo(); reader.onload(); await pending;
    assert.ok(doc.getElementById("mode-badge").textContent.includes("Synthetic demo"));
    assert.equal(doc.getElementById("local-study-results").hidden, true);
  } finally { global.fetch = oldFetch; global.ResizeObserver = oldObserver; global.FileReader = oldReader; }
});
