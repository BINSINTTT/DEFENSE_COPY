(function () {
  const DEFAULTS = {
    classifyProxyUrl: (window.TOMATO_INSIGHT_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "") + "/classify",
    severityProxyUrl:
      (window.TOMATO_INSIGHT_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "") + "/assess-severity",
    /** Minimum confidence required for a disease detection. */
    conf: 0.2,
    iou: null,

    imgsz: null,
  };

  const userConfig = window.TomatoInsightDiseaseConfig || {};
  const config = { ...DEFAULTS, ...userConfig };

  /** Existing dashboard classes; match the detector's class names, not numeric IDs. */
  const DISEASE_LABELS = [
    { barKey: "healthy", names: ["healthy", "tomatohealthy"] },
    {
      barKey: "tlcv",
      names: ["yellowleafcurlvirus", "tomatoyellowleafcurlvirus", "yellow leaf curl virus", "tomatoleafcurlvirus", "tomatoleafcurlvirustlcv", "tomato leaf curl virus", "tlcv", "yellow leaf curl"],
    },
    {
      barKey: "early_blight",
      names: ["earlyblightvirus", "early blight", "earlyblight", "tomatoearlyblight"],
    },
    {
      barKey: "spotted_wilt",
      names: ["spottedwiltvirus", "tomatospottedwiltvirus", "spotted wilt", "spottedwilt", "tswv"],
    },
  ];

  function normalizeKey(name) {
    return String(name || "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
  }

  function normalizeConfidence(value) {
    const n = Number(value);
    if (Number.isNaN(n)) return 0;
    return n > 1 ? n / 100 : n;
  }

  function classNameFor(item, classNames) {
    const raw = item?.name ?? item?.class_name ?? item?.className ?? item?.label;
    const classId = item?.class_id ?? item?.classId ?? item?.class ?? item?.category_id;
    const name = raw != null && String(raw).trim() ? raw : classId;
    if (name == null || String(name).trim() === "") return "";
    const value = String(name).trim();
    if (/^\d+$/.test(value)) {
      const mapped = classNames?.[value];
      return mapped != null ? String(mapped).trim() : "";
    }
    return value;
  }

  function collectResultItems(payload) {
    const items = [];
    if (!payload || typeof payload !== "object") return items;
    const defaultNames = payload.metadata?.classNames ?? payload.metadata?.class_names
      ?? payload.classNames ?? payload.class_names;
    if (Array.isArray(payload.images)) {
      payload.images.forEach((image) => {
        const names = image?.classNames ?? image?.class_names ?? defaultNames;
        const rows = image?.results ?? image?.predictions ?? [];
        if (Array.isArray(rows)) rows.forEach((item) => items.push({ item, names }));
      });
    }
    if (Array.isArray(payload.results)) {
      payload.results.forEach((item) => items.push({ item, names: defaultNames }));
    }
    if (Array.isArray(payload.predictions)) {
      payload.predictions.forEach((item) => items.push({ item, names: defaultNames }));
    }
    return items;
  }

  function extractPredictions(payload) {
    const bestByClass = new Map();

    collectResultItems(payload).forEach(({ item, names }) => {
      const cleaned = classNameFor(item, names);
      if (!cleaned) return;
      const key = normalizeKey(cleaned);
      const confidence = normalizeConfidence(item?.confidence ?? item?.score ?? 0);
      const previous = bestByClass.get(key);
      if (!previous || confidence > previous.confidence) {
        bestByClass.set(key, { name: cleaned, confidence });
      }
    });

    return [...bestByClass.values()].sort((a, b) => b.confidence - a.confidence);
  }

  function topBarKeyFromScores(scores) {
    let topKey = "";
    let topPct = -1;
    ["healthy", "tlcv", "early_blight", "spotted_wilt"].forEach((key) => {
      const pct = Math.min(100, Math.max(0, Number(scores?.[key]) || 0));
      if (pct > topPct) {
        topPct = pct;
        topKey = key;
      }
    });
    return topPct > 0 ? topKey : "";
  }

  function normalizeDiseaseSeverities(raw) {
    if (!raw || typeof raw !== "object") return {};
    const normalized = {};
    Object.entries(raw).forEach(([key, value]) => {
      if (!value || typeof value !== "object") return;
      const pctRaw = value.severity_pct ?? value.severityPct ?? value.affected_area_pct;
      const pct = pctRaw != null && Number.isFinite(Number(pctRaw))
        ? Math.min(100, Math.max(0, Number(pctRaw)))
        : null;
      normalized[key] = {
        severityPct: pct,
        severityLabel: String(value.severity || value.severityLabel || "Unable to Assess"),
        affectedAreaPct: pct,
        severityAssessable: Boolean(value.measurable) && pct != null,
        severityReason: String(value.reason || ""),
        metric: String(value.metric || "visual_symptom_extent"),
        evidence: Array.isArray(value.evidence) ? value.evidence.map(String) : [],
      };
    });
    return normalized;
  }

  /**
   * Separate image-based symptom assessment. Classification scores identify
   * disease candidates only; the backend never converts confidence to severity.
   */
  async function assessSymptomSeverity(file, diseaseKey, leafMaskPng) {
    const unable = {
      severityPct: null,
      severityLabel: "Unable to Assess",
      affectedAreaPct: null,
      severityAssessable: false,
      severitySource: "assessment_unavailable",
      severityReason: "request_failed",
      diseaseSeverities: {},
      rescanRecommended: false,
    };

    const url = String(config.severityProxyUrl || "").trim();
    if (!url || !file || !diseaseKey) return unable;

    try {
      const form = new FormData();
      form.append("file", file, file.name || "upload.jpg");
      form.append("disease", diseaseKey);
      form.append("bar_key", diseaseKey);
      if (leafMaskPng) form.append("leaf_mask_png", leafMaskPng);
      const response = await fetch(url, { method: "POST", body: form });
      const payload = await readJsonResponse(response);
      if (!response.ok || !payload?.ok) {
        return {
          ...unable,
          severityReason: payload?.reason || payload?.error || `http_${response.status}`,
        };
      }

      const label = String(payload.severity || "Unable to Assess");
      const measurable = Boolean(payload.measurable);
      const areaRaw = payload.severity_pct ?? payload.affected_area_pct;
      const isHealthy = diseaseKey === "healthy" || label === "Healthy";
      const areaPct = isHealthy
        ? areaRaw != null && Number.isFinite(Number(areaRaw))
          ? Math.min(100, Math.max(0, Number(areaRaw)))
          : 0
        : measurable && areaRaw != null && Number.isFinite(Number(areaRaw))
          ? Math.min(100, Math.max(0, Number(areaRaw)))
          : null;

      return {
        severityPct: areaPct,
        severityLabel: isHealthy ? "Healthy" : label,
        affectedAreaPct: areaPct,
        severityAssessable: isHealthy ? true : measurable && label !== "Unable to Assess",
        severitySource: String(payload.source || "unknown"),
        severityReason: String(payload.reason || ""),
        diseaseSeverities: normalizeDiseaseSeverities(
          payload.disease_severities || payload.diseaseSeverities
        ),
        imageQuality: payload.image_quality || payload.imageQuality || null,
        rescanRecommended: Boolean(payload.rescan_recommended ?? payload.rescanRecommended),
        severityModel: payload.model || null,
      };
    } catch (err) {
      console.warn("[TomatoInsight] Severity assessment failed:", err);
      return { ...unable, severityReason: "network" };
    }
  }

  function mapToBarScores(predictions) {
    const byKey = new Map();
    predictions.forEach((item) => {
      byKey.set(normalizeKey(item.name), item.confidence);
    });

    const scores = {
      healthy: 0,
      tlcv: 0,
      early_blight: 0,
      spotted_wilt: 0,
    };

    DISEASE_LABELS.forEach(({ barKey, names }) => {
      let best = 0;
      names.forEach((label) => {
        const key = normalizeKey(label);
        if (byKey.has(key)) best = Math.max(best, byKey.get(key));
      });
      scores[barKey] = Math.round(best * 1000) / 10;
    });

    return scores;
  }

  function setClassifying(active) {
    const section = document.querySelector(".scan-results");
    section?.classList.toggle("scan-results--loading", active);
  }

  function showClassificationMessage(title, message, variant) {
    const el = document.getElementById("validation-alert");
    const titleNode = document.getElementById("validation-alert-title");
    const messageNode = document.getElementById("validation-alert-message");
    if (!el || !titleNode || !messageNode) {
      console.warn("[TomatoInsight]", title, message);
      return;
    }
    el.classList.remove(
      "validation-alert--success",
      "validation-alert--warning",
      "validation-alert--error"
    );
    el.classList.add(`validation-alert--${variant || "warning"}`);
    titleNode.textContent = title;
    messageNode.hidden = false;
    messageNode.textContent = message;
    document.getElementById("validation-alert-guide")?.setAttribute("hidden", "");
    el.classList.remove("validation-alert--invalid-image");
    el.hidden = false;
  }

  function buildClassifierForm(file) {
    const form = new FormData();
    form.append("file", file, file.name || "upload.jpg");
    ["conf", "iou", "imgsz"].forEach((key) => {
      const value = config[key];
      if (value === null || value === undefined || String(value).trim() === "") return;
      form.append(key, String(value).trim());
    });
    return form;
  }

  async function postToClassifier(file) {
    return fetch(config.classifyProxyUrl.trim(), {
      method: "POST",
      body: buildClassifierForm(file),
    });
  }

  async function readJsonResponse(response) {
    const text = await response.text();
    try {
      return JSON.parse(text);
    } catch {
      return {
        error: "invalid_json",
        message: `The model service returned HTTP ${response.status} with an invalid response. Retry the scan; if this repeats, check the deployment logs.`,
      };
    }
  }

  async function classifyImageFile(file, loadToken, requestId) {
    const stopLoading = () => window.TomatoInsightValidation?.finishLoading?.(loadToken);
    const stillCurrent = () =>
      !window.TomatoInsightValidation?.isCurrentRequest ||
      window.TomatoInsightValidation.isCurrentRequest(requestId);

    if (!file?.type?.startsWith("image/")) {
      stopLoading();
      return { ok: false, error: "not_an_image" };
    }

    if (!config.classifyProxyUrl?.trim()) {
      console.warn("[TomatoInsight] Disease classification not configured.");
      stopLoading();
      return { ok: false, error: "missing_config" };
    }

    setClassifying(true);
    window.TomatoInsightScan?.setScanStage?.("Isolating leaf and detecting disease…");

    try {
      const response = await postToClassifier(file);

      const result = await readJsonResponse(response);
      const { leaf_mask_png: leafMaskPng, ...classificationResult } = result || {};
      console.log("[TomatoInsight] Disease classification:", classificationResult);

      if (!response.ok) {
        if (!stillCurrent()) return { ok: false, cancelled: true };
        window.TomatoInsightScan?.setClassificationScores?.({});
        const detail =
          result?.message ||
          result?.error ||
          `Classification failed (${response.status}). Restart server/start.ps1 if /classify was added recently.`;
        console.error("[TomatoInsight]", detail);
        const needsAnotherLeaf = result?.error === "leaf_isolation_failed";
        showClassificationMessage(
          needsAnotherLeaf ? "Scan another leaf" : "Classification failed",
          detail,
          needsAnotherLeaf ? "warning" : "error"
        );
        return { ok: false, error: needsAnotherLeaf ? "leaf_isolation_failed" : "http_error", detail, raw: classificationResult };
      }

      const predictions = extractPredictions(classificationResult);
      const scores = mapToBarScores(predictions);
      const totalScore = Object.values(scores).reduce((sum, value) => sum + (Number(value) || 0), 0);
      if (!predictions.length || totalScore <= 0) {
        if (!stillCurrent()) return { ok: false, cancelled: true };
        window.TomatoInsightScan?.setClassificationScores?.({});
        showClassificationMessage(
          "Scan another leaf",
          "We couldn't identify a disease from this scan. Please scan another tomato leaf in bright, even light.",
          "warning"
        );
        return { ok: false, error: "empty_predictions", raw: classificationResult };
      }

      if (!stillCurrent()) return { ok: false, cancelled: true };

      const diseaseKey = topBarKeyFromScores(scores);
      window.TomatoInsightScan?.setScanStage?.("Measuring symptom severity…");
      const severity = await assessSymptomSeverity(file, diseaseKey, leafMaskPng);
      if (!stillCurrent()) return { ok: false, cancelled: true };

      console.log("[TomatoInsight] Detection scores:", scores, "OpenCV severity:", severity);
      window.TomatoInsightScan?.setClassificationScores?.(scores, severity);
      if (!severity.severityAssessable && severity.rescanRecommended) {
        const qualityIssues = Array.isArray(severity.imageQuality?.issues)
          ? severity.imageQuality.issues.filter(Boolean).join(", ")
          : "";
        window.TomatoInsightValidation?.showNotice?.(
          "warning",
          "Please scan the leaf again",
          `The disease classification completed, but symptom severity could not be measured reliably${
            qualityIssues ? ` because of: ${qualityIssues}` : " from this image"
          }. Use bright, even lighting, keep the full leaf in focus, and avoid shadows or glare.`
        );
      }
      return { ok: true, scores, predictions, ...severity, raw: classificationResult };
    } catch (err) {
      console.error("[TomatoInsight] Disease classification error:", err);
      const msg = String(err?.message || "");
      const hint =
        msg === "Failed to fetch"
          ? "Could not reach the classification service. Run server\\start.ps1 and use http://127.0.0.1:8765/"
          : msg;
      showClassificationMessage("Classification failed", hint, "error");
      return { ok: false, error: "network", detail: err?.message };
    } finally {
      setClassifying(false);
      stopLoading();
    }
  }

  window.TomatoInsightDisease = {
    classifyImageFile,
    mapToBarScores,
    extractPredictions,
    assessSymptomSeverity,
    topBarKeyFromScores,
  };
})();
