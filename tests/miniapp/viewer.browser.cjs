const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");

const hostPath = path.resolve(
  __dirname,
  "../../custom_components/comelit/frontend/miniapp/host.js",
);

async function newViewer(page) {
  await page.setContent(
    '<div id="comelitCard"></div><div id="startupStatus"></div>' +
    '<div id="fatalError"></div>',
  );
  await page.addScriptTag({ path: hostPath });
  await page.evaluate(() => {
    const Viewer = customElements.get("miniapp-picture-entity");
    Viewer.prototype._openMSE = function () {};
    Viewer.prototype._openWebRTC = function () {};
    const outer = document.createElement("div");
    outer.attachShadow({ mode: "open" });
    document.body.appendChild(outer);
    const viewer = new Viewer();
    viewer.setConfig({ entity: "camera.parking_6048", show_name: true });
    viewer.hass = {
      states: {
        "camera.parking_6048": {
          attributes: { friendly_name: "Паркинг 6048" },
        },
      },
    };
    outer.shadowRoot.appendChild(viewer);
    window.testViewer = viewer;
  });
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: chromium.executablePath(),
    args: ["--disable-crash-reporter"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 780 } });
    await newViewer(page);

    const measurements = await page.evaluate(async () => {
      const root = window.testViewer.shadowRoot;
      const stage = root.querySelector(".miniapp-video-stage");
      const video = root.querySelector("video");
      const before = stage.getBoundingClientRect();
      const canvas = document.createElement("canvas");
      canvas.width = 240;
      canvas.height = 1000;
      const context = canvas.getContext("2d");
      context.fillStyle = "red";
      context.fillRect(0, 0, canvas.width, canvas.height);
      const stream = canvas.captureStream(25);
      video.srcObject = stream;
      await new Promise((resolve, reject) => {
        video.addEventListener("loadeddata", resolve, { once: true });
        video.play().catch(reject);
      });
      const after = stage.getBoundingClientRect();
      const videoRect = video.getBoundingClientRect();
      window.testViewer._playbackMode = "hls";
      window.testViewer._markFirstHlsFrame(window.testViewer._requestGeneration);
      const label = root.querySelector(".miniapp-video-label").textContent;
      stream.getTracks().forEach((track) => track.stop());
      return {
        beforeHeight: before.height,
        afterHeight: after.height,
        videoHeight: videoRect.height,
        videoWidth: videoRect.width,
        naturalHeight: video.videoHeight,
        label,
      };
    });
    assert.equal(measurements.naturalHeight, 1000);
    assert.ok(measurements.afterHeight <= 320, JSON.stringify(measurements));
    assert.equal(measurements.beforeHeight, measurements.afterHeight);
    assert.ok(measurements.videoHeight <= 320, JSON.stringify(measurements));
    assert.ok(measurements.videoWidth <= 390, JSON.stringify(measurements));
    assert.match(measurements.label, /HLS · первый кадр [\d.]+ с/);

    async function verifyFallback(iceState, earliest, latest) {
      const fallbackPage = await browser.newPage();
      await fallbackPage.clock.install();
      await newViewer(fallbackPage);
      await fallbackPage.evaluate((state) => {
      const viewer = window.testViewer;
      const peer = {
        iceConnectionState: state,
        getStats: async () => new Map([["video", {
          type: "inbound-rtp",
          kind: "video",
          bytesReceived: 0,
          framesDecoded: 0,
        }]]),
      };
      viewer._peerConnection = peer;
      viewer._playbackMode = "webrtc";
      viewer._webrtcStartTime = performance.now();
      viewer._fallbackToHls = function () {
        window.fallbackAt = performance.now() - this._webrtcStartTime;
        this._webrtcFallbackStarted = true;
        clearInterval(this._webrtcStatsTimer);
      };
      viewer._watchWebRTCFirstFrame(
        peer, viewer._video, "camera.parking_6048", viewer._requestGeneration,
      );
      }, iceState);
      await fallbackPage.clock.runFor(latest);
      const fallbackAt = await fallbackPage.evaluate(() => window.fallbackAt);
      assert.ok(
        fallbackAt >= earliest && fallbackAt <= latest,
        iceState + ": " + fallbackAt,
      );
      await fallbackPage.close();
    }
    await verifyFallback("checking", 5000, 6000);
    await verifyFallback("connected", 8000, 9000);

    const priorityPage = await browser.newPage();
    await priorityPage.setContent(
      '<div id="comelitCard"></div><div id="startupStatus"></div>' +
      '<div id="fatalError"></div>',
    );
    await priorityPage.addScriptTag({ path: hostPath });
    const priority = await priorityPage.evaluate(() => {
      let mse = 0;
      let webrtc = 0;
      const Viewer = customElements.get("miniapp-picture-entity");
      Viewer.prototype._openMSE = function () { mse += 1; };
      Viewer.prototype._openWebRTC = function () { webrtc += 1; };

      const ordinary = new Viewer();
      ordinary.setConfig({entity: "camera.parking_6048", show_name: true});
      ordinary.hass = {
        states: {"camera.parking_6048": {attributes: {friendly_name: "Parking"}}},
      };
      document.body.appendChild(ordinary);
      return {mse, webrtc};
    });
    assert.deepEqual(priority, {mse: 1, webrtc: 0});
    await priorityPage.close();

    console.log("viewer shadow layout and stalled-ICE fallback: PASS");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
