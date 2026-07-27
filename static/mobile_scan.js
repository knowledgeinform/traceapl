const mobileInput = document.getElementById("mobileQrInput");
const mobileForm = document.getElementById("mobileScanForm");
const startMobileButton = document.getElementById("startMobileCamera");
const stopMobileButton = document.getElementById("stopMobileCamera");
const scanStatus = document.getElementById("scanStatus");
const cameraDebug = document.getElementById("cameraDebug");
const reader = document.getElementById("mobileReader");

let mobileScanner = null;
let mobileSubmitted = false;
let nativeStream = null;
let nativeVideo = null;
let nativeCanvas = null;
let nativeLoop = null;
let nativeDetector = null;
let scannerMode = "idle";

function setStatus(message) {
  if (scanStatus) scanStatus.textContent = message;
}

function setDebug(message) {
  if (cameraDebug) cameraDebug.textContent = message || "";
}

function cleanScannedCode(value) {
  return (value || "").replace(/[\r\n\t]+/g, "").trim();
}

function submitMobileCode(decodedText) {
  const cleaned = cleanScannedCode(decodedText);
  if (!cleaned || mobileSubmitted) return;
  mobileSubmitted = true;
  mobileInput.value = cleaned;
  setStatus("Code found. Opening TraceAPL record...");
  if (navigator.vibrate) navigator.vibrate(80);
  stopScannerQuietly().finally(() => mobileForm.submit());
}

function getFormatsToSupport() {
  if (!window.Html5QrcodeSupportedFormats) return undefined;
  return [
    Html5QrcodeSupportedFormats.QR_CODE,
    Html5QrcodeSupportedFormats.CODE_128,
    Html5QrcodeSupportedFormats.CODE_39,
    Html5QrcodeSupportedFormats.CODE_93,
    Html5QrcodeSupportedFormats.CODABAR,
    Html5QrcodeSupportedFormats.DATA_MATRIX,
    Html5QrcodeSupportedFormats.EAN_13,
    Html5QrcodeSupportedFormats.EAN_8,
    Html5QrcodeSupportedFormats.ITF,
    Html5QrcodeSupportedFormats.PDF_417,
    Html5QrcodeSupportedFormats.UPC_A,
    Html5QrcodeSupportedFormats.UPC_E
  ].filter(Boolean);
}

function scannerConfig() {
  return {
    fps: 10,
    aspectRatio: 1.7777778,
    rememberLastUsedCamera: false,
    showTorchButtonIfSupported: true,
    disableFlip: false,
    formatsToSupport: getFormatsToSupport(),
    experimentalFeatures: {
      useBarCodeDetectorIfSupported: true
    }
  };
}

function cameraConstraints() {
  // Use the simple string form for best compatibility with iOS Safari and
  // html5-qrcode. Some versions reject { ideal: "environment" }.
  return {
    facingMode: "environment",
    width: { ideal: 1280 },
    height: { ideal: 720 }
  };
}

function explainCameraError(err) {
  const name = err && err.name ? err.name : "Camera error";
  const message = err && err.message ? err.message : String(err || "Unknown error");
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "Camera permission was denied. Allow camera access in the browser/site settings, then reload this page.";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "No camera was found by the browser.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "The camera is already in use by another app or browser tab.";
  }
  if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") {
    return "The browser rejected the rear-camera request. TraceAPL will need a softer camera constraint for this device.";
  }
  return `${name}: ${message}`;
}

async function stopScannerQuietly() {
  if (nativeLoop) {
    cancelAnimationFrame(nativeLoop);
    nativeLoop = null;
  }
  if (nativeStream) {
    nativeStream.getTracks().forEach((track) => track.stop());
    nativeStream = null;
  }
  if (mobileScanner) {
    try {
      await mobileScanner.stop();
    } catch (err) {
      // Already stopped or not fully started.
    }
    try {
      await mobileScanner.clear();
    } catch (err) {
      // Some versions do not need clear.
    }
    mobileScanner = null;
  }
  if (reader && scannerMode === "native") {
    reader.innerHTML = '<div class="scanner-placeholder"><strong>Rear camera scanner ready</strong><span>Tap Start Rear Camera and allow camera access.</span></div>';
  }
  scannerMode = "idle";
}

