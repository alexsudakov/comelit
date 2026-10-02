const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");

const cardPath = path.resolve(
  __dirname,
  "../../custom_components/comelit/frontend/comelit-card.js",
);
const viewerPath = path.resolve(
  __dirname,
  "../../custom_components/comelit/frontend/miniapp/webcodecs.js",
);

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: chromium.executablePath(),
    args: ["--disable-crash-reporter"],
  });
  const logs = [];
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 780 } });
    page.on("console", (message) => {
      if (message.type() === "log") {
        logs.push(message.text());
      }
    });
    await page.setContent("<comelit-card id=\"card\"></comelit-card>");
    await page.evaluate(() => {
      window.__webcodecs = {
        sockets: [],
        chunks: [],
        supportChecks: [],
        drawCount: 0,
        closedFrames: 0,
      };

      CanvasRenderingContext2D.prototype.drawImage = function () {
        window.__webcodecs.drawCount += 1;
      };

      window.VideoDecoder = class {
        static async isConfigSupported(config) {
          window.__webcodecs.supportChecks.push(config);
          return { supported: true, config };
        }
        constructor(init) {
          this.init = init;
          this.decodeQueueSize = 0;
          this.state = "unconfigured";
        }
        configure(config) {
          this.config = config;
          this.state = "configured";
        }
        decode(chunk) {
          window.__webcodecs.chunks.push({
            type: chunk.type,
            timestamp: chunk.timestamp,
            byteLength: chunk.data.byteLength,
          });
          this.decodeQueueSize += 1;
          setTimeout(() => {
            this.decodeQueueSize -= 1;
            this.init.output({
              codedWidth: 640,
              codedHeight: 258,
              visibleRect: { width: 640, height: 258 },
              displayWidth: 640,
              displayHeight: 360,
              close() {
                window.__webcodecs.closedFrames += 1;
              },
            });
          }, 0);
        }
        async flush() {}
        close() {
          this.state = "closed";
        }
      };

      window.EncodedVideoChunk = class {
        constructor(init) {
          this.type = init.type;
          this.timestamp = init.timestamp;
          this.data = init.data;
        }
      };

      window.WebSocket = class {
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        constructor(url) {
          this.url = url;
          this.readyState = 0;
          this.sent = [];
          window.__webcodecs.sockets.push(this);
          setTimeout(() => {
            this.readyState = WebSocket.OPEN;
            this.onopen?.();
          }, 0);
        }
        send(data) {
          this.sent.push(data);
        }
        close() {
          this.readyState = WebSocket.CLOSED;
          this.onclose?.();
        }
        emitText(payload) {
          this.onmessage?.({ data: JSON.stringify(payload) });
        }
        emitBinary(buffer) {
          this.onmessage?.({ data: buffer });
        }
      };

      window.__frame = () => {
        const payload = new Uint8Array([0, 0, 0, 1, 0x65, 0x88]);
        const buffer = new ArrayBuffer(36 + payload.length);
        const view = new DataView(buffer);
        view.setUint8(0, 2);
        view.setUint8(1, 1 | 4);
        view.setUint16(2, 0, false);
        view.setUint32(4, 1, false);
        view.setUint32(8, 0, false);
        view.setUint32(12, 33333, false);
        view.setUint32(16, 0, false);
        view.setUint32(20, 0, false);
        view.setUint32(24, 0, false);
        view.setUint32(28, 0, false);
        view.setUint32(32, payload.length, false);
        new Uint8Array(buffer, 36).set(payload);
        return buffer;
      };
    });
    await page.addScriptTag({ path: viewerPath });
    await page.addScriptTag({ path: cardPath });

    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.setConfig({
        default_tab: "intercom",
        webcodecs: { enabled: true },
        surveillance: { include: ["camera.parking_6048", "camera.dvor_1"] },
      });
      card.hass = {
        states: {
          "camera.parking_6048": {
            state: "idle",
            attributes: { friendly_name: "Паркинг 6048" },
          },
          "camera.dvor_1": {
            state: "idle",
            attributes: { friendly_name: "Двор" },
          },
          "camera.comelit_entrance": {
            state: "idle",
            attributes: { friendly_name: "Comelit — Камера подъезда" },
          },
        },
        callWS: async (message) => {
          if (message?.type === "config/entity_registry/list") {
            return [
              {
                entity_id: "camera.comelit_entrance",
                platform: "comelit",
                unique_id: "comelit_entrance_camera",
                labels: [],
                name: null,
                original_name: "Comelit — Камера подъезда",
              },
            ];
          }
          return [];
        },
        callService: async () => {},
      };
    });

    await page.waitForFunction(() => document.getElementById("card")._registryLoaded === true);
    const tabCount = await page.evaluate(() => {
      const card = document.getElementById("card");
      return card.shadowRoot.querySelectorAll("[data-tab]").length;
    });
    assert.equal(tabCount, 3);
    assert.equal(await page.evaluate(() => window.__webcodecs.sockets.length), 0);

    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.shadowRoot.querySelector('[data-tab="webcodecs"]').click();
    });
    assert.equal(await page.evaluate(() => window.__webcodecs.sockets.length), 0);
    const entranceOption = await page.evaluate(() => {
      const card = document.getElementById("card");
      const viewer = card.shadowRoot.querySelector("miniapp-webcodecs-viewer");
      return [...viewer.shadowRoot.querySelectorAll("[data-camera] option")]
        .some((option) => option.value === "camera.comelit_entrance");
    });
    assert.equal(entranceOption, true);

    const refreshRegression = await page.evaluate(() => {
      const card = document.getElementById("card");
      const viewer = card.shadowRoot.querySelector("miniapp-webcodecs-viewer");
      const root = viewer.shadowRoot;
      const select = root.querySelector("[data-camera]");
      const result = root.querySelector("[data-result]");
      const canvas = root.querySelector("[data-canvas]");
      window.__webcodecs.uiCanvas = canvas;
      window.__webcodecs.uiResult = result;
      select.value = "camera.dvor_1";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      result.textContent = Array.from({ length: 80 }, (_, index) => `line-${index}`).join("\n");
      result.scrollTop = 120;
      const beforeScroll = result.scrollTop;
      const baseHass = card._hass;
      for (let index = 0; index < 10; index += 1) {
        card.hass = {
          ...baseHass,
          states: { ...baseHass.states },
        };
      }
      const sameSelect = root.querySelector("[data-camera]") === select;
      const sameResult = root.querySelector("[data-result]") === result;
      const sameCanvas = root.querySelector("[data-canvas]") === canvas;
      const selected = root.querySelector("[data-camera]").value;
      const afterScroll = root.querySelector("[data-result]").scrollTop;
      select.value = "camera.parking_6048";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return { sameSelect, sameResult, sameCanvas, selected, beforeScroll, afterScroll };
    });
    assert.equal(refreshRegression.sameSelect, true);
    assert.equal(refreshRegression.sameResult, true);
    assert.equal(refreshRegression.sameCanvas, true);
    assert.equal(refreshRegression.selected, "camera.dvor_1");
    assert.equal(refreshRegression.afterScroll, refreshRegression.beforeScroll);

    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.shadowRoot.querySelector("miniapp-webcodecs-viewer")
        .shadowRoot.querySelector("[data-start]").click();
    });
    await page.waitForFunction(() => window.__webcodecs.sockets.length === 1);
    await page.waitForFunction(() => window.__webcodecs.sockets[0].sent.length === 1);
    const sent = await page.evaluate(() => window.__webcodecs.sockets[0].sent[0]);
    assert.equal(sent, JSON.stringify({ type: "webcodecs", value: "h264" }));

    await page.evaluate(() => {
      const socket = window.__webcodecs.sockets[0];
      socket.emitText({ type: "source_open", server_elapsed_ms: 120 });
      socket.emitText({ type: "source_packet", server_elapsed_ms: 145 });
      socket.emitText({
        type: "hello",
        protocol: 2,
        entity_id: "camera.parking_6048",
        codec: "avc1.640029",
        max_unit_bytes: 1048576,
        session_max_seconds: 120,
        zero_transcode: true,
        source_kind: "ordinary_rtsp",
        comelit_entrance_open: false,
        comelit_media_started: false,
      });
      socket.emitBinary(window.__frame());
    });
    await page.waitForFunction(() => window.__webcodecs.drawCount === 1);
    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.shadowRoot.querySelector("miniapp-webcodecs-viewer")
        .shadowRoot.querySelector("[data-stop]").click();
    });
    await page.waitForFunction(() => window.__webcodecs.closedFrames === 1);
    await page.waitForFunction(() => {
      const card = document.getElementById("card");
      return card.shadowRoot.querySelector("miniapp-webcodecs-viewer")
        .shadowRoot.querySelector("[data-result]").textContent.includes("RESULT=PASS");
    });

    const postRunRefresh = await page.evaluate(() => {
      const card = document.getElementById("card");
      const root = card.shadowRoot.querySelector("miniapp-webcodecs-viewer").shadowRoot;
      const result = root.querySelector("[data-result]");
      result.scrollTop = 60;
      const beforeScroll = result.scrollTop;
      const baseHass = card._hass;
      for (let index = 0; index < 10; index += 1) {
        card.hass = {
          ...baseHass,
          states: { ...baseHass.states },
        };
      }
      return {
        sameCanvas: root.querySelector("[data-canvas]") === window.__webcodecs.uiCanvas,
        sameResult: root.querySelector("[data-result]") === window.__webcodecs.uiResult,
        beforeScroll,
        afterScroll: root.querySelector("[data-result]").scrollTop,
      };
    });
    assert.equal(postRunRefresh.sameCanvas, true);
    assert.equal(postRunRefresh.sameResult, true);
    assert.equal(postRunRefresh.afterScroll, postRunRefresh.beforeScroll);

    const state = await page.evaluate(() => ({
      supportChecks: window.__webcodecs.supportChecks,
      chunks: window.__webcodecs.chunks,
      drawCount: window.__webcodecs.drawCount,
      result: document.getElementById("card").shadowRoot
        .querySelector("miniapp-webcodecs-viewer").shadowRoot
        .querySelector("[data-result]").textContent,
    }));
    assert.deepEqual(state.supportChecks[0], {
      codec: "avc1.640029",
      optimizeForLatency: true,
    });
    assert.deepEqual(state.chunks[0], {
      type: "key",
      timestamp: 33333,
      byteLength: 6,
    });
    assert.equal(state.drawCount, 1);
    for (const key of [
      "=== COMELIT MINIAPP WEBCODECS LIVE CANARY ===",
      "RESULT=PASS",
      "FUNCTIONAL_PASS=true",
      "TRANSPORT_BACKLOG_OBSERVED=unknown",
      "ENTITY_ID=camera.parking_6048",
      "ZERO_TRANSCODE=true",
      "SOURCE_KIND=ordinary_rtsp",
      "SOURCE_OPEN_MS=",
      "FIRST_SOURCE_PACKET_MS=",
      "SOURCE_STARTUP_MS=",
      "SOURCE_PACKET_TO_BINARY_MS=",
      "BINARY_TO_DECODE_MS=",
      "SOURCE_PTS_DRIFT_MS=",
      "SERVER_QUEUE_DRIFT_MS=",
      "TRANSPORT_DRIFT_MS=",
      "DECODE_P50_MS=",
      "FIRST_DECODED_FRAME_MS=",
      "RECEIVE_TO_DRAW_P50_MS=",
      "COMELIT_MEDIA_STARTED=false",
      "DOOR_ACTIONS=0",
      "GATE_ACTIONS=0",
    ]) {
      assert.ok(state.result.includes(key), key + "\n" + state.result);
    }
    assert.ok(logs.includes(state.result));

    await page.evaluate(() => {
      const card = document.getElementById("card");
      const root = card.shadowRoot.querySelector("miniapp-webcodecs-viewer").shadowRoot;
      const select = root.querySelector("[data-camera]");
      select.value = "camera.comelit_entrance";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      root.querySelector("[data-start]").click();
    });
    await page.waitForFunction(() => window.__webcodecs.sockets.length === 2);
    await page.waitForFunction(() => window.__webcodecs.sockets[1].sent.length === 1);
    await page.evaluate(() => {
      const socket = window.__webcodecs.sockets[1];
      socket.emitText({ type: "intercom_media_ready", server_elapsed_ms: 4100 });
      socket.emitText({ type: "source_open", server_elapsed_ms: 4140 });
      socket.emitText({ type: "source_packet", server_elapsed_ms: 4160 });
      socket.emitText({
        type: "hello",
        protocol: 2,
        entity_id: "camera.comelit_entrance",
        codec: "avc1.42C01E",
        max_unit_bytes: 1048576,
        session_max_seconds: 120,
        zero_transcode: true,
        source_kind: "comelit_entrance_rtp",
        comelit_entrance_open: true,
        comelit_media_started: true,
      });
      socket.emitBinary(window.__frame());
    });
    await page.waitForFunction(() => window.__webcodecs.drawCount === 2);
    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.shadowRoot.querySelector("miniapp-webcodecs-viewer")
        .shadowRoot.querySelector("[data-stop]").click();
    });
    await page.waitForFunction(() => {
      const card = document.getElementById("card");
      const result = card.shadowRoot.querySelector("miniapp-webcodecs-viewer")
        .shadowRoot.querySelector("[data-result]").textContent;
      return result.includes("ENTITY_ID=camera.comelit_entrance") &&
        result.includes("COMELIT_ENTRANCE_OPEN=true") &&
        result.includes("COMELIT_MEDIA_STARTED=true");
    });
    const entranceResult = await page.evaluate(() => {
      const card = document.getElementById("card");
      return card.shadowRoot.querySelector("miniapp-webcodecs-viewer")
        .shadowRoot.querySelector("[data-result]").textContent;
    });
    for (const key of [
      "SOURCE_KIND=comelit_entrance_rtp",
      "INTERCOM_MEDIA_READY_MS=",
      "INTERCOM_MEDIA_READY_SERVER_MS=4100.0",
      "INTERCOM_MEDIA_TO_SOURCE_OPEN_MS=",
      "COMELIT_ENTRANCE_OPEN=true",
      "COMELIT_MEDIA_STARTED=true",
      "DOOR_ACTIONS=0",
      "GATE_ACTIONS=0",
    ]) {
      assert.ok(entranceResult.includes(key), key + "\n" + entranceResult);
    }

    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.setConfig({
        default_tab: "intercom",
        surveillance: { include: ["camera.parking_6048"] },
      });
    });
    const defaultTabs = await page.evaluate(() => {
      const card = document.getElementById("card");
      return {
        tabs: [...card.shadowRoot.querySelectorAll("[data-tab]")]
          .map((button) => button.textContent.trim()),
        hasPanel: Boolean(card.shadowRoot.querySelector("miniapp-webcodecs-viewer")),
      };
    });
    assert.deepEqual(defaultTabs, {
      tabs: ["Домофон", "Видеонаблюдение"],
      hasPanel: false,
    });

    // Production Entrance path: WebCodecs is primary without exposing the
    // diagnostic tab. A terminal WebCodecs failure falls back to the legacy
    // HLS-backed picture viewer automatically, with no extra user click.
    await page.evaluate(() => {
      window.__webcodecs.legacyMounts = 0;
      window.loadCardHelpers = async () => ({
        createCardElement: async (config) => {
          window.__webcodecs.legacyMounts += 1;
          const node = document.createElement("div");
          node.dataset.legacyViewer = config.entity;
          return node;
        },
      });

      const card = document.getElementById("card");
      card.setConfig({
        default_tab: "intercom",
        webcodecs: { enabled: false, intercom_primary: true },
        surveillance: { include: ["camera.parking_6048"] },
      });
      card.shadowRoot.querySelector("[data-intercom-camera-toggle]").click();
    });

    await page.waitForFunction(() => window.__webcodecs.sockets.length === 3);
    await page.waitForFunction(() => window.__webcodecs.sockets[2].sent.length === 1);
    const productionSurface = await page.evaluate(() => {
      const card = document.getElementById("card");
      const viewer = card.shadowRoot.querySelector("#intercom-viewer miniapp-webcodecs-viewer");
      return {
        tabs: [...card.shadowRoot.querySelectorAll("[data-tab]")]
          .map((button) => button.textContent.trim()),
        embedded: Boolean(viewer),
        hasStart: Boolean(viewer?.shadowRoot.querySelector("[data-start]")),
        hasResult: Boolean(viewer?.shadowRoot.querySelector("[data-result]")),
      };
    });
    assert.deepEqual(productionSurface, {
      tabs: ["Домофон", "Видеонаблюдение"],
      embedded: true,
      hasStart: false,
      hasResult: false,
    });

    await page.evaluate(() => {
      const socket = window.__webcodecs.sockets[2];
      socket.emitText({ type: "intercom_media_ready", server_elapsed_ms: 3900 });
      socket.emitText({ type: "source_open", server_elapsed_ms: 3950 });
      socket.emitText({ type: "source_packet", server_elapsed_ms: 3970 });
      socket.emitText({
        type: "hello",
        protocol: 2,
        entity_id: "camera.comelit_entrance",
        codec: "avc1.42C01E",
        max_unit_bytes: 1048576,
        session_max_seconds: 600,
        zero_transcode: true,
        source_kind: "comelit_entrance_rtp",
        comelit_entrance_open: true,
        comelit_media_started: true,
      });
      socket.emitBinary(window.__frame());
    });
    await page.waitForFunction(() => window.__webcodecs.drawCount === 3);

    const preservedViewer = await page.evaluate(() => {
      const card = document.getElementById("card");
      const before = card.shadowRoot.querySelector(
        "#intercom-viewer miniapp-webcodecs-viewer",
      );
      window.__webcodecs.productionViewer = before;
      card._render();
      const after = card.shadowRoot.querySelector(
        "#intercom-viewer miniapp-webcodecs-viewer",
      );
      return {
        sameNode: before === after,
        connected: Boolean(after?.isConnected),
        sockets: window.__webcodecs.sockets.length,
      };
    });
    assert.deepEqual(preservedViewer, {
      sameNode: true,
      connected: true,
      sockets: 3,
    });

    await page.evaluate(() => {
      window.__webcodecs.sockets[2].emitText({
        type: "error",
        code: "source_open_failed",
      });
    });
    await page.waitForFunction(() => window.__webcodecs.legacyMounts === 1);
    const automaticFallback = await page.evaluate(() => {
      const card = document.getElementById("card");
      return {
        legacy: card.shadowRoot
          .querySelector("#intercom-viewer [data-legacy-viewer]")
          ?.dataset.legacyViewer,
        manualFallbackButton: Boolean(
          card.shadowRoot.querySelector("[data-intercom-legacy-fallback]"),
        ),
      };
    });
    assert.deepEqual(automaticFallback, {
      legacy: "camera.comelit_entrance",
      manualFallbackButton: false,
    });

    // Explicit reopen resets the primary mode. If WebCodecs is unavailable in
    // the WebView, fallback is automatic before opening any WebCodecs socket.
    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.shadowRoot.querySelector("[data-intercom-camera-toggle]").click();
      window.__webcodecs.savedVideoDecoder = window.VideoDecoder;
      delete window.VideoDecoder;
      card.shadowRoot.querySelector("[data-intercom-camera-toggle]").click();
    });
    await page.waitForFunction(() => window.__webcodecs.legacyMounts === 2);
    assert.equal(await page.evaluate(() => window.__webcodecs.sockets.length), 3);
    await page.evaluate(() => {
      window.VideoDecoder = window.__webcodecs.savedVideoDecoder;
      const card = document.getElementById("card");
      // Isolate the ordinary-camera scenario. The card intentionally keeps an
      // explicitly opened Entrance viewer alive while changing tabs, so close
      // the Entrance viewer before asserting ordinary-camera socket ownership.
      card.shadowRoot.querySelector("[data-intercom-camera-toggle]").click();
    });

    // Production ordinary surveillance path: the normal two-tab surface uses
    // the already live-validated WebCodecs transport first. Terminal failures
    // fall back to the existing picture-entity MSE -> WebRTC -> HLS chain.
    const surveillanceSocketBase = await page.evaluate(() => {
      window.__webcodecs.legacyMounts = 0;
      window.__webcodecs.surveillanceSocketBase =
        window.__webcodecs.sockets.length;
      const card = document.getElementById("card");
      card.setConfig({
        default_tab: "surveillance",
        webcodecs: {
          enabled: false,
          intercom_primary: true,
          surveillance_primary: true,
        },
        surveillance: { include: ["camera.parking_6048", "camera.dvor_1"] },
      });
      return window.__webcodecs.surveillanceSocketBase;
    });
    assert.equal(surveillanceSocketBase, 3);

    const surveillanceMount = await page.evaluate(() => {
      const card = document.getElementById("card");
      const viewer = card.shadowRoot.querySelector(
        "#viewer miniapp-webcodecs-viewer",
      );
      return {
        primary: card._webcodecsSurveillancePrimary(),
        selected: card._selectedCamera,
        viewer: Boolean(viewer),
        connected: Boolean(viewer?.isConnected),
        embedded: viewer?._embedded === true,
        autoStart: viewer?._autoStart === true,
        autoStartConsumed: viewer?._autoStartConsumed === true,
      };
    });
    assert.deepEqual(surveillanceMount, {
      primary: true,
      selected: "camera.dvor_1",
      viewer: true,
      connected: true,
      embedded: true,
      autoStart: true,
      autoStartConsumed: true,
    });

    await page.waitForFunction(
      (base) => window.__webcodecs.sockets.length > base,
      surveillanceSocketBase,
    );
    const surveillanceSocketUrls = await page.evaluate(
      (base) => window.__webcodecs.sockets.slice(base).map((socket) => socket.url),
      surveillanceSocketBase,
    );
    assert.equal(
      surveillanceSocketUrls.length,
      1,
      "ordinary surveillance must create exactly one WebCodecs socket: " +
        JSON.stringify(surveillanceSocketUrls),
    );
    await page.waitForFunction(
      (index) => window.__webcodecs.sockets[index].sent.length === 1,
      surveillanceSocketBase,
    );
    const surveillanceSurface = await page.evaluate(() => {
      const card = document.getElementById("card");
      const viewer = card.shadowRoot.querySelector("#viewer miniapp-webcodecs-viewer");
      return {
        tabs: [...card.shadowRoot.querySelectorAll("[data-tab]")]
          .map((button) => button.textContent.trim()),
        selected: card._selectedCamera,
        embedded: Boolean(viewer),
        hasStart: Boolean(viewer?.shadowRoot.querySelector("[data-start]")),
        hasResult: Boolean(viewer?.shadowRoot.querySelector("[data-result]")),
      };
    });
    assert.deepEqual(surveillanceSurface, {
      tabs: ["Домофон", "Видеонаблюдение"],
      selected: "camera.dvor_1",
      embedded: true,
      hasStart: false,
      hasResult: false,
    });

    await page.evaluate((index) => {
      const socket = window.__webcodecs.sockets[index];
      socket.emitText({ type: "source_open", server_elapsed_ms: 4700 });
      socket.emitText({ type: "source_packet", server_elapsed_ms: 4720 });
      socket.emitText({
        type: "hello",
        protocol: 2,
        entity_id: "camera.dvor_1",
        codec: "avc1.42C02A",
        max_unit_bytes: 1048576,
        session_max_seconds: 600,
        zero_transcode: true,
        source_kind: "ordinary_rtsp",
        comelit_entrance_open: false,
        comelit_media_started: false,
      });
      socket.emitBinary(window.__frame());
    }, surveillanceSocketBase);
    await page.waitForFunction(() => window.__webcodecs.drawCount === 4);
    assert.equal(
      await page.evaluate(() => window.__webcodecs.legacyMounts),
      0,
      "successful ordinary WebCodecs playback must not mount legacy",
    );

    const preservedSurveillanceViewer = await page.evaluate(() => {
      const card = document.getElementById("card");
      const before = card.shadowRoot.querySelector(
        "#viewer miniapp-webcodecs-viewer",
      );
      card._render();
      const after = card.shadowRoot.querySelector(
        "#viewer miniapp-webcodecs-viewer",
      );
      return {
        sameNode: before === after,
        connected: Boolean(after?.isConnected),
        sockets: window.__webcodecs.sockets.length,
      };
    });
    assert.deepEqual(preservedSurveillanceViewer, {
      sameNode: true,
      connected: true,
      sockets: surveillanceSocketBase + 1,
    });

    await page.evaluate((index) => {
      window.__webcodecs.sockets[index].emitText({
        type: "error",
        code: "source_open_failed",
      });
    }, surveillanceSocketBase);
    await page.waitForFunction(() => window.__webcodecs.legacyMounts === 1);
    const surveillanceFallback = await page.evaluate(() => {
      const card = document.getElementById("card");
      return card.shadowRoot.querySelector("#viewer [data-legacy-viewer]")
        ?.dataset.legacyViewer;
    });
    assert.equal(surveillanceFallback, "camera.dvor_1");

    // Re-entering Surveillance is an explicit user navigation and retries the
    // primary transport once. Ordinary duration_limit then falls back, while
    // Entrance keeps its no-auto-restart ceiling semantics.
    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.shadowRoot.querySelector('[data-tab="intercom"]').click();
      card.shadowRoot.querySelector('[data-tab="surveillance"]').click();
    });
    await page.waitForFunction(
      (base) => window.__webcodecs.sockets.length > base + 1,
      surveillanceSocketBase,
    );
    assert.equal(
      await page.evaluate(() => window.__webcodecs.sockets.length),
      surveillanceSocketBase + 2,
    );
    await page.evaluate((index) => {
      window.__webcodecs.sockets[index].emitText({
        type: "eos",
        reason: "duration_limit",
      });
    }, surveillanceSocketBase + 1);
    await page.waitForFunction(() => window.__webcodecs.legacyMounts === 2);

    // Ordinary WebCodecs capability absence is terminal for the primary path
    // and must fall back without constructing a WSS session.
    const socketsBeforeUnsupported = await page.evaluate(
      () => window.__webcodecs.sockets.length,
    );
    await page.evaluate(() => {
      window.__webcodecs.savedVideoDecoder = window.VideoDecoder;
      delete window.VideoDecoder;
      const card = document.getElementById("card");
      card.shadowRoot.querySelector('[data-tab="intercom"]').click();
      card.shadowRoot.querySelector('[data-tab="surveillance"]').click();
    });
    await page.waitForFunction(() => window.__webcodecs.legacyMounts === 3);
    assert.equal(
      await page.evaluate(() => window.__webcodecs.sockets.length),
      socketsBeforeUnsupported,
      "unsupported WebCodecs must fall back before opening WSS",
    );
    assert.equal(
      await page.evaluate(() => {
        const card = document.getElementById("card");
        return card.shadowRoot.querySelector("#viewer [data-legacy-viewer]")
          ?.dataset.legacyViewer;
      }),
      "camera.dvor_1",
    );

    // Start a fresh primary viewer, switch cameras, then inject a late event
    // from the disconnected old socket. Generation guards must ignore it.
    await page.evaluate(() => {
      window.VideoDecoder = window.__webcodecs.savedVideoDecoder;
      const card = document.getElementById("card");
      card.shadowRoot.querySelector('[data-tab="intercom"]').click();
      card.shadowRoot.querySelector('[data-tab="surveillance"]').click();
    });
    await page.waitForFunction(
      (base) => window.__webcodecs.sockets.length === base + 1,
      socketsBeforeUnsupported,
    );
    const staleDvorSocketIndex = socketsBeforeUnsupported;
    await page.waitForFunction(
      (index) => window.__webcodecs.sockets[index].sent.length === 1,
      staleDvorSocketIndex,
    );

    await page.evaluate(() => {
      const card = document.getElementById("card");
      card.shadowRoot.querySelector(
        '[data-camera="camera.parking_6048"]',
      ).click();
    });
    await page.waitForFunction(
      (base) => window.__webcodecs.sockets.length === base + 2,
      socketsBeforeUnsupported,
    );
    const parkingSocketIndex = socketsBeforeUnsupported + 1;
    const switchedState = await page.evaluate((oldIndex) => {
      const card = document.getElementById("card");
      return {
        selected: card._selectedCamera,
        oldSocketClosed:
          window.__webcodecs.sockets[oldIndex].readyState === WebSocket.CLOSED,
        webcodecsMounted: Boolean(
          card.shadowRoot.querySelector("#viewer miniapp-webcodecs-viewer"),
        ),
      };
    }, staleDvorSocketIndex);
    assert.deepEqual(switchedState, {
      selected: "camera.parking_6048",
      oldSocketClosed: true,
      webcodecsMounted: true,
    });

    await page.evaluate((oldIndex) => {
      window.__webcodecs.sockets[oldIndex].emitText({
        type: "error",
        code: "source_open_failed",
      });
    }, staleDvorSocketIndex);
    await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
    assert.equal(
      await page.evaluate(() => window.__webcodecs.legacyMounts),
      3,
      "stale callback after camera switch must not start legacy fallback",
    );

    // Leaving Surveillance disconnects the active ordinary viewer. A late
    // callback from that closed socket must likewise be ignored.
    await page.evaluate(() => {
      document.getElementById("card").shadowRoot
        .querySelector('[data-tab="intercom"]').click();
    });
    assert.equal(
      await page.evaluate((index) =>
        window.__webcodecs.sockets[index].readyState === WebSocket.CLOSED
      , parkingSocketIndex),
      true,
      "leaving Surveillance must close the active WebCodecs socket",
    );
    await page.evaluate((index) => {
      window.__webcodecs.sockets[index].emitText({
        type: "error",
        code: "source_open_failed",
      });
    }, parkingSocketIndex);
    await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
    assert.deepEqual(
      await page.evaluate(() => {
        const card = document.getElementById("card");
        return {
          legacyMounts: window.__webcodecs.legacyMounts,
          viewerReleased: card._viewerElement === undefined,
        };
      }),
      {
        legacyMounts: 3,
        viewerReleased: true,
      },
    );

    console.log("webcodecs mock canary: PASS");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
