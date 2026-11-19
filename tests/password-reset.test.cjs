const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../js/Firebase/firebase-auth.module.js"),
  "utf8"
);

function loadAuth(sendPasswordResetEmail) {
  const window = {
    TOMATO_INSIGHT_FIREBASE_CONFIG: { apiKey: "test" },
    location: { href: "https://example.com/html/login.html" },
    dispatchEvent() {},
  };
  const importsRemoved = source.replace(
    /^import[\s\S]*?from "https:\/\/www\.gstatic\.com\/firebasejs\/[^\"]+";\r?\n/gm,
    ""
  );
  vm.runInNewContext(importsRemoved, {
    window,
    URL,
    Event,
    console: { error() {}, warn() {} },
    getApps: () => [],
    initializeApp: () => ({}),
    getAuth: () => ({}),
    isSupported: async () => false,
    setPersistence: async () => {},
    browserLocalPersistence: {},
    browserSessionPersistence: {},
    firebaseSendPasswordResetEmail: sendPasswordResetEmail,
  });
  return window.TomatoInsightAuth;
}

test("forgot password sends a reset request without checking sign-in methods", async () => {
  const requests = [];
  const auth = loadAuth(async (_auth, email, settings) => {
    requests.push({ email, settings });
  });

  const result = await auth.sendPasswordResetEmail("  farmer@gmail.com  ");

  assert.equal(result.ok, true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].email, "farmer@gmail.com");
  assert.equal(requests[0].settings.url, "https://example.com/html/reset-password.html");
});
