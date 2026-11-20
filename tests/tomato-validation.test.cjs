const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../js/TomatoValidator/TomatoLeafValidation.js"), "utf8");

async function runValidation(payload) {
  const nodes = new Map();
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
      hidden: false,
      textContent: "",
      classList: { add() {}, remove() {}, toggle() {}, contains() { return true; } },
      setAttribute() {},
      addEventListener() {},
      focus() {},
      querySelectorAll() { return []; },
    });
    return nodes.get(id);
  }
  let classifications = 0;
  const window = {
    TOMATO_INSIGHT_API_BASE: "http://localhost:8765",
    TomatoInsightValidation: { strictValidation: true },
    TomatoInsightDisease: { classifyImageFile() { classifications++; } },
    TomatoInsightScan: { setClassificationScores() {}, endPipeline() {}, syncSaveInfoButton() {} },
  };
  vm.runInNewContext(script, {
    window,
    document: { getElementById: node },
    fetch: async () => ({ ok: true, json: async () => payload }),
    FormData,
    console: { log() {}, error() {} },
  });
  const file = new Blob(["image"], { type: "image/jpeg" });
  file.name = "photo.jpg";
  const verdict = await window.TomatoInsightValidation.validateImageFile(file);
  return { verdict, classifications, title: node("validation-alert-title").textContent };
}

test("explicit NonTomatoLeaf stops classification even when a legacy result says tomato", async () => {
  const result = await runValidation({ result: "TomatoLeaf", detected_class: "NonTomatoLeaf", confidence: 0.94 });
  assert.equal(result.verdict.isTomato, false);
  assert.equal(result.classifications, 0);
  assert.equal(result.title, "Not a tomato leaf");
});

test("metadata class IDs identify a non tomato detection", async () => {
  const result = await runValidation({
    metadata: { classNames: { 0: "TomatoLeaf", 1: "NonTomatoLeaf" } },
    images: [{ results: [{ class_id: 1, confidence: 0.91 }] }],
  });
  assert.equal(result.verdict.isTomato, false);
  assert.equal(result.classifications, 0);
  assert.equal(result.title, "Not a tomato leaf");
});

test("a confirmed tomato leaf proceeds to classification", async () => {
  const result = await runValidation({
    metadata: { classNames: { 0: "TomatoLeaf", 1: "NonTomatoLeaf" } },
    images: [{ results: [{ class_id: 0, confidence: 0.91 }] }],
  });
  assert.equal(result.verdict.isTomato, true);
  assert.equal(result.classifications, 1);
});

test("a low confidence tomato prediction stops before isolation", async () => {
  const result = await runValidation({
    images: [{ results: [{ name: "TomatoLeaf", confidence: 0.31 }] }],
  });
  assert.equal(result.verdict.isTomato, false);
  assert.equal(result.classifications, 0);
  assert.equal(result.title, "Invalid Image");
});
