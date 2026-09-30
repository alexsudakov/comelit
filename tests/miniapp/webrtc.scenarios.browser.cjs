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
const SECOND_ENTITY_ID = "camera.second_6048";
const MAX_COUNTERS = 16;
const COUNTER_KEY = /^[a-z][a-z0-9_]{0,39}$/;

async function setupPage(browser) {
  const page = await browser.newPage({ viewport: { width: 390, height: 780 } });
  const posts = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    if (request.url().includes("/diagnostics")) {
      const payload = JSON.parse(request.postData() || "{}");
      Object.defineProperty(payload, "__url", {
        value: request.url(),
        enumerable: false,
      });
      posts.push(payload);
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
    window.makeFakePeer = ({
      stats = [],
      iceState = "connected",
      gatheringState = "new",
    } = {}) => ({
      iceConnectionState: iceState,
      connectionState: "new",
      iceGatheringState: gatheringState,
      localDescription: null,
      remoteDescription: null,
      onicecandidate: null,
      ontrack: null,
      oniceconnectionstatechange: null,
      onconnectionstatechange: null,
      addTransceiver() {},
      async createOffer() {
        return { type: "offer", sdp: "v=0\r\n" };
      },
      async setLocalDescription(description) {
        this.localDescription = description;
      },
      async setRemoteDescription(description) {
        this.remoteDescription = description;
      },
      async addIceCandidate() {},
      async getStats() {
        return new Map(stats.map((report, index) => ["r" + index, report]));
      },
      close() {
        this.connectionState = "closed";
        this.iceConnectionState = "closed";
      },
    });

    window.makeViewer = (selectedEntityId = entityId) => {
      const Viewer = customElements.get("miniapp-picture-entity");
      const originalOpenMSE = Viewer.prototype._openMSE;
      const originalOpenWebRTC = Viewer.prototype._openWebRTC;
      Viewer.prototype._openMSE = function () {};
      Viewer.prototype._openWebRTC = function () {};
      const outer = document.createElement("div");
      outer.attachShadow({ mode: "open" });
      document.body.appendChild(outer);
      const viewer = new Viewer();
      viewer.setConfig({ entity: selectedEntityId, show_name: true });
      viewer.hass = {
        states: {
          [entityId]: {
            attributes: { friendly_name: "Parking" },
          },
          "camera.second_6048": {
            attributes: { friendly_name: "Second" },
          },
        },
      };
      outer.shadowRoot.appendChild(viewer);
      Viewer.prototype._openMSE = originalOpenMSE;
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

function assertSchemaBudget(posts) {
  for (const payload of posts) {
    const counters = payload.counters || {};
    const keys = Object.keys(counters);
    assert.ok(keys.length <= MAX_COUNTERS, JSON.stringify(payload));
    for (const key of keys) {
      assert.match(key, COUNTER_KEY, JSON.stringify(payload));
      assert.equal(Number.isInteger(counters[key]), true, JSON.stringify(payload));
      assert.ok(counters[key] >= 0 && counters[key] <= 1000000, JSON.stringify(payload));
    }
  }
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

async function finishScenario(posts) {
  assertSchemaBudget(posts);
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
    const peer = window.makeFakePeer({ stats, iceState });
    viewer._peerConnection = peer;
    viewer._playbackMode = "webrtc";
    viewer._webrtcStartTime = performance.now();
    if (withTrack) {
      viewer._remoteStream = new MediaStream();
      viewer._webrtcTrackSeen = true;
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

async function installPreTrackSampler(page, stats, iceState) {
  await page.evaluate(({ entityId, stats, iceState }) => {
    const viewer = window.testViewer;
    const peer = window.makeFakePeer({
      stats,
      iceState,
      gatheringState: "gathering",
    });
    viewer._peerConnection = peer;
    viewer._playbackMode = "webrtc";
    viewer._webrtcStartTime = performance.now();
    viewer._webrtcTrackSeen = false;
    viewer._startWebRTCDiagnosticsSampler(peer, viewer._requestGeneration);
    viewer._webrtcTimer = setTimeout(() => {
      if (!viewer._remoteStream) {
        viewer._fallbackToHls(
          entityId,
          viewer._requestGeneration,
          "stats_deadline_other",
        );
      }
    }, 6000);
  }, { entityId: ENTITY_ID, stats, iceState });
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
    args: ["--disable-crash-reporter"],
  });
  try {
    await runWithPage(browser, async (page, posts) => {
      await installSignallingTimer(page, false);
      // Playwright's fake clock may deliver the 6000 ms timer on the next
      // scheduler tick. Allow one bounded second for that tick.
      await flush(page, 7000);
      assert.equal(event(posts, "config")?.event, "config");
      assert.equal(event(posts, "answer"), undefined);
      assert.equal(event(posts, "track"), undefined);
      assert.equal(event(posts, "fallback")?.reason, "stats_deadline_other");
      await finishScenario(posts);
    });

    await runWithPage(browser, async (page, posts) => {
      await installSignallingTimer(page, true);
      await flush(page, 7000);
      assert.equal(event(posts, "answer")?.event, "answer");
      assert.equal(event(posts, "track"), undefined);
      assert.equal(event(posts, "fallback")?.reason, "stats_deadline_other");
      await finishScenario(posts);
    });

    await runWithPage(browser, async (page, posts) => {
      await installPreTrackSampler(
        page,
        [
          {
            type: "inbound-rtp",
            kind: "video",
            bytesReceived: 0,
            framesDecoded: 0,
          },
          { type: "local-candidate", candidateType: "host", protocol: "udp" },
          { type: "remote-candidate", candidateType: "srflx", protocol: "tcp" },
          { type: "candidate-pair", state: "waiting" },
        ],
        "checking",
      );
      await flush(page, 6500);
      assert.equal(event(posts, "ice")?.state, "checking");
      assert.equal(event(posts, "rtp")?.state, "checking");
      assert.equal(event(posts, "ice")?.counters.ice_gathering_state, 1);
      assert.equal(event(posts, "ice")?.counters.cand_host, 1);
      assert.equal(event(posts, "ice")?.counters.cand_srflx, 1);
      assert.equal(event(posts, "fallback")?.reason, "stats_deadline_other");
      // The 6000 ms signalling timer fires on the next fake-clock tick, so the reported
      // elapsed_ms lands one tick past the deadline boundary.
      assert.ok(
        event(posts, "fallback").elapsed_ms >= 6000 &&
          event(posts, "fallback").elapsed_ms <= 7000,
        JSON.stringify(event(posts, "fallback")),
      );
      await finishScenario(posts);
    });

    await runWithPage(browser, async (page, posts) => {
      await page.evaluate((entityId) => {
        const viewer = window.testViewer;
        const peer = window.makeFakePeer({
          iceState: "checking",
          gatheringState: "gathering",
          stats: [
            {
              type: "inbound-rtp",
              kind: "video",
              bytesReceived: 0,
              framesDecoded: 0,
            },
          ],
        });
        viewer._peerConnection = peer;
        viewer._playbackMode = "webrtc";
        viewer._webrtcStartTime = performance.now();
        viewer._webrtcTrackSeen = false;
        viewer._startWebRTCDiagnosticsSampler(peer, viewer._requestGeneration);
        setTimeout(() => {
          viewer._webrtcTrackSeen = true;
          viewer._stopWebRTCDiagnosticsSampler();
          viewer._reportDiagnostics("track");
          viewer._watchWebRTCFirstFrame(
            peer,
            viewer._video,
            entityId,
            viewer._requestGeneration,
          );
        }, 2200);
      }, ENTITY_ID);
      await flush(page, 4500);
      assert.ok(events(posts, "ice").length >= 1, JSON.stringify(posts));
      const trackPost = event(posts, "track");
      assert.ok(trackPost, JSON.stringify(posts));
      const iceAfterTrack = events(posts, "ice").filter(
        (payload) => payload.elapsed_ms > trackPost.elapsed_ms,
      );
      assert.equal(iceAfterTrack.length, 0, JSON.stringify(posts));
      await finishScenario(posts);
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
      await finishScenario(posts);
    });

    await runWithPage(browser, async (page, posts) => {
      // Reproduce the 1.7.6 production canary shape: signaling consumes almost
      // five seconds before the remote video track arrives. The media watchdog
      // must start at track time instead of inheriting that signaling delay.
      await flush(page, 4800);
      await page.evaluate((entityId) => {
        const viewer = window.testViewer;
        const peer = window.makeFakePeer({
          iceState: "checking",
          stats: [{
            type: "inbound-rtp",
            kind: "video",
            bytesReceived: 0,
            framesDecoded: 0,
          }],
        });
        viewer._peerConnection = peer;
        viewer._remoteStream = new MediaStream();
        viewer._webrtcTrackSeen = true;
        viewer._reportDiagnostics("answer");
        viewer._reportDiagnostics("track");
        viewer._watchWebRTCFirstFrame(
          peer,
          viewer._video,
          entityId,
          viewer._requestGeneration,
        );
      }, ENTITY_ID);

      await flush(page, 1200);
      assert.equal(event(posts, "fallback"), undefined, JSON.stringify(posts));

      await flush(page, 4000);
      assert.equal(
        event(posts, "fallback")?.reason,
        "stats_deadline_checking",
        JSON.stringify(posts),
      );
      assert.ok(
        event(posts, "fallback").elapsed_ms >= 9500 &&
          event(posts, "fallback").elapsed_ms <= 10100,
        JSON.stringify(event(posts, "fallback")),
      );
      await finishScenario(posts);
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
      await finishScenario(posts);
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
      await finishScenario(posts);
    });

    await runWithPage(browser, async (page, posts) => {
      await page.evaluate(({ firstEntityId, secondEntityId }) => {
        const viewer = window.testViewer;
        viewer._startDiagnostics(firstEntityId, viewer._requestGeneration);
        viewer._reportDiagnostics("config");
        viewer._reportDiagnostics("offer");
        viewer._requestGeneration += 1;
        viewer._startDiagnostics(secondEntityId, viewer._requestGeneration);
        viewer._reportDiagnostics("config");
      }, { firstEntityId: ENTITY_ID, secondEntityId: SECOND_ENTITY_ID });
      await flush(page, 1000);
      assert.equal(events(posts, "offer").length, 0, JSON.stringify(posts));
      assert.equal(
        posts.some((payload) => payload.__url.includes(encodeURIComponent(SECOND_ENTITY_ID)) && payload.event === "offer"),
        false,
        JSON.stringify(posts),
      );
      await finishScenario(posts);
    });

    await runWithPage(browser, async (page, posts) => {
      await page.evaluate(() => {
        const viewer = window.testViewer;
        viewer._reportDiagnostics("config");
        viewer._playbackMode = "webrtc";
        viewer._webrtcFallbackStarted = false;
        viewer.disconnectedCallback();
      });
      await flush(page, 50);
      const navigate = events(posts, "fallback").filter(
        (payload) => payload.reason === "navigate",
      );
      assert.equal(navigate.length, 1, JSON.stringify(posts));
      assert.equal(event(posts, "config")?.event, "config");
      await finishScenario(posts);
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
      // Let the rejected play() promise enqueue its throttled diagnostics
      // before advancing the fake clock that releases those timers.
      await page.waitForTimeout(0);
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
      await finishScenario(posts);
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