async function startHtml5QrcodeScanner() {
  scannerMode = "html5-qrcode";
  mobileScanner = new Html5Qrcode("mobileReader", { verbose: false });
  await mobileScanner.start(
    { facingMode: "environment" },
    scannerConfig(),
    submitMobileCode,
    () => {}
  );
  setStatus("Rear camera running. Point at a QR code or barcode. Try moving closer/farther and avoid glare.");
  setDebug("Scanner engine: html5-qrcode. Rear camera requested with environment-facing mode.");
}

async function startNativeScanner() {
  scannerMode = "native";
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error("This browser does not expose camera access. Use HTTPS and a current mobile browser.");
  }

  reader.innerHTML = "";
  nativeVideo = document.createElement("video");
  nativeVideo.setAttribute("playsinline", "true");
  nativeVideo.setAttribute("muted", "true");
  nativeVideo.autoplay = true;
  nativeVideo.className = "mobile-native-video";
  reader.appendChild(nativeVideo);

  nativeStream = await navigator.mediaDevices.getUserMedia({ video: cameraConstraints(), audio: false });
  nativeVideo.srcObject = nativeStream;
  await nativeVideo.play();

  const track = nativeStream.getVideoTracks()[0];
  const settings = track && track.getSettings ? track.getSettings() : {};
  setStatus("Camera started. Looking for a code...");
  setDebug(`Scanner engine: native browser camera${settings.facingMode ? ` (${settings.facingMode})` : ""}.`);

  if (!("BarcodeDetector" in window)) {
    setStatus("Camera started, but this browser does not include a built-in barcode detector and the scanner library did not load. Use manual entry or try a browser/network that can load the scanner library.");
    return;
  }

  try {
    nativeDetector = new BarcodeDetector({
      formats: ["qr_code", "code_128", "code_39", "code_93", "codabar", "data_matrix", "ean_13", "ean_8", "itf", "pdf417", "upc_a", "upc_e"]
    });
  } catch (err) {
    nativeDetector = new BarcodeDetector();
  }

  nativeCanvas = document.createElement("canvas");
  const ctx = nativeCanvas.getContext("2d", { willReadFrequently: true });

  async function scanFrame() {
    if (!nativeVideo || !nativeStream || mobileSubmitted) return;
    if (nativeVideo.readyState >= 2 && nativeVideo.videoWidth && nativeVideo.videoHeight) {
      nativeCanvas.width = nativeVideo.videoWidth;
      nativeCanvas.height = nativeVideo.videoHeight;
      ctx.drawImage(nativeVideo, 0, 0, nativeCanvas.width, nativeCanvas.height);
      try {
        const codes = await nativeDetector.detect(nativeCanvas);
        if (codes && codes.length > 0) {
          submitMobileCode(codes[0].rawValue || codes[0].rawData || "");
          return;
        }
      } catch (err) {
        setDebug("Native detector error: " + explainCameraError(err));
      }
    }
    nativeLoop = requestAnimationFrame(scanFrame);
  }
  nativeLoop = requestAnimationFrame(scanFrame);
}

async function startScanner() {
  mobileSubmitted = false;
  startMobileButton.disabled = true;
  stopMobileButton.disabled = false;
  setStatus("Starting rear camera...");
  setDebug("Start button clicked. Requesting camera access...");

  await stopScannerQuietly();

  try {
    if (window.Html5Qrcode) {
      await startHtml5QrcodeScanner();
    } else {
      setDebug("html5-qrcode library was not available. Trying native browser camera fallback.");
      await startNativeScanner();
    }
  } catch (err) {
    setStatus("Could not start camera: " + explainCameraError(err));
    setDebug("Raw error: " + String(err && err.stack ? err.stack : err));
    startMobileButton.disabled = false;
    stopMobileButton.disabled = true;
    await stopScannerQuietly();
  }
}

if (startMobileButton) {
  startMobileButton.addEventListener("click", startScanner);
  setStatus("Camera is stopped.");
  setDebug("Mobile scanner JavaScript loaded.");
}

if (stopMobileButton) {
  stopMobileButton.addEventListener("click", async () => {
    await stopScannerQuietly();
    startMobileButton.disabled = false;
    stopMobileButton.disabled = true;
    setStatus("Camera is stopped.");
    setDebug("Scanner stopped.");
  });
}

if (mobileInput) {
  mobileInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && mobileInput.value.trim()) {
      event.preventDefault();
      submitMobileCode(mobileInput.value);
    }
  });
}
