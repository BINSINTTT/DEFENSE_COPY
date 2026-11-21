const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../js/plans.module.js"), "utf8");

async function planAfterPayments(rows, currentPackId = null) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, {
      textContent: "",
      hidden: false,
      classList: { remove() {}, toggle() {} },
      replaceChildren() {},
      appendChild() {},
    });
    return elements.get(id);
  };
  const packs = {
    starter: { packName: "Starter" },
    grower: { packName: "Grower" },
    season: { packName: "Season" },
  };
  const window = {
    TomatoInsightCredits: { getBalance: () => 5, getCurrentPackId: () => currentPackId },
    TomatoInsightPayments: {
      listPaymentsForCurrentUser: async () => rows,
      packFor: (id) => packs[id] || null,
      formatPhp: () => "₱49",
    },
    addEventListener() {},
  };
  vm.runInNewContext(script, {
    window,
    document: {
      readyState: "complete",
      getElementById: get,
      createElement: () => ({ textContent: "", append() {} }),
    },
    console: { warn() {} },
  });
  await new Promise((resolve) => setImmediate(resolve));
  return get("plans-current-plan").textContent;
}

test("no completed pack purchase shows Free Plan", async () => {
  assert.equal(await planAfterPayments([{ status: "pending", packId: "grower" }]), "Free Plan");
});

test("latest completed recognized pack becomes the current plan", async () => {
  const rows = [
    { status: "pending", packId: "season" },
    { status: "selected", packId: "grower" },
    { status: "paid", packId: "starter" },
  ];
  assert.equal(await planAfterPayments(rows), "Grower Plan");
});

test("chosen pack in credit balance stays current when history is missing", async () => {
  assert.equal(await planAfterPayments([], "season"), "Season Plan");
});
