window.TomatoInsightDiseaseConfig = {
  classifyProxyUrl: (window.TOMATO_INSIGHT_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "") + "/classify",
  /** Require at least 20% confidence from the disease detector. */
  conf: 0.2,
  iou: null,
  imgsz: null,
};
