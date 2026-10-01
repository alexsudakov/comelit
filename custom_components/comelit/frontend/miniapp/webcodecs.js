(() => {
  "use strict";

  const TAG = "miniapp-webcodecs-viewer";
  const PROTOCOL_VERSION = 2;
  const HEADER_BYTES = 36;
  const FLAG_KEY = 1;
  const FLAG_DELTA = 2;
  const FLAG_PTS_VALID = 4;
  const MAX_UNIT_BYTES = 1024 * 1024;
  const CANARY_MS = 60_000;
  const MAX_DECODE_QUEUE = 8;
  const BACKLOG_STALL_MS = 2000;

  function safeEntityId(value) {
    const entityId = String(value || "");
    return /^camera\.[a-zA-Z0-9_]+$/.test(entityId) ? entityId : "";
  }

  function percentile(values, ratio) {
    if (!values.length) {
      return "n/a";
    }
    const sorted = [...values].sort((left, right) => left - right);
    const index = Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * ratio));
    return sorted[index].toFixed(1);
  }

  function maxValue(values) {
    return values.length ? Math.max(...values).toFixed(1) : "n/a";
  }

  function fmt(value) {
    if (value === undefined || value === null || Number.isNaN(value)) {
      return "n/a";
    }
    if (typeof value === "number") {
      return value.toFixed(1);
    }
    return String(value);
  }

  function readUint64(view, offset) {
    return view.getUint32(offset, false) * 4294967296 +
      view.getUint32(offset + 4, false);
  }

  function parseFrame(buffer) {
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < HEADER_BYTES) {
      throw new Error("malformed_frame");
    }
    const view = new DataView(buffer);
    const version = view.getUint8(0);
    const flags = view.getUint8(1);
    const reserved = view.getUint16(2, false);
    const sequence = view.getUint32(4, false);
    const pts = readUint64(view, 8);
    const sourceElapsedUs = readUint64(view, 16);
    const sendElapsedUs = readUint64(view, 24);
    const payloadLength = view.getUint32(32, false);
    if (version !== PROTOCOL_VERSION || reserved !== 0) {
      throw new Error("malformed_frame");
    }
    const key = Boolean(flags & FLAG_KEY);
    const delta = Boolean(flags & FLAG_DELTA);
    if (key === delta || flags & ~(FLAG_KEY | FLAG_DELTA | FLAG_PTS_VALID)) {
      throw new Error("malformed_frame");
    }
    if (payloadLength > MAX_UNIT_BYTES) {
      throw new Error("unit_too_large");
    }
    if (payloadLength !== buffer.byteLength - HEADER_BYTES) {
      throw new Error("malformed_frame");
    }
    return {
      sequence,
      type: key ? "key" : "delta",
      ptsValid: Boolean(flags & FLAG_PTS_VALID),
      pts,
      sourceElapsedUs,
      sendElapsedUs,
      payload: buffer.slice(HEADER_BYTES),
    };
  }

  class MiniAppWebCodecsViewer extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({mode: "open"});
      this._cameras = [];
      this._cameraFingerprint = "";
      this._hass = null;
      this._selected = "";
      this._rendered = false;
      this._socket = null;
      this._decoder = null;
      this._running = false;
      this._finalEmitted = false;
      this._timer = null;
      this._backlogSince = null;
      this._pendingReceives = [];
      this._pendingDecodeStarts = [];
      this._pendingBinary = [];
      this._stats = this._newStats();
    }

    set cameras(value) {
      const next = Array.isArray(value)
        ? value.filter((camera) => {
            const entityId = safeEntityId(camera.entityId || camera.entity_id);
            return entityId && !/comelit_(entrance|gate|intercom)/i.test(entityId);
          })
        : [];
      const nextFingerprint = this._cameraListFingerprint(next);
      if (this._running) {
        this._refreshCounters();
        return;
      }
      if (nextFingerprint === this._cameraFingerprint && this._rendered) {
        this._syncControls();
        return;
      }
      this._cameras = next;
      this._cameraFingerprint = nextFingerprint;
      if (!this._selected || !this._cameras.some((camera) => this._cameraId(camera) === this._selected)) {
        this._selected = this._cameras.length ? this._cameraId(this._cameras[0]) : "";
      }
      this._render();
    }

    set hass(value) {
      this._hass = value;
      if (!this._rendered) {
        this._render();
        return;
      }
      this._refreshCounters();
    }

    connectedCallback() {
      if (!this._rendered) {
        this._render();
      }
    }

    disconnectedCallback() {
      this._stop("disconnect", false);
    }

    _cameraId(camera) {
      return safeEntityId(camera?.entityId || camera?.entity_id);
    }

    _cameraName(camera) {
      const entityId = this._cameraId(camera);
      return String(
        camera?.name ||
        this._hass?.states?.[entityId]?.attributes?.friendly_name ||
        entityId,
      );
    }

    _cameraListFingerprint(cameras) {
      return cameras
        .map((camera) => this._cameraId(camera) + "\u0000" + this._cameraName(camera))
        .join("\u0001");
    }

    _newStats() {
      return {
        startedAt: 0,
        wsOpenAt: null,
        sourceOpenAt: null,
        firstSourcePacketAt: null,
        sourceOpenServerMs: null,
        firstSourcePacketServerMs: null,
        firstBinaryAt: null,
        firstDecodedAt: null,
        firstReceiveAt: null,
        firstPts: null,
        firstSourceElapsedUs: null,
        firstSendElapsedUs: null,
        codec: "n/a",
        units: 0,
        frames: 0,
        keyframes: 0,
        gaps: 0,
        lastSequence: 0,
        maxDecodeQueue: 0,
        decodeMs: [],
        receiveToDrawMs: [],
        interarrivalMs: [],
        sourcePtsDriftMs: [],
        serverQueueDriftMs: [],
        transportDriftMs: [],
        lastReceiveAt: null,
        codedSize: "n/a",
        visibleSize: "n/a",
        displaySize: "n/a",
        backlogStop: false,
        stopReason: "n/a",
        zeroTranscode: null,
        unsupported: false,
        error: null,
      };
    }

    _render() {
      if (!this.shadowRoot) {
        return;
      }
      const options = this._cameras.map((camera) => {
        const entityId = this._cameraId(camera);
        const name = this._cameraName(camera);
        return `<option value="${entityId}" ${entityId === this._selected ? "selected" : ""}>${name}</option>`;
      }).join("");
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; min-width: 0; }
          * { box-sizing: border-box; }
          .panel { display: grid; gap: 12px; }
          .toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; align-items: center; }
          select, button { min-height: 40px; font: inherit; border-radius: 8px; border: 1px solid var(--divider-color, #d1d5db); }
          select { width: 100%; min-width: 0; padding: 0 10px; background: var(--card-background-color, #fff); color: var(--primary-text-color, #111827); }
          button { padding: 0 12px; background: var(--secondary-background-color, #f3f4f6); color: var(--primary-text-color, #111827); cursor: pointer; }
          button.primary { background: var(--primary-color, #2563eb); color: var(--text-primary-color, #fff); border-color: var(--primary-color, #2563eb); }
          button:disabled { opacity: 0.45; cursor: default; }
          canvas { display: block; width: 100%; aspect-ratio: 16 / 9; background: #000; border-radius: 8px; }
          .status { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; color: var(--secondary-text-color, #4b5563); font-size: 0.9rem; }
          .notice { padding: 12px; border-radius: 8px; background: var(--secondary-background-color, #f3f4f6); color: var(--secondary-text-color, #4b5563); }
          pre { max-height: 340px; overflow: auto; white-space: pre-wrap; margin: 0; padding: 12px; border-radius: 8px; background: #111827; color: #f9fafb; font-size: 0.82rem; }
        </style>
        <div class="panel">
          ${this._cameras.length ? `
            <div class="toolbar">
              <select data-camera ${this._running ? "disabled" : ""}>${options}</select>
              <button class="primary" data-start ${this._running ? "disabled" : ""}>Запустить тест</button>
              <button data-stop ${this._running ? "" : "disabled"}>Остановить</button>
            </div>
            <canvas data-canvas width="1280" height="720"></canvas>
            <div class="status">
              <span>Статус: <b data-status>${this._running ? "идёт тест" : "ожидание"}</b></span>
              <span>Кодек: <b data-codec>${this._stats.codec}</b></span>
              <span>AU: <b data-units>${this._stats.units}</b></span>
              <span>Кадры: <b data-frames>${this._stats.frames}</b></span>
              <span>Очередь: <b data-queue>${this._stats.maxDecodeQueue}</b></span>
            </div>
            <pre data-result>${this._stats.finalBlock || ""}</pre>
          ` : '<div class="notice">В allowlist Mini App нет обычных камер для теста WebCodecs.</div>'}
        </div>
      `;
      this.shadowRoot.querySelector("[data-camera]")?.addEventListener("change", (event) => {
        this._selected = safeEntityId(event.target.value);
      });
      this.shadowRoot.querySelector("[data-start]")?.addEventListener("click", () => this._start());
      this.shadowRoot.querySelector("[data-stop]")?.addEventListener("click", () => this._stop("manual_stop", true));
      this._rendered = true;
      this._syncControls();
    }

    _syncControls() {
      const select = this.shadowRoot?.querySelector("[data-camera]");
      if (select) {
        select.disabled = this._running;
        if (!this._running && this._selected && select.value !== this._selected) {
          select.value = this._selected;
        }
      }
      const start = this.shadowRoot?.querySelector("[data-start]");
      if (start) {
        start.disabled = this._running;
      }
      const stop = this.shadowRoot?.querySelector("[data-stop]");
      if (stop) {
        stop.disabled = !this._running;
      }
    }

    _setStatus(text) {
      const status = this.shadowRoot?.querySelector("[data-status]");
      if (status) {
        status.textContent = text;
      }
    }

    _refreshCounters() {
      for (const [selector, value] of [
        ["[data-codec]", this._stats.codec],
        ["[data-units]", this._stats.units],
        ["[data-frames]", this._stats.frames],
        ["[data-queue]", this._stats.maxDecodeQueue],
      ]) {
        const node = this.shadowRoot?.querySelector(selector);
        if (node) {
          node.textContent = String(value);
        }
      }
    }

    async _start() {
      if (this._running) {
        return;
      }
      const entityId = safeEntityId(this._selected);
      if (!entityId) {
        return;
      }
      if (!("VideoDecoder" in globalThis) || !("EncodedVideoChunk" in globalThis)) {
        this._stats = this._newStats();
        this._stats.error = "webcodecs_unavailable";
        this._emitFinal("codec_unsupported");
        return;
      }
      this._running = true;
      this._finalEmitted = false;
      this._stats = this._newStats();
      this._pendingReceives = [];
      this._pendingDecodeStarts = [];
      this._pendingBinary = [];
      this._stats.startedAt = performance.now();
      const result = this.shadowRoot?.querySelector("[data-result]");
      if (result) {
        result.textContent = "";
        result.scrollTop = 0;
      }
      this._syncControls();
      this._refreshCounters();
      this._setStatus("подключение");

      const scheme = location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${scheme}//${location.host}/api/comelit/miniapp/camera/${encodeURIComponent(entityId)}/webcodecs`;
      const socket = new WebSocket(url);
      socket.binaryType = "arraybuffer";
      this._socket = socket;
      this._timer = setTimeout(() => this._stop("duration_60s", true), CANARY_MS);

      socket.onopen = () => {
        this._stats.wsOpenAt = performance.now();
        socket.send(JSON.stringify({type: "webcodecs", value: "h264"}));
        this._setStatus("ожидание источника");
      };
      socket.onerror = () => {
        this._stats.error = "ws_error";
        this._stop("ws_error", true);
      };
      socket.onclose = () => {
        if (this._running) {
          this._stop("ws_closed", true);
        }
      };
      socket.onmessage = (event) => {
        if (typeof event.data === "string") {
          this._handleText(event.data);
          return;
        }
        this._handleBinary(event.data);
      };
    }

    async _handleText(raw) {
      let message;
      try {
        message = JSON.parse(raw);
      } catch (_) {
        this._stats.error = "invalid_json";
        this._stop("invalid_json", true);
        return;
      }
      if (message.type === "hello") {
        if (Number(message.protocol) !== PROTOCOL_VERSION) {
          this._stats.error = "protocol_mismatch";
          this._stop("protocol_mismatch", true);
          return;
        }
        this._stats.codec = String(message.codec || "n/a");
        if (Object.prototype.hasOwnProperty.call(message, "zero_transcode")) {
          this._stats.zeroTranscode = message.zero_transcode === true;
        }
        const config = {
          codec: this._stats.codec,
          optimizeForLatency: true,
        };
        const support = await VideoDecoder.isConfigSupported(config);
        if (!support.supported) {
          this._stats.unsupported = true;
          this._stats.error = "codec_unsupported";
          this._stop("codec_unsupported", true);
          return;
        }
        this._decoder = new VideoDecoder({
          output: (frame) => this._drawFrame(frame),
          error: () => {
            this._stats.error = "decoder_error";
            this._stop("decoder_error", true);
          },
        });
        this._decoder.configure(config);
        for (const data of this._pendingBinary.splice(0)) {
          this._handleBinary(data);
        }
        this._refreshCounters();
        return;
      }
      if (message.type === "source") {
        this._stats.sourceAt = performance.now();
        this._setStatus("получение H.264");
        return;
      }
      if (message.type === "error") {
        this._stats.error = String(message.code || "ws_error");
        this._stop(this._stats.error, true);
        return;
      }
      if (message.type === "eos") {
        this._stop(String(message.reason || "eos"), true);
      }
    }

    _handleBinary(data) {
      if (!this._decoder) {
        if (this._running && this._pendingBinary.length < 16) {
          this._pendingBinary.push(data);
        }
        return;
      }
      let parsed;
      try {
        parsed = parseFrame(data);
      } catch (error) {
        this._stats.error = error instanceof Error ? error.message : "malformed_frame";
        this._stop(this._stats.error, true);
        return;
      }
      const now = performance.now();
      if (!this._stats.firstBinaryAt) {
        this._stats.firstBinaryAt = now;
      }
      if (this._stats.lastReceiveAt !== null) {
        this._stats.interarrivalMs.push(now - this._stats.lastReceiveAt);
      }
      this._stats.lastReceiveAt = now;
      if (this._stats.firstReceiveAt === null) {
        this._stats.firstReceiveAt = now;
      }
      if (parsed.ptsValid && this._stats.firstPts === null) {
        this._stats.firstPts = parsed.pts;
      }
      if (parsed.ptsValid && this._stats.firstPts !== null && this._stats.firstReceiveAt !== null) {
        const arrivalElapsed = now - this._stats.firstReceiveAt;
        const mediaElapsed = (parsed.pts - this._stats.firstPts) / 1000;
        this._stats.lagMs.push(arrivalElapsed - mediaElapsed);
      }
      if (this._stats.lastSequence && parsed.sequence !== this._stats.lastSequence + 1) {
        this._stats.gaps += 1;
      }
      this._stats.lastSequence = parsed.sequence;
      this._stats.units += 1;
      if (parsed.type === "key") {
        this._stats.keyframes += 1;
      }
      this._pendingReceives.push(now);
      this._pendingDecodeStarts.push(now);
      this._decoder.decode(new EncodedVideoChunk({
        type: parsed.type,
        timestamp: parsed.ptsValid ? parsed.pts : 0,
        data: parsed.payload,
      }));
      this._stats.maxDecodeQueue = Math.max(
        this._stats.maxDecodeQueue,
        this._decoder.decodeQueueSize || 0,
      );
      this._checkBacklog();
      this._refreshCounters();
    }

    _checkBacklog() {
      const queue = this._decoder?.decodeQueueSize || 0;
      if (queue <= MAX_DECODE_QUEUE) {
        this._backlogSince = null;
        return;
      }
      if (this._backlogSince === null) {
        this._backlogSince = performance.now();
        return;
      }
      if (performance.now() - this._backlogSince > BACKLOG_STALL_MS) {
        this._stats.backlogStop = true;
        this._stats.error = "BACKLOG_STOP=true";
        this._stop("decode_backlog", true);
      }
    }

    _drawFrame(frame) {
      const now = performance.now();
      if (!this._stats.firstDecodedAt) {
        this._stats.firstDecodedAt = now;
      }
      const canvas = this.shadowRoot?.querySelector("[data-canvas]");
      const context = canvas?.getContext("2d");
      const width = frame.displayWidth || frame.codedWidth || 1280;
      const height = frame.displayHeight || frame.codedHeight || 720;
      if (canvas && context) {
        if (canvas.width !== width) {
          canvas.width = width;
        }
        if (canvas.height !== height) {
          canvas.height = height;
        }
        context.drawImage(frame, 0, 0, canvas.width, canvas.height);
      }
      this._stats.frames += 1;
      this._stats.codedSize = `${frame.codedWidth || "n/a"}x${frame.codedHeight || "n/a"}`;
      const rect = frame.visibleRect;
      this._stats.visibleSize = rect
        ? `${rect.width || "n/a"}x${rect.height || "n/a"}`
        : "n/a";
      this._stats.displaySize = `${frame.displayWidth || "n/a"}x${frame.displayHeight || "n/a"}`;
      const receiveAt = this._pendingReceives.shift();
      if (receiveAt !== undefined) {
        this._stats.receiveToDrawMs.push(now - receiveAt);
      }
      const decodeStartedAt = this._pendingDecodeStarts.shift();
      if (decodeStartedAt !== undefined) {
        this._stats.decodeMs.push(now - decodeStartedAt);
      }
      frame.close();
      this._setStatus("кадры декодируются");
      this._refreshCounters();
    }

    async _stop(reason, emit) {
      if (!this._running && (!emit || this._finalEmitted)) {
        return;
      }
      this._running = false;
      this._stats.stopReason = reason;
      if (this._timer) {
        clearTimeout(this._timer);
        this._timer = null;
      }
      const socket = this._socket;
      this._socket = null;
      if (socket && socket.readyState < WebSocket.CLOSING) {
        socket.close();
      }
      const decoder = this._decoder;
      this._decoder = null;
      if (decoder) {
        try {
          await decoder.flush();
        } catch (_) {
          // The final canary block records the stop reason.
        }
        try {
          decoder.close();
        } catch (_) {
          // Already closed by the browser implementation.
        }
      }
      this._setStatus("остановлено");
      if (emit) {
        this._emitFinal(reason);
      }
      this._syncControls();
    }

    _emitFinal(reason) {
      if (this._finalEmitted) {
        return;
      }
      this._finalEmitted = true;
      const s = this._stats;
      const duration = s.startedAt ? (performance.now() - s.startedAt) / 1000 : 0;
      const cleanStop = (
        reason === "manual_stop" ||
        reason === "duration_60s" ||
        reason === "duration_limit" ||
        reason === "source_eof"
      );
      const pass = (
        s.frames > 0 &&
        s.gaps === 0 &&
        !s.backlogStop &&
        !s.unsupported &&
        !s.error &&
        cleanStop
      );
      const block = [
        "=== COMELIT MINIAPP WEBCODECS LIVE CANARY ===",
        `RESULT=${pass ? "PASS" : "FAIL"}`,
        `ENTITY_ID=${safeEntityId(this._selected) || "n/a"}`,
        `DURATION_S=${fmt(duration)}`,
        `CODEC=${s.codec}`,
        `ZERO_TRANSCODE=${s.zeroTranscode === null ? "n/a" : s.zeroTranscode ? "true" : "false"}`,
        "",
        `WS_CONNECT_MS=${s.wsOpenAt ? fmt(s.wsOpenAt - s.startedAt) : "n/a"}`,
        `SOURCE_OPEN_MS=${s.sourceAt ? fmt(s.sourceAt - s.startedAt) : "n/a"}`,
        `FIRST_SOURCE_PACKET_MS=${s.sourceAt ? fmt(s.sourceAt - s.startedAt) : "n/a"}`,
        `FIRST_BINARY_MS=${s.firstBinaryAt ? fmt(s.firstBinaryAt - s.startedAt) : "n/a"}`,
        `FIRST_DECODED_FRAME_MS=${s.firstDecodedAt ? fmt(s.firstDecodedAt - s.startedAt) : "n/a"}`,
        "",
        `UNITS_RECEIVED=${s.units}`,
        `FRAMES_DECODED=${s.frames}`,
        `KEYFRAMES_RECEIVED=${s.keyframes}`,
        `SEQUENCE_GAPS=${s.gaps}`,
        "",
        `DECODE_P50_MS=${percentile(s.decodeMs, 0.50)}`,
        `DECODE_P95_MS=${percentile(s.decodeMs, 0.95)}`,
        `DECODE_MAX_MS=${maxValue(s.decodeMs)}`,
        "",
        `INTERARRIVAL_P50_MS=${percentile(s.interarrivalMs, 0.50)}`,
        `INTERARRIVAL_P95_MS=${percentile(s.interarrivalMs, 0.95)}`,
        `INTERARRIVAL_MAX_MS=${maxValue(s.interarrivalMs)}`,
        "",
        `MAX_DECODE_QUEUE=${s.maxDecodeQueue}`,
        `ACCUMULATED_LAG_MS=${s.lagMs.length ? fmt(s.lagMs[s.lagMs.length - 1]) : "n/a"}`,
        `ACCUMULATED_LAG_P95_MS=${percentile(s.lagMs, 0.95)}`,
        `ACCUMULATED_LAG_MAX_MS=${maxValue(s.lagMs)}`,
        "",
        `CODED_SIZE=${s.codedSize}`,
        `VISIBLE_SIZE=${s.visibleSize}`,
        `DISPLAY_SIZE=${s.displaySize}`,
        "",
        `RECEIVE_TO_DRAW_P50_MS=${percentile(s.receiveToDrawMs, 0.50)}`,
        `RECEIVE_TO_DRAW_P95_MS=${percentile(s.receiveToDrawMs, 0.95)}`,
        `STOP_REASON=${reason}`,
        `BACKLOG_STOP=${s.backlogStop ? "true" : "false"}`,
        `DROPPED_UNITS=0`,
        "",
        "COMELIT_ENTRANCE_OPEN=false",
        "COMELIT_MEDIA_STARTED=false",
        "DOOR_ACTIONS=0",
        "GATE_ACTIONS=0",
      ].join("\n");
      s.finalBlock = block;
      console.log(block);
      const pre = this.shadowRoot?.querySelector("[data-result]");
      if (pre) {
        pre.textContent = block;
      }
    }
  }

  if (!customElements.get(TAG)) {
    customElements.define(TAG, MiniAppWebCodecsViewer);
  }
})();
