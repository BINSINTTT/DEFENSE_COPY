const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../js/scan-calendar.js"), "utf8");

function loadCalendar() {
  const values = new Map();
  const window = { dispatchEvent() {} };
  const localStorage = {
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, value); },
  };
  vm.runInNewContext(script, {
    window,
    localStorage,
    Date,
    CustomEvent: class CustomEvent {},
  });
  return window.TomatoInsightScanCalendar;
}

test("each plot becomes due seven days after its own first scan", () => {
  const calendar = loadCalendar();
  calendar.write({ enabled: true });
  calendar.chooseDate("2026-11-01");
  const plot1 = {
    savedAt: calendar.savedAtForScan(),
    scanDayIso: calendar.scanDayIsoForSave(),
    week: calendar.weekForScan(),
  };
  calendar.chooseDate("2026-11-04");
  const plot2 = {
    savedAt: calendar.savedAtForScan(),
    scanDayIso: calendar.scanDayIsoForSave(),
    week: calendar.weekForScan(),
  };

  calendar.chooseDate("2026-11-08");
  assert.equal(calendar.reminderWeekForPlant(plot1.savedAt, plot1.week, plot1.scanDayIso), 5);
  assert.equal(calendar.reminderWeekForPlant(plot2.savedAt, plot2.week, plot2.scanDayIso), null);

  calendar.chooseDate("2026-11-11");
  assert.equal(calendar.reminderWeekForPlant(plot2.savedAt, plot2.week, plot2.scanDayIso), 5);
});

test("older scans use their saved timestamp, and missing dates do not trigger a reminder", () => {
  const calendar = loadCalendar();
  calendar.write({
    enabled: true,
    anchor: "2026-11-01",
    selected: "2026-11-08",
    nextDue: "2026-11-08",
  });

  assert.equal(calendar.reminderWeekForPlant("2026-11-04T12:00:00", 4), null);
  assert.equal(calendar.reminderWeekForPlant("2026-11-01T12:00:00", 4), 5);
  assert.equal(calendar.reminderWeekForPlant("", 4), null);
});

test("reminder timing follows each scan across farm weeks and date boundaries", () => {
  function addDays(iso, days) {
    const [year, month, day] = iso.split("-").map(Number);
    return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
  }

  for (const anchor of ["2026-01-01", "2026-11-01", "2026-12-28"]) {
    for (const offset of [0, 1, 3, 6, 7, 10, 25, 55]) {
      const calendar = loadCalendar();
      const scanDay = addDays(anchor, offset);
      const latestWeek = 4 + Math.floor(offset / 7);
      calendar.write({ enabled: true, anchor, selected: addDays(scanDay, 6) });
      assert.equal(
        calendar.reminderWeekForPlant("", latestWeek, scanDay),
        null,
        `${anchor} plot scanned ${scanDay} should not be due after 6 days`
      );

      calendar.write({ enabled: true, anchor, selected: addDays(scanDay, 7) });
      assert.equal(
        calendar.reminderWeekForPlant("", latestWeek, scanDay),
        latestWeek + 1,
        `${anchor} plot scanned ${scanDay} should be due after 7 days`
      );
    }
  }

  const calendar = loadCalendar();
  calendar.write({ enabled: true, anchor: "2026-11-01", selected: "2027-01-03" });
  assert.equal(calendar.reminderWeekForPlant("", 12, "2026-12-27"), null);
});
