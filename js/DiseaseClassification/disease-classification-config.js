window.TomatoInsightDiseaseConfig = {
  classifyProxyUrl: (window.TOMATO_INSIGHT_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "") + "/classify",
  predictUrl: "",
  apiKey: "",
  /** Require at least 70% confidence from the disease detector. */
  conf: 0.7,
  iou: null,
  imgsz: null,
};
