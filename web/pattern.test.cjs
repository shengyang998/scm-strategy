/* SPDX-License-Identifier: BSD-3-Clause */
const test = require("node:test"), assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const pattern = require("./pattern.js"), app = require("./app.js");
const data = JSON.parse(fs.readFileSync(path.join(__dirname, "data/pattern-demo.json"), "utf8"));
const copy = () => structuredClone(data);
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const { createDocument } = require("./test-dom.cjs");
class Reader { readAsText(file) { this.result = file.content; queueMicrotask(() => this.onload()); } }

test("pattern demo has linked synthetic traces and full association states", () => {
  assert.equal(pattern.validate(data, true), data);
  assert.equal(data.associations.length, 14);
  assert.equal(data.records.length, data.generator.primary_participants);
  assert.ok(data.records.every(r => r.trajectories.left.knee_deg.length <= 2400));
  assert.equal(app.validateLocalPayload(data), data);
  assert.throws(() => app.validateDataset(data));
});

test("private pattern cannot be remote and schema rejects arbitrary fields", () => {
  let bad = copy(); bad.dataset_kind = "private_empirical";
  assert.equal(pattern.validate(bad), bad);
  assert.throws(() => pattern.validate(bad, true), /远端/);
  bad = copy(); bad.records[0].url = "https://example.invalid";
  assert.throws(() => pattern.validate(bad));
  bad = copy(); bad.generator.name = "https://example.invalid";
  assert.throws(() => pattern.validate(bad));
  bad = copy(); bad.records[0].trajectories.left.ankle_deg[0] = NaN;
  assert.throws(() => pattern.validate(bad), /轨迹/);
  bad = copy(); bad.associations.pop(); assert.throws(() => pattern.validate(bad), /14/);
});

test("pattern DOM renders paths, rejects third selection and never uploads local data", async () => {
  const doc = createDocument(html), $ = id => doc.getElementById(id);
  const oldFetch = global.fetch, oldObserver = global.ResizeObserver, oldReader = global.FileReader;
  const storage = Object.fromEntries(["localStorage", "sessionStorage", "indexedDB"].map(k => [k, Object.getOwnPropertyDescriptor(global, k)]));
  let requests = 0, storageReads = 0;
  global.fetch = async () => { requests++; return { ok: true, json: async () => copy() }; };
  global.ResizeObserver = class { observe() {} }; global.FileReader = Reader;
  for (const k of Object.keys(storage)) Object.defineProperty(global, k, { configurable: true, get() { storageReads++; throw new Error("no storage"); } });
  try {
    const controller = app.mount(doc); await new Promise(r => setImmediate(r));
    assert.equal($("legacy-model-content").hidden, true);
    assert.equal($("pattern-model-content").hidden, false);
    assert.ok($("pattern-model-content").textContent.includes("全部14个"));
    assert.ok($("pattern-model-content").textContent.includes("合成演示减少次数"));
    for (const r of data.records.slice(0, 3)) { $("point-select").value = r.participant_id; $("pick-person").click(); }
    assert.ok($("selection-status").textContent.includes("已选择两人"));
    assert.equal($("trajectory-panel").hidden, false);
    assert.equal($("trajectory-charts").children.length, 2);
    assert.ok(!$("comparison-cards").textContent.includes(data.records[2].participant_id));
    const local = copy(); local.dataset_kind = "private_empirical"; local.generator = {};
    for (const r of local.records) r.participant_id = "LOCAL-" + r.participant_id;
    const content = JSON.stringify(local);
    assert.equal(await controller.importFile({ size: content.length, content }), true);
    assert.equal(requests, 1); assert.equal(storageReads, 0);
    assert.ok($("mode-badge").textContent.includes("本地私有研究"));
    $("point-select").value = local.records[0].participant_id; $("pick-person").click();
    assert.ok($("trajectory-charts").textContent.includes("LOCAL-"));
    controller.returnToDemo();
    assert.equal(requests, 1); assert.equal(storageReads, 0);
    assert.ok(!$("trajectory-charts").textContent.includes("LOCAL-"));
    assert.ok(!$("comparison-cards").textContent.includes("LOCAL-"));
    assert.ok($("mode-badge").textContent.includes("Synthetic demo"));
    assert.equal($("local-study-results").hidden, true);
  } finally {
    global.fetch = oldFetch; global.ResizeObserver = oldObserver; global.FileReader = oldReader;
    for (const [k, v] of Object.entries(storage)) { if (v) Object.defineProperty(global, k, v); else delete global[k]; }
  }
});

test("private pattern response is rejected by initial remote loading", async () => {
  const doc = createDocument(html), oldFetch = global.fetch, oldObserver = global.ResizeObserver;
  global.fetch = async () => ({ ok: true, json: async () => ({ ...copy(), dataset_kind: "private_empirical" }) });
  global.ResizeObserver = class { observe() {} };
  try {
    app.mount(doc); await new Promise(r => setImmediate(r));
    assert.equal(doc.getElementById("explorer-content").hidden, true);
    assert.equal(doc.getElementById("load-state").classList.contains("is-error"), true);
  } finally { global.fetch = oldFetch; global.ResizeObserver = oldObserver; }
});

test("display accepts the native 2400-point cap and rejects excess or contradictory counts", () => {
  const full = copy(); full.configuration.display_max_points = 2400;
  const record = full.records[0];
  for (const side of ["left", "right"]) for (const key of ["knee_deg", "ankle_deg"]) {
    const before = record.trajectories[side][key];
    record.trajectories[side][key] = Array.from({ length: 2400 }, (_, i) => before[i % before.length]);
  }
  record.trajectory_sampling = { source_points: 2400, display_points: 2400, simplified: false };
  assert.equal(pattern.validate(full), full);
  const excess = structuredClone(full); excess.records[0].trajectories.left.knee_deg.push(0); excess.records[0].trajectories.left.ankle_deg.push(0);
  assert.throws(() => pattern.validate(excess), /轨迹/);
  const mismatch = structuredClone(full); mismatch.records[0].trajectory_sampling.simplified = true;
  assert.throws(() => pattern.validate(mismatch), /显示|采样/);
});
