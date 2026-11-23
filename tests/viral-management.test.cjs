const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../js/DiseaseClassification/disease-recommendations.js"),
  "utf8"
);

function recommendations(options = {}) {
  const window = options.window || {};
  vm.runInNewContext(source, {
    window,
    document: options.document || { getElementById: () => null },
    localStorage: options.localStorage,
  });
  return window.TomatoInsightRecommendations;
}

test("the scan button always says View Intervention for detected results", () => {
  const button = { addEventListener() {}, setAttribute() {} };
  const document = {
    getElementById(id) {
      return id === "scan-treatment-btn" ? button : null;
    },
  };
  const recs = recommendations({ document });
  for (const [scores, severityLabel, affectedAreaPct] of [
    [{ healthy: 85 }, "Healthy", 0],
    [{ early_blight: 85 }, "Mild", 20],
    [{ early_blight: 85 }, "Moderate", 50],
    [{ early_blight: 85 }, "Severe", 80],
    [{ early_blight: 85 }, "Unable to Assess", null],
  ]) {
    recs.onScoresUpdated(scores, 19, {
      severityLabel,
      affectedAreaPct,
      severityPct: affectedAreaPct,
      severityAssessable: affectedAreaPct != null,
    });
    assert.equal(button.textContent, "View Intervention");
  }
});

for (const [disease, insect] of [["tlcv", "whiteflies"], ["spotted_wilt", "thrips"]]) {
  test(`${disease} uses severity-based management and names ${insect}`, () => {
    const recs = recommendations();
    const guides = [20, 50, 80].map((pct) =>
      recs.treatmentForBarKey(disease, 95, pct)
    );
    assert.deepEqual(guides.map((guide) => guide.severity), ["Mild", "Moderate", "Severe"]);
    assert.notDeepEqual(guides[0].actionSteps, guides[2].actionSteps);
    for (const guide of guides) {
      assert.match(guide.summary, /no cure/i);
      assert.match(guide.preventionTips.join(" "), new RegExp(insect, "i"));
      const html = recs.renderGuidesHtml([{ ...guide, barKey: disease }]);
      assert.match(html, /Management actions/);
      assert.match(html, /Prevent spread to other plants/);
      assert.doesNotMatch(html, /Treatment steps/);
    }
    assert.match(guides[2].actionSteps[0], /if infection is confirmed/i);
  });
}

test("the care panel omits the severity percentage banner", () => {
  const recs = recommendations();
  const guide = {
    ...recs.treatmentForBarKey("early_blight", 91, 86.6),
    barKey: "early_blight",
    pct: 91,
  };
  const html = recs.renderGuidesHtml([guide]);
  assert.match(html, /Intervention/);
  assert.match(html, /Treatment steps/);
  assert.doesNotMatch(html, /86\.6% affected/);
  assert.doesNotMatch(html, /scan-treatment-panel__urgency/);
});

test("TLCV intervention uses the Tomato Leaf Curl Virus label", () => {
  const recs = recommendations();
  const guide = recs.guidesForScores({ tlcv: 88 }, 35)[0];
  assert.equal(guide.diseaseName, "Tomato Leaf Curl Virus (TLCV)");
  const oldSavedGuide = { ...guide, diseaseName: "Tomato Yellow Leaf Curl Virus" };
  const html = recs.renderGuidesHtml([oldSavedGuide]);
  assert.match(html, /Tomato Leaf Curl Virus \(TLCV\)/);
  assert.doesNotMatch(html, /Tomato Yellow Leaf Curl Virus/);
});

test("a secondary Spotted Wilt detection gets its own management and prevention", () => {
  const recs = recommendations();
  const scores = { healthy: 31, tlcv: 0, early_blight: 0, spotted_wilt: 23 };
  const severity = {
    severityLabel: "Healthy",
    severityPct: 0,
    affectedAreaPct: 0,
    severityAssessable: true,
  };
  const guides = recs.guidesForScores(scores, severity);

  assert.equal(guides.length, 2);
  assert.equal(guides[0].barKey, "healthy");
  assert.match(guides[0].summary, /does not rule out the other model detection/i);
  assert.equal(guides[1].barKey, "spotted_wilt");
  assert.equal(guides[1].severity, "Unable to Assess");
  assert.equal(guides[1].severityPct, null);
  assert.match(guides[1].preventionTips.join(" "), /thrips/i);

  const html = recs.renderGuidesHtml(guides);
  assert.match(html, /Additional model detection · 23% confidence/);
  assert.match(html, /not a confirmed second diagnosis/);
  assert.match(html, /Its severity was not assessed/);
  assert.match(html, /Management actions/);
  assert.match(html, /Prevent spread to other plants/);
});

test("secondary severity is used only when measured for that disease", () => {
  const recs = recommendations();
  const scores = { healthy: 31, tlcv: 0, early_blight: 0, spotted_wilt: 23 };
  const withoutSecondarySeverity = {
    severityLabel: "Healthy",
    severityPct: 0,
    affectedAreaPct: 0,
    severityAssessable: true,
  };
  const withSecondarySeverity = {
    severityLabel: "Healthy",
    severityPct: 0,
    affectedAreaPct: 0,
    severityAssessable: true,
    diseaseSeverities: {
      spotted_wilt: {
        severityLabel: "Mild",
        severityPct: 18,
        affectedAreaPct: 18,
        severityAssessable: true,
      },
    },
  };
  const guides = recs.guidesForScores(scores, withSecondarySeverity);
  assert.equal(guides[1].severity, "Mild");
  assert.equal(guides[1].severityPct, 18);
  assert.notEqual(
    recs.recommendationKeyFor(scores, withSecondarySeverity),
    recs.recommendationKeyFor(scores, withoutSecondarySeverity)
  );
});

test("saving an online guide keeps the secondary disease plan", async () => {
  const values = new Map();
  const localStorage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
  };
  const window = {
    TomatoInsightGroqClient: {
      groqEnabled: () => true,
      groqOnlyMode: () => false,
      fetchCareRecommendation: async () => ({
        ok: true,
        groqUsed: true,
        guide: {
          diseaseName: "Healthy",
          urgencyNote: "No other concerns.",
          summary: "This leaf looks healthy.",
          actionSteps: ["Keep monitoring."],
          preventionTips: ["Check nearby plants."],
        },
      }),
    },
  };
  const recs = recommendations({ window, localStorage });
  const stored = await recs.captureForSave(
    19,
    { healthy: 31, tlcv: 0, early_blight: 0, spotted_wilt: 23 },
    { severityLabel: "Healthy", severityPct: 0, severityAssessable: true }
  );

  assert.equal(stored.guides.length, 2);
  assert.match(stored.guides[0].summary, /does not rule out the other model detection/i);
  assert.equal(stored.guides[1].barKey, "spotted_wilt");
  assert.match(stored.guides[1].preventionTips.join(" "), /thrips/i);
});
