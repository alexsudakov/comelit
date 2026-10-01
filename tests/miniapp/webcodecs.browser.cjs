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
        const buffer = new ArrayBuffer(20 + payload.length);
        const view = new DataView(buffer);
        view.setUint8(0, 1);
        view.setUint8(1, 1 | 4);
        view.setUint16(2, 0, false);
        view.setUint32(4, 1, false);
        view.setUint32(8, 0, false);
        view.setUint32(12, 33333, false);
        view.setUint32(16, payload.length, false);
        new Uint8Array(buffer, 20).set(payload);
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
        surveillance: { include: ["camera.parking_6048"] },
      });
      card.hass = {
        states: {
          "camera.parking_6048": {
            state: "idle",
            attributes: { friendly_name: "Паркинг 6048" },
          },
        },
        callWS: async () => [],
        callService: async () => {},
      };
    });

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
      socket.emitText({
        type: "hello",
        protocol: 1,
        entity_id: "camera.parking_6048",
        codec: "avc1.640029",
        max_unit_bytes: 1048576,
        session_max_seconds: 120,
        zero_transcode: true,
      });
      socket.emitText({ type: "source" });
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
      "ENTITY_ID=camera.parking_6048",
      "ZERO_TRANSCODE=true",
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

    console.log("webcodecs mock canary: PASS");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
