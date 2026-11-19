const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(
  path.join(__dirname, "../js/DiseaseClassification/disease-classification.js"),
  "utf8"
);

function loadClassifier(fetch) {
  const window = {
    TOMATO_INSIGHT_API_BASE: "http://localhost:8765",
    TomatoInsightValidation: { finishLoading() {} },
    TomatoInsightScan: { setClassificationScores() {} },
  };
  const context = {
    window,
    document: { querySelector: () => null, getElementById: () => null },
    fetch,
    FormData,
    console: { log() {}, warn() {}, error() {} },
    setTimeout: (callback) => callback(),
  };
  vm.runInNewContext(script, context);
  return window.TomatoInsightDisease;
}

test("detector class IDs use metadata names and the strongest box per class", () => {
  const classifier = loadClassifier();
  const response = {
    metadata: {
      classNames: { 0: "Healthy", 1: "YellowLeafCurlVirus", 2: "EarlyBlightVirus", 3: "SpottedWiltVirus" },
    },
    images: [{ results: [
      { class_id: 2, confidence: 0.42 },
      { class_id: 2, confidence: 0.86 },
      { class_id: 3, confidence: 0.34 },
    ] }],
  };
  const predictions = classifier.extractPredictions(response);
  assert.equal(predictions.length, 2);
  assert.equal(predictions[0].name, "EarlyBlightVirus");
  assert.equal(predictions[0].confidence, 0.86);
  assert.equal(classifier.mapToBarScores(predictions).early_blight, 86);
});

test("unrecognized detector classes do not become a disease score", () => {
  const classifier = loadClassifier();
  const scores = classifier.mapToBarScores([
    { name: "Unhealthy background", confidence: 0.99 },
  ]);
  assert.equal(scores.healthy, 0);
  assert.equal(classifier.topBarKeyFromScores(scores), "");
});

test("one detector request is followed by OpenCV assessment, with no specialist request", async () => {
  const calls = [];
  const classifier = loadClassifier(async (url, options) => {
    calls.push(url);
    if (url.endsWith("/classify")) assert.equal(options.body.get("conf"), "0.7");
    const payload = url.endsWith("/classify")
      ? { images: [{ results: [{ name: "SpottedWiltVirus", confidence: 0.9 }] }] }
      : { ok: true, severity: "Mild", severity_pct: 18, measurable: true, source: "opencv_color_segmentation" };
    return { ok: true, status: 200, text: async () => JSON.stringify(payload) };
  });
  const file = new Blob(["image"], { type: "image/jpeg" });
  file.name = "leaf.jpg";
  const result = await classifier.classifyImageFile(file);
  assert.equal(result.ok, true);
  assert.equal(result.scores.spotted_wilt, 90);
  assert.equal(result.affectedAreaPct, 18);
  assert.deepEqual(calls, ["http://localhost:8765/classify", "http://localhost:8765/assess-severity"]);
});

test("HTML gateway errors become a useful message", async () => {
  const classifier = loadClassifier(async () => ({
    ok: false,
    status: 502,
    text: async () => "<!DOCTYPE html><title>502</title>",
  }));
  const file = new Blob(["image"], { type: "image/jpeg" });
  file.name = "leaf.jpg";
  const result = await classifier.classifyImageFile(file);
  assert.equal(result.ok, false);
  assert.match(result.detail, /HTTP 502.*Retry the scan/);
  assert.doesNotMatch(result.detail, /DOCTYPE/);
});
