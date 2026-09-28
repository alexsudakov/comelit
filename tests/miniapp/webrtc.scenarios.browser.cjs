const assert = require("node:assert/strict");
const os = require("node:os");
const path = require("node:path");

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (firstError) {
    const root =
      process.env.COMELIT_PLAYWRIGHT_ROOT ||
      path.join(os.homedir(), ".npm/_npx/e41f203b7505f1fb/node_modules");
    try {
      return require(path.join(root, "playwright"));
    } catch (_) {
      console.error(
        "SKIP: playwright unavailable; tried require(\"playwright\") and " +
          path.join(root, "playwright"),
      );
      console.error(firstError.message);
      process.exit(1);
    }
  }
}

const { chromium } = loadPlaywright();
const hostPath = path.resolve(
  __dirname,
  "../../custom_components/comelit/frontend/miniapp/host.js",
);
const ENTITY_ID = "camera.parking_6048";

async function setupPage(browser) {
  const page = await browser.newPage({ viewport: { width: 390, height: 780 } });
  const posts = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    if (request.url().includes("/diagnostics")) {
      posts.push(JSON.parse(request.postData() || "{}"));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: '{"ok":true}',
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body:
        '<div id="comelitCard"></div><div id="startupStatus"></div>' +
        '<div id="fatalError"></div>',
    });
  });
  await page.goto("http://miniapp.test/");
  await page.addScriptTag({ path: hostPath });
  await page.evaluate((entityId) => {
    window.makeViewer = () => {
      const Viewer = customElements.get("miniapp-picture-entity");
      const originalOpenWebRTC = Viewer.prototype._openWebRTC;
      Viewer.prototype._openWebRTC = function () {};
      const outer = document.createElement("div");
      outer.attachShadow({ mode: "open" });
      document.body.appendChild(outer);
      const viewer = new Viewer();
      viewer.setConfig({ entity: entityId, show_name: true });
      viewer.hass = {
        states: {
          [entityId]: {
            attributes: { friendly_name: "Parking" },
          },
        },
      };
      outer.shadowRoot.appendChild(viewer);
      Viewer.prototype._openWebRTC = originalOpenWebRTC;
      viewer._openHls = function () {};
      window.testViewer = viewer;
      return viewer;
    };
  }, ENTITY_ID);
  return { page, posts };
}

function event(posts, name) {
  return posts.find((payload) => payload.event === name);
}

function events(posts, name) {
  return posts.filter((payload) => payload.event === name);
}

async function flush(page, ms = 0) {
  if (ms > 0) {
    await page.clock.runFor(ms);
  }
  await page.waitForTimeout(0);
}

async function startViewer(page) {
  await page.evaluate((entityId) => {
    const viewer = window.makeViewer();
    viewer._startDiagnostics(entityId, viewer._requestGeneration);
    viewer._playbackMode = "webrtc";
    viewer._webrtcStartTime = performance.now();
  }, ENTITY_ID);
}

async function installSignallingTimer(page, withAnswer) {
  await page.evaluate(({ entityId, withAnswer }) => {
    const viewer = window.testViewer;
    const generation = viewer._requestGeneration;
    viewer._remoteStream = null;
    viewer._reportDiagnostics("config");
    if (withAnswer) {
      setTimeout(() => viewer._reportDiagnostics("answer"), 300);
    }
    viewer._webrtcTimer = setTimeout(() => {
      if (!viewer._remoteStream) {
        viewer._fallbackToHls(
          entityId,
          generation,
          "stats_deadline_other",
        );
      }
    }, 6000);
  }, { entityId: ENTITY_ID, withAnswer });
}

async function installStatsWatch(page, stats, iceState, withTrack) {
  await page.evaluate(({ entityId, stats, iceState, withTrack }) => {
    const viewer = window.testViewer;
    const peer = {
      iceConnectionState: iceState,
      getStats: async () =>
        new Map(stats.map((report, index) => ["r" + index, report])),
    };
    viewer._peerConnection = peer;
    viewer._playbackMode = "webrtc";
    viewer._webrtcStartTime = performance.now();
    if (withTrack) {
      viewer._remoteStream = new MediaStream();
      viewer._reportDiagnostics("track");
    }
    viewer._watchWebRTCFirstFrame(
      peer,
      viewer._video,
      entityId,
      viewer._requestGeneration,
    );
  }, { entityId: ENTITY_ID, stats, iceState, withTrack });
}

