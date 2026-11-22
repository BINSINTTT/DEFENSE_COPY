const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../js/DiseaseClassification/disease-recommendations.js"),
  "utf8"
);

function recommendations() {
  const window = {};
  vm.runInNewContext(source, {
    window,
    document: { getElementById: () => null },
  });
  return window.TomatoInsightRecommendations;
}

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
