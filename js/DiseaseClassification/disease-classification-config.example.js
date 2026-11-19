/**
 * Copy to disease-classification-config.js (gitignored). The local proxy reads
 * the object detection model URL and key from server/.env.
 */
window.TomatoInsightDiseaseConfig = {
  /** Local proxy (server/validation_api.py) — recommended to avoid CORS. */
  classifyProxyUrl: "http://127.0.0.1:8765/classify",
  predictUrl: "",
  apiKey: "",
  /** Require at least 70% confidence from the disease detector. */
  conf: 0.7,
  iou: null,
  imgsz: null,
};
