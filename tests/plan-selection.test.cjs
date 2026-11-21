const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../js/Firebase/payments.module.js"), "utf8")
  .replace(/^import\s+.*?from\s+"[^"]+";\s*/gms, "")
  .replace(/^export /gm, "");

test("choosing a plan grants demo credits immediately without checkout", async () => {
  const buttons = [{ disabled: false }, { disabled: false }];
  const calls = [];
  const events = [];
  const window = {
    TomatoInsightCredits: {
      async addTopUpCredits(credits, pack) {
        calls.push({ credits, pack });
        return { ok: true, payment: { packId: pack.packId }, balance: 30 };
      },
      hideOutOfCreditModal() { calls.push("closed"); },
    },
    dispatchEvent(event) { events.push(event); },
  };
  vm.runInNewContext(source, {
    window,
    document: { querySelectorAll: () => buttons },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    console: { warn() {} },
  });
  await window.TomatoInsightPayments.selectPlan("grower");
  assert.equal(calls[0].credits, 25);
  assert.equal(calls[0].pack.packId, "grower");
  assert.equal(calls[0].pack.amountChargedPhp, 0);
  assert.equal(calls[0].pack.method, "plan_selection");
  assert.equal(events[0].detail.packId, "grower");
  assert.ok(buttons.every((button) => !button.disabled));
});
