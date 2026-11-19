/**
 * Copy to disease-classification-config.js (gitignored). The local proxy reads
 * the object detection model URL and key from server/.env.
 */
window.TomatoInsightDiseaseConfig = {
  /** Local proxy isolates one leaf before forwarding to the disease model. */
  classifyProxyUrl: "http://127.0.0.1:8765/classify",
  /** Require at least 20% confidence from the disease detector. */
  conf: 0.2,
  iou: null,
  imgsz: null,
};
