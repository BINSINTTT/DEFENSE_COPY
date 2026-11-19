window.TomatoInsightDiseaseConfig = {
  classifyProxyUrl: (window.TOMATO_INSIGHT_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "") + "/classify",
  predictUrl: "",
  apiKey: "",
  /** Use the new detector's default confidence threshold until it is calibrated. */
  conf: null,
  iou: null,
  imgsz: null,
};