async function runWithPage(browser, callback) {
  const { page, posts } = await setupPage(browser);
  await page.clock.install();
  try {
    await startViewer(page);
    await callback(page, posts);
  } finally {
    await page.close();
  }
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: chromium.executablePath(),
  });
  try {
    await runWithPage(browser, async (page, posts) => {
      await installSignallingTimer(page, false);
      await flush(page, 6500);
      assert.equal(event(posts, "config")?.event, "config");
      assert.equal(event(posts, "answer"), undefined);
      assert.equal(event(posts, "track"), undefined);
      assert.equal(event(posts, "fallback")?.reason, "stats_deadline_other");
    });

    await runWithPage(browser, async (page, posts) => {
      await installSignallingTimer(page, true);
      await flush(page, 6500);
      assert.equal(event(posts, "answer")?.event, "answer");
      assert.equal(event(posts, "track"), undefined);
      assert.equal(event(posts, "fallback")?.reason, "stats_deadline_other");
    });

    await runWithPage(browser, async (page, posts) => {
      await installStatsWatch(
        page,
        [{
          type: "inbound-rtp",
          kind: "video",
          bytesReceived: 0,
          framesDecoded: 0,
        }],
        "checking",
        false,
      );
      await flush(page, 6000);
      assert.equal(event(posts, "rtp")?.state, "checking");
      assert.equal(event(posts, "rtp")?.counters.bytes_received, 0);
      assert.equal(event(posts, "fallback")?.reason, "stats_deadline_checking");
      assert.ok(
        event(posts, "fallback").elapsed_ms >= 5000 &&
          event(posts, "fallback").elapsed_ms <= 6000,
        JSON.stringify(event(posts, "fallback")),
      );
    });

    await runWithPage(browser, async (page, posts) => {
      await installStatsWatch(
        page,
        [{
          type: "inbound-rtp",
          kind: "video",
          bytesReceived: 0,
          framesDecoded: 0,
        }],
        "connected",
        true,
      );
      await flush(page, 9000);
      assert.equal(event(posts, "track")?.event, "track");
      assert.equal(event(posts, "rtp")?.counters.bytes_received, 0);
      assert.equal(event(posts, "fallback")?.reason, "stats_deadline_other");
      assert.ok(
        event(posts, "fallback").elapsed_ms >= 8000 &&
          event(posts, "fallback").elapsed_ms <= 9000,
        JSON.stringify(event(posts, "fallback")),
      );
    });

    await runWithPage(browser, async (page, posts) => {
      await installStatsWatch(
        page,
        [{
          type: "inbound-rtp",
          kind: "video",
          bytesReceived: 2048,
          framesDecoded: 0,
        }],
        "connected",
        true,
      );
      await flush(page, 9000);
      assert.equal(event(posts, "fallback"), undefined);
      assert.ok(event(posts, "rtp").counters.bytes_received > 0);
      assert.equal(event(posts, "rtp").counters.frames_decoded, 0);
    });

    await runWithPage(browser, async (page, posts) => {
      await page.evaluate(() => {
        const viewer = window.testViewer;
        viewer._playbackMode = null;
        const video = viewer._video;
        video.play = () => Promise.reject({ name: "NotAllowedError" });
        window.Hls = class {
          static isSupported() {
            return true;
          }
          static Events = { MANIFEST_PARSED: "manifest", ERROR: "error" };
          on(name, callback) {
            this["on" + name] = callback;
          }
          loadSource() {}
          attachMedia() {
            this.onmanifest();
          }
          destroy() {}
        };
        viewer._startHlsPlayback(
          "/local/master.m3u8",
          viewer._requestGeneration,
        );
      });
      await flush(page, 1000);
      assert.equal(event(posts, "hls_play")?.state, "NotAllowedError");
      assert.equal(event(posts, "hls_blocked")?.state, "NotAllowedError");
      assert.ok(events(posts, "hls_manifest").length >= 1);
      const label = await page.evaluate(
        () =>
          window.testViewer.shadowRoot.querySelector(".miniapp-video-label")
            .textContent,
      );
      assert.match(label, /нажмите Play/);
    });

    console.log("webrtc diagnostics scenarios: PASS");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
