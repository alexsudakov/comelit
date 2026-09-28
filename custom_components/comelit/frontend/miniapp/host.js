(() => {
  "use strict";

  const telegram = window.Telegram?.WebApp;
  const card = document.getElementById("comelitCard");
  const startupStatus = document.getElementById("startupStatus");
  const fatalError = document.getElementById("fatalError");

  let bootstrap = null;
  let hass = null;
  let actionNonce = null;
  let refreshTimer = null;
  let refreshInFlight = false;

  // The shared comelit-card mounts this viewer inside its Shadow DOM.
  // Page-level styles.css cannot style descendants across that boundary.
  const VIEWER_STYLES = `
    :host { display: block; min-width: 0; max-width: 100%; }
    * { box-sizing: border-box; }
    .miniapp-video-shell {
      width: 100%; max-width: 100%; overflow: hidden;
      border-radius: 12px; background: #000;
    }
    .miniapp-video-stage {
      position: relative; width: 100%; max-width: 100%; min-width: 0;
      overflow: hidden; contain: layout paint size; background: #000;
    }
    .miniapp-video-shell.surveillance .miniapp-video-stage {
      height: clamp(180px, 34dvh, 320px);
    }
    .miniapp-video-shell.intercom .miniapp-video-stage {
      height: clamp(220px, 52dvh, 520px);
    }
    .miniapp-video {
      position: absolute; inset: 0; display: block;
      width: 100%; height: 100%; max-width: 100%; max-height: 100%;
      object-fit: contain; background: #000;
    }
    .miniapp-video-label {
      padding: 8px 10px; background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #111827);
    }
    .miniapp-video-error {
      padding: 16px; color: var(--error-color, #dc2626);
      background: var(--secondary-background-color, #f3f4f6);
    }
  `;

  if (!customElements.get("ha-card")) {
    customElements.define(
      "ha-card",
      class extends HTMLElement {
        connectedCallback() {
          this.style.display = "block";
        }
      },
    );
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
    });

    if (!response.ok) {
      let detail = "HTTP " + response.status;
      try {
        const body = await response.json();
        detail = body.error || body.detail || detail;
      } catch (_) {
        // Keep HTTP fallback.
      }
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }

    if (response.status === 204) {
      return null;
    }
    return response.json();
  }

  function isIntercomCameraEntity(entityId) {
    const entry = (bootstrap?.entity_registry || []).find(
      (candidate) => candidate.entity_id === entityId,
    );
    return (
      entry?.platform === "comelit" &&
      entry?.unique_id === "comelit_entrance_camera"
    );
  }

  class MiniAppPictureEntity extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({mode: "open"});
      this._config = null;
      this._hass = null;
      this._video = null;
      this._labelElement = null;
      this._displayName = "";
      this._hls = null;
      this._peerConnection = null;
      this._websocket = null;
      this._remoteStream = null;
      this._pendingRemoteCandidates = [];
      this._pendingLocalCandidates = [];
      this._webrtcSessionReady = false;
      this._webrtcFallbackStarted = false;
      this._webrtcTimer = null;
      this._webrtcStatsTimer = null;
      this._webrtcStartTime = null;
      this._firstFrameSeen = false;
      this._firstHlsFrameSeen = false;
      this._firstMovingFrameSeen = false;
      this._viewStartTime = null;
      this._playbackMode = null;
      this._failed = false;
      this._requestGeneration = 0;
      this._diagnostics = null;
    }

    setConfig(config) {
      this._config = config;
      this._render();
    }

    set hass(value) {
      this._hass = value;
      this._render();
    }

    connectedCallback() {
      this._render();
    }

    disconnectedCallback() {
      if (this._playbackMode === "webrtc" && !this._webrtcFallbackStarted) {
        this._reportDiagnostics("fallback", {reason: "navigate"});
      }
      this._requestGeneration += 1;
      this._destroyPlayback();
      this._video = null;
      this._labelElement = null;
    }

    _setTransportLabel(transport) {
      if (!this._labelElement) {
        return;
      }
      this._labelElement.textContent = transport
        ? this._displayName + " · " + transport
        : this._displayName;
    }

    _destroyWebRTC() {
      if (this._webrtcTimer) {
        clearTimeout(this._webrtcTimer);
        this._webrtcTimer = null;
      }
      if (this._webrtcStatsTimer) {
        clearInterval(this._webrtcStatsTimer);
        this._webrtcStatsTimer = null;
      }
      this._webrtcStartTime = null;
      this._firstFrameSeen = false;
      this._firstMovingFrameSeen = false;

      const socket = this._websocket;
      this._websocket = null;
      if (socket && socket.readyState === WebSocket.OPEN) {
        try {
          socket.send(JSON.stringify({type: "close"}));
        } catch (_) {
          // Best-effort session close; closing the socket is authoritative.
        }
      }
      if (socket && socket.readyState < WebSocket.CLOSING) {
        socket.close();
      }

      if (this._peerConnection) {
        this._peerConnection.close();
        this._peerConnection = null;
      }

      if (this._remoteStream) {
        for (const track of this._remoteStream.getTracks()) {
          track.stop();
        }
        this._remoteStream = null;
      }
      this._pendingRemoteCandidates = [];
      this._pendingLocalCandidates = [];
      this._webrtcSessionReady = false;

      if (this._video) {
        this._video.srcObject = null;
      }
    }

    _destroyPlayback() {
      this._playbackMode = null;
      this._destroyWebRTC();

      if (this._hls) {
        this._hls.destroy();
        this._hls = null;
      }
      if (this._video) {
        this._video.pause();
        this._video.srcObject = null;
        this._video.removeAttribute("src");
        this._video.load();
      }
    }

    _showPlaybackError(message) {
      this._failed = true;
      this._destroyPlayback();
      this._video = null;
      const error = document.createElement("div");
      error.className = "miniapp-video-error";
      error.textContent = message;
      this._replaceContent(error);
    }

    _replaceContent(content) {
      const style = document.createElement("style");
      style.textContent = VIEWER_STYLES;
      this.shadowRoot.replaceChildren(style, content);
    }

    _formatBytes(value) {
      const bytes = Number(value) || 0;
      if (bytes < 1024) {
        return bytes + " B";
      }
      if (bytes < 1024 * 1024) {
        return (bytes / 1024).toFixed(1) + " KiB";
      }
      return (bytes / (1024 * 1024)).toFixed(1) + " MiB";
    }

    _startDiagnostics(entityId, generation) {
      this._diagnostics = {
        entityId,
        generation,
        start: performance.now(),
        stage: performance.now(),
        count: 0,
        lastAt: -Infinity,
        lastTriple: "",
        queuedTriples: new Set(),
      };
    }

    _diagnosticElapsed() {
      const diagnostics = this._diagnostics;
      if (!diagnostics) {
        return {elapsed_ms: 0, stage_ms: 0};
      }
      const now = performance.now();
      const elapsed_ms = Math.max(0, Math.min(600000, Math.round(now - diagnostics.start)));
      const stage_ms = Math.max(0, Math.min(600000, Math.round(now - diagnostics.stage)));
      diagnostics.stage = now;
      return {elapsed_ms, stage_ms};
    }

    _reportDiagnostics(event, options = {}) {
      const diagnostics = this._diagnostics;
      if (
        !diagnostics ||
        diagnostics.generation !== this._requestGeneration ||
        diagnostics.count >= 60
      ) {
        return;
      }
      const triple =
        event + "|" + (options.state || "") + "|" + (options.reason || "");
      const now = performance.now();
      if (triple === diagnostics.lastTriple) {
        return;
      }
      if (diagnostics.count > 0 && now - diagnostics.lastAt < 250) {
        if (!diagnostics.queuedTriples.has(triple)) {
          diagnostics.queuedTriples.add(triple);
          setTimeout(() => {
            diagnostics.queuedTriples.delete(triple);
            this._reportDiagnostics(event, options);
          }, Math.max(0, 250 - (now - diagnostics.lastAt)));
        }
        return;
      }
      diagnostics.count += 1;
      diagnostics.lastAt = now;
      diagnostics.lastTriple = triple;
      const timing = this._diagnosticElapsed();
      const payload = {
        event,
        elapsed_ms: timing.elapsed_ms,
        stage_ms: timing.stage_ms,
      };
      if (options.state) {
        payload.state = options.state;
      }
      if (options.reason) {
        payload.reason = options.reason;
      }
      if (options.counters) {
        payload.counters = options.counters;
      }
      fetch(
        "/api/comelit/miniapp/camera/" +
          encodeURIComponent(diagnostics.entityId) +
          "/diagnostics",
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-Comelit-MiniApp-Request": "1",
          },
          body: JSON.stringify(payload),
        },
      ).catch(() => {});
    }

    _boundedCounter(value) {
      const number = Number(value);
      if (!Number.isFinite(number) || number <= 0) {
        return 0;
      }
      return Math.min(1000000, Math.round(number));
    }

    _videoCounters(video) {
      const duration = Number(video.duration);
      const counters = {
        paused: video.paused ? 1 : 0,
        ended: video.ended ? 1 : 0,
        ready_state: this._boundedCounter(video.readyState),
        network_state: this._boundedCounter(video.networkState),
        buffered_count: this._boundedCounter(video.buffered?.length || 0),
        seekable_count: this._boundedCounter(video.seekable?.length || 0),
      };
      let bufferedSeconds = 0;
      for (let index = 0; index < (video.buffered?.length || 0); index += 1) {
        bufferedSeconds += Math.max(0, video.buffered.end(index) - video.buffered.start(index));
      }
      let seekableSeconds = 0;
      for (let index = 0; index < (video.seekable?.length || 0); index += 1) {
        seekableSeconds += Math.max(0, video.seekable.end(index) - video.seekable.start(index));
      }
      counters.buffered_s = this._boundedCounter(bufferedSeconds);
      counters.seekable_s = this._boundedCounter(seekableSeconds);
      if (Number.isFinite(duration)) {
        counters.live_latency_s = this._boundedCounter(duration - Number(video.currentTime || 0));
      }
      return counters;
    }

    _hlsErrorReason(data) {
      const allowed = new Set([
        "networkError",
        "mediaError",
        "muxError",
        "keySystemError",
        "otherError",
        "manifestLoadError",
        "manifestLoadTimeOut",
        "manifestParsingError",
        "levelLoadError",
        "levelLoadTimeOut",
        "fragLoadError",
        "fragLoadTimeOut",
        "bufferStalledError",
        "bufferSeekOverHole",
        "bufferNudgeOnStall",
        "internalException",
      ]);
      if (allowed.has(data?.details)) {
        return data.details;
      }
      if (allowed.has(data?.type)) {
        return data.type;
      }
      return data?.fatal ? "fatal" : "nonfatal";
    }

    _playErrorState(error) {
      const name = error?.name;
      if (
        [
          "NotAllowedError",
          "AbortError",
          "NotSupportedError",
          "NotReadableError",
          "SecurityError",
          "TypeError",
        ].includes(name)
      ) {
        return name;
      }
      return "rejected";
    }

    async _webrtcCounters(peer) {
      const counters = {
        bytes_received: 0,
        frames_decoded: 0,
      };
      const candidateTypes = new Set(["host", "srflx", "prflx", "relay"]);
      const protocols = new Set(["udp", "tcp"]);
      const pairStates = new Set([
        "waiting",
        "in-progress",
        "succeeded",
        "failed",
      ]);
      try {
        const stats = await peer.getStats();
        stats.forEach((report) => {
          if (
            report.type === "inbound-rtp" &&
            (report.kind === "video" || report.mediaType === "video") &&
            !report.isRemote
          ) {
            counters.bytes_received += this._boundedCounter(report.bytesReceived || 0);
            counters.frames_decoded += this._boundedCounter(report.framesDecoded || 0);
          }
          if (
            (report.type === "local-candidate" ||
              report.type === "remote-candidate") &&
            candidateTypes.has(report.candidateType)
          ) {
            const prefix = report.type === "local-candidate" ? "local" : "remote";
            counters[prefix + "_" + report.candidateType] =
              (counters[prefix + "_" + report.candidateType] || 0) + 1;
            const protocol = String(report.protocol || "").toLowerCase();
            if (protocols.has(protocol)) {
              counters[prefix + "_" + protocol] =
                (counters[prefix + "_" + protocol] || 0) + 1;
            }
          }
          if (report.type === "candidate-pair") {
            const state = String(report.state || "");
            if (pairStates.has(state)) {
              const key = "pair_" + state.replace("-", "_");
              counters[key] = (counters[key] || 0) + 1;
            }
            if (report.nominated) {
              counters.pair_nominated = (counters.pair_nominated || 0) + 1;
            }
          }
        });
      } catch (_) {
        // Keep diagnostics best-effort; playback timing remains authoritative.
      }
      counters.bytes_received = this._boundedCounter(counters.bytes_received);
      counters.frames_decoded = this._boundedCounter(counters.frames_decoded);
      return counters;
    }

    _markFirstWebRTCFrame(generation) {
      if (
        this._firstFrameSeen ||
        generation !== this._requestGeneration ||
        this._playbackMode !== "webrtc" ||
        !this.isConnected
      ) {
        return;
      }
      this._firstFrameSeen = true;
      if (this._webrtcTimer) {
        clearTimeout(this._webrtcTimer);
        this._webrtcTimer = null;
      }
      if (this._webrtcStatsTimer) {
        clearInterval(this._webrtcStatsTimer);
        this._webrtcStatsTimer = null;
      }
      const elapsed = this._webrtcStartTime
        ? (performance.now() - this._webrtcStartTime) / 1000
        : 0;
      this._setTransportLabel(
        "WebRTC · первый кадр " + elapsed.toFixed(1) + " с",
      );
      this._reportDiagnostics("first_frame");
      const video = this._video;
      if (video && typeof video.requestVideoFrameCallback === "function") {
        video.requestVideoFrameCallback(() => {
          if (
            this._firstMovingFrameSeen ||
            generation !== this._requestGeneration ||
            this._playbackMode !== "webrtc" ||
            !this.isConnected
          ) {
            return;
          }
          this._firstMovingFrameSeen = true;
          this._reportDiagnostics("first_moving_frame");
        });
      }
    }

    _markFirstHlsFrame(generation) {
      if (
        this._firstHlsFrameSeen ||
        generation !== this._requestGeneration ||
        this._playbackMode !== "hls" ||
        !this.isConnected
      ) {
        return;
      }
      this._firstHlsFrameSeen = true;
      const elapsed = this._viewStartTime
        ? (performance.now() - this._viewStartTime) / 1000
        : 0;
      this._setTransportLabel("HLS · первый кадр " + elapsed.toFixed(1) + " с");
      this._reportDiagnostics("hls_first_frame", {
        counters: this._video ? this._videoCounters(this._video) : undefined,
      });
    }

    _watchWebRTCFirstFrame(peer, video, entityId, generation) {
      const mark = () => this._markFirstWebRTCFrame(generation);

      if (typeof video.requestVideoFrameCallback === "function") {
        video.requestVideoFrameCallback(() => mark());
      } else {
        video.addEventListener("loadeddata", mark, {once: true});
      }

      this._webrtcStatsTimer = setInterval(async () => {
        if (
          generation !== this._requestGeneration ||
          this._playbackMode !== "webrtc" ||
          !this.isConnected ||
          this._peerConnection !== peer ||
          this._firstFrameSeen
        ) {
          return;
        }

        const counters = await this._webrtcCounters(peer);
        const bytesReceived = counters.bytes_received;
        const framesDecoded = counters.frames_decoded;

        const elapsed = this._webrtcStartTime
          ? Math.round((performance.now() - this._webrtcStartTime) / 1000)
          : 0;
        const iceState = peer.iceConnectionState || "unknown";
        this._setTransportLabel(
          "WebRTC · ожидание кадра " +
            elapsed +
            " с · ICE " +
            iceState +
            " · RTP " +
            this._formatBytes(bytesReceived) +
            " · decoded " +
            framesDecoded,
        );
        this._reportDiagnostics("rtp", {state: iceState, counters});

        if (
          bytesReceived === 0 &&
          (elapsed >= 8 ||
            (elapsed >= 5 &&
              ["new", "checking", "disconnected", "failed"].includes(iceState)))
        ) {
          this._setTransportLabel(
            "WebRTC · ICE " + iceState + " · fallback HLS",
          );
          this._fallbackToHls(
            entityId,
            generation,
            ["new", "checking", "disconnected", "failed"].includes(iceState)
              ? "stats_deadline_checking"
              : "stats_deadline_other",
          );
        }
      }, 1000);
    }

    async _startHlsPlayback(source, generation) {
      const video = this._video;
      if (
        generation !== this._requestGeneration ||
        !this.isConnected ||
        !video
      ) {
        return;
      }

      this._playbackMode = "hls";
      this._setTransportLabel("HLS");
      const markHlsFrame = () => this._markFirstHlsFrame(generation);
      if (typeof video.requestVideoFrameCallback === "function") {
        video.requestVideoFrameCallback(markHlsFrame);
      } else {
        video.addEventListener("loadeddata", markHlsFrame, {once: true});
      }

      const HlsClass = window.Hls;
      if (
        HlsClass &&
        typeof HlsClass.isSupported === "function" &&
        HlsClass.isSupported()
      ) {
        const hls = new HlsClass({
          enableWorker: false,
          lowLatencyMode: true,
          backBufferLength: 30,
        });
        this._hls = hls;

        hls.on(HlsClass.Events.MANIFEST_PARSED, () => {
          if (
            generation !== this._requestGeneration ||
            !this.isConnected ||
            this._video !== video
          ) {
            return;
          }
          this._reportDiagnostics("hls_manifest", {
            counters: this._videoCounters(video),
          });
          video.play().then(() => {
            this._reportDiagnostics("hls_play", {
              state: "resolved",
              counters: this._videoCounters(video),
            });
          }).catch((error) => {
            const state = this._playErrorState(error);
            this._reportDiagnostics("hls_play", {
              state,
              counters: this._videoCounters(video),
            });
            this._reportDiagnostics("hls_blocked", {
              state,
              counters: this._videoCounters(video),
            });
            this._setTransportLabel("HLS · нажмите Play");
          });
        });

        hls.on(HlsClass.Events.ERROR, (_event, data) => {
          this._reportDiagnostics("hls_error", {
            reason: this._hlsErrorReason(data),
            counters: {
              fatal: data?.fatal ? 1 : 0,
              ...this._videoCounters(video),
            },
          });
          if (
            !data?.fatal ||
            generation !== this._requestGeneration ||
            !this.isConnected
          ) {
            return;
          }
          const detail = data.details || data.type || "fatal";
          this._showPlaybackError(
            "Не удалось воспроизвести HLS-поток: " + detail,
          );
        });

        hls.loadSource(source);
        hls.attachMedia(video);
        return;
      }

      if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = source;
        try {
          await video.play();
          this._reportDiagnostics("hls_play", {
            state: "resolved",
            counters: this._videoCounters(video),
          });
        } catch (error) {
          const state = this._playErrorState(error);
          this._reportDiagnostics("hls_play", {
            state,
            counters: this._videoCounters(video),
          });
          this._reportDiagnostics("hls_blocked", {
            state,
            counters: this._videoCounters(video),
          });
          this._setTransportLabel("HLS · нажмите Play");
        }
        return;
      }

      this._showPlaybackError(
        "Этот Telegram WebView не поддерживает HLS или MediaSource.",
      );
    }

    async _openHls(entityId, generation) {
      try {
        const result = await fetchJson(
          "/api/comelit/miniapp/camera/" +
            encodeURIComponent(entityId) +
            "/stream",
          {
            method: "POST",
            headers: {"X-Comelit-MiniApp-Request": "1"},
          },
        );
        if (
          generation !== this._requestGeneration ||
          !this.isConnected ||
          !this._video
        ) {
          return;
        }

        await this._startHlsPlayback(result.url, generation);
      } catch (error) {
        if (generation !== this._requestGeneration || !this.isConnected) {
          return;
        }
        this._showPlaybackError(
          "Не удалось открыть видеопоток: " +
            (error?.message || "ошибка"),
        );
      }
    }

    _fallbackToHls(entityId, generation, reason = "stats_deadline_other") {
      // Historical invariant: every call still resolves through
      // _fallbackToHls(entityId, generation), with an added bounded reason.
      if (
        this._webrtcFallbackStarted ||
        generation !== this._requestGeneration ||
        !this.isConnected ||
        !this._video
      ) {
        return;
      }

      this._webrtcFallbackStarted = true;
      this._reportDiagnostics("fallback", {reason});
      // Invalidate any pending WebRTC video-frame callback before attaching
      // HLS to the same <video> element. Otherwise the first HLS frame can be
      // misreported as a successful WebRTC frame.
      this._playbackMode = "hls";
      this._destroyWebRTC();
      this._openHls(entityId, generation);
    }

    _openWebRTC(entityId, generation) {
      if (typeof RTCPeerConnection !== "function") {
        this._fallbackToHls(entityId, generation, "no_rtcpeerconnection");
        return;
      }

      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url =
        scheme +
        "//" +
        window.location.host +
        "/api/comelit/miniapp/camera/" +
        encodeURIComponent(entityId) +
        "/webrtc";

      let socket;
      try {
        socket = new WebSocket(url);
      } catch (_) {
        this._fallbackToHls(entityId, generation, "websocket_error");
        return;
      }
      this._websocket = socket;
      this._playbackMode = "webrtc";
      this._webrtcStartTime = performance.now();
      this._firstFrameSeen = false;
      this._setTransportLabel("WebRTC · подключение…");

      // This timeout covers signaling failure only. A remote track may be
      // announced before the first decodable frame arrives, so first-frame
      // waiting is diagnosed separately instead of being mistaken for success.
      this._webrtcTimer = setTimeout(() => {
        if (!this._remoteStream) {
          this._fallbackToHls(entityId, generation, "stats_deadline_other");
        }
      }, 6000);

      socket.onmessage = async (event) => {
        if (
          generation !== this._requestGeneration ||
          !this.isConnected ||
          this._websocket !== socket
        ) {
          return;
        }

        let message;
        try {
          message = JSON.parse(event.data);
        } catch (_) {
          return;
        }

        if (message.type === "config") {
          this._reportDiagnostics("config");
          try {
            const peer = new RTCPeerConnection(message.configuration || {});
            this._peerConnection = peer;
            this._remoteStream = new MediaStream();
            this._pendingRemoteCandidates = [];
            this._pendingLocalCandidates = [];
            this._webrtcSessionReady = false;

            // Mirror Home Assistant's native WebRTC player negotiation shape.
            // go2rtc may expose audio+video even though the Mini App stays muted.
            peer.addTransceiver("audio", {direction: "recvonly"});
            peer.addTransceiver("video", {direction: "recvonly"});

            peer.ontrack = (trackEvent) => {
              if (
                generation !== this._requestGeneration ||
                this._peerConnection !== peer ||
                !this._video
              ) {
                return;
              }

              if (trackEvent.track?.kind === "audio") {
                return;
              }

              if (trackEvent.streams?.[0]) {
                this._remoteStream = trackEvent.streams[0];
              } else if (trackEvent.track) {
                this._remoteStream.addTrack(trackEvent.track);
              }
              this._video.srcObject = this._remoteStream;
              this._setTransportLabel("WebRTC · track получен, ждём кадр…");
              this._reportDiagnostics("track");
              if (this._webrtcTimer) {
                clearTimeout(this._webrtcTimer);
                this._webrtcTimer = null;
              }
              this._watchWebRTCFirstFrame(
                peer,
                this._video,
                entityId,
                generation,
              );
              this._video.play().catch(() => {
                // Telegram autoplay policy may require an explicit Play tap.
              });
            };

            peer.onicecandidate = (candidateEvent) => {
              if (!candidateEvent.candidate) {
                return;
              }
              const candidate = candidateEvent.candidate.toJSON();
              if (
                this._webrtcSessionReady &&
                socket.readyState === WebSocket.OPEN
              ) {
                socket.send(
                  JSON.stringify({
                    type: "candidate",
                    candidate,
                  }),
                );
              } else {
                this._pendingLocalCandidates.push(candidate);
              }
            };

            peer.oniceconnectionstatechange = () => {
              if (
                generation !== this._requestGeneration ||
                this._peerConnection !== peer
              ) {
                return;
              }
              const state = peer.iceConnectionState;
              if (!this._firstFrameSeen) {
                this._setTransportLabel("WebRTC · ICE " + state);
              }
              this._reportDiagnostics("ice", {state});
              if (state === "failed") {
                this._fallbackToHls(entityId, generation, "ice_failed");
              }
            };

            peer.onconnectionstatechange = () => {
              if (
                peer.connectionState === "failed" &&
                generation === this._requestGeneration
              ) {
                this._fallbackToHls(entityId, generation, "connection_failed");
              }
            };

            const offer = await peer.createOffer({
              offerToReceiveAudio: true,
              offerToReceiveVideo: true,
            });
            await peer.setLocalDescription(offer);
            this._reportDiagnostics("offer");

            // Match Home Assistant's native WebRTC player: include local ICE
            // candidates gathered before the provider session id arrives in
            // the initial SDP, then trickle only later candidates.
            let offerSdp = offer.sdp || "";
            while (this._pendingLocalCandidates.length) {
              const candidate = this._pendingLocalCandidates.pop();
              if (candidate?.candidate) {
                offerSdp += "a=" + candidate.candidate + "\r\n";
              }
            }

            if (socket.readyState === WebSocket.OPEN && offerSdp) {
              socket.send(
                JSON.stringify({
                  type: "offer",
                  sdp: offerSdp,
                }),
              );
            }
          } catch (_) {
            this._fallbackToHls(entityId, generation, "offer_error");
          }
          return;
        }

        const peer = this._peerConnection;
        if (!peer) {
          return;
        }

        if (message.type === "session") {
          this._webrtcSessionReady = true;
          if (socket.readyState === WebSocket.OPEN) {
            for (const candidate of this._pendingLocalCandidates.splice(0)) {
              socket.send(
                JSON.stringify({
                  type: "candidate",
                  candidate,
                }),
              );
            }
          }
          return;
        }

        if (message.type === "answer" && typeof message.answer === "string") {
          try {
            await peer.setRemoteDescription({
              type: "answer",
              sdp: message.answer,
            });
            this._reportDiagnostics("answer");
            for (const candidate of this._pendingRemoteCandidates.splice(0)) {
              await peer.addIceCandidate(candidate);
            }
          } catch (_) {
            this._fallbackToHls(entityId, generation, "answer_error");
          }
          return;
        }

        if (message.type === "candidate" && message.candidate) {
          try {
            const raw = message.candidate;
            const candidate =
              raw.sdpMid || raw.sdpMLineIndex != null
                ? new RTCIceCandidate(raw)
                : new RTCIceCandidate({
                    candidate: raw.candidate,
                    sdpMid: "0",
                  });
            if (peer.remoteDescription) {
              await peer.addIceCandidate(candidate);
            } else {
              this._pendingRemoteCandidates.push(candidate);
            }
          } catch (_) {
            this._fallbackToHls(entityId, generation, "candidate_error");
          }
          return;
        }

        if (message.type === "error") {
          this._fallbackToHls(
            entityId,
            generation,
            message.code === "miniapp_session_expired"
              ? "session_expired"
              : "answer_error",
          );
        }
      };

      socket.onerror = () => {
        this._fallbackToHls(entityId, generation, "websocket_error");
      };
      socket.onclose = () => {
        if (
          generation === this._requestGeneration &&
          !this._webrtcFallbackStarted
        ) {
          this._fallbackToHls(entityId, generation, "websocket_closed");
        }
      };
    }

    _render() {
      if (
        !this.isConnected ||
        !this._config?.entity ||
        this._video ||
        this._failed
      ) {
        return;
      }

      const entityId = this._config.entity;
      const state = this._hass?.states?.[entityId];
      const name = state?.attributes?.friendly_name || entityId;
      this._displayName = name;

      const shell = document.createElement("div");
      shell.className =
        "miniapp-video-shell " +
        (this._config.show_name !== false ? "surveillance" : "intercom");

      const stage = document.createElement("div");
      stage.className = "miniapp-video-stage";

      const video = document.createElement("video");
      video.className = "miniapp-video";
      video.controls = true;
      video.autoplay = true;
      video.muted = true;
      video.playsInline = true;
      video.setAttribute("playsinline", "");
      video.setAttribute("webkit-playsinline", "");
      video.addEventListener("playing", () => {
        this._reportDiagnostics("hls_state", {
          state: "playing",
          counters: this._videoCounters(video),
        });
      });
      video.addEventListener("pause", () => {
        this._reportDiagnostics("hls_state", {
          state: "paused",
          counters: this._videoCounters(video),
        });
      });
      video.addEventListener("ended", () => {
        this._reportDiagnostics("hls_state", {
          state: "ended",
          counters: this._videoCounters(video),
        });
      });
      video.addEventListener("seeking", () => {
        this._reportDiagnostics("hls_seek", {
          state: "seeking",
          counters: this._videoCounters(video),
        });
      });
      this._video = video;
      stage.appendChild(video);
      shell.appendChild(stage);

      if (this._config.show_name !== false) {
        const label = document.createElement("div");
        label.className = "miniapp-video-label";
        label.textContent = name;
        this._labelElement = label;
        shell.appendChild(label);
      }

      this._replaceContent(shell);
      const generation = ++this._requestGeneration;
      this._viewStartTime = performance.now();
      this._firstHlsFrameSeen = false;
      this._webrtcFallbackStarted = false;
      this._startDiagnostics(entityId, generation);

      if (isIntercomCameraEntity(entityId)) {
        this._openHls(entityId, generation);
      } else {
        this._openWebRTC(entityId, generation);
      }
    }
  }

  if (!customElements.get("miniapp-picture-entity")) {
    customElements.define("miniapp-picture-entity", MiniAppPictureEntity);
  }

  window.loadCardHelpers = async () => ({
    createCardElement: async (config) => {
      if (config?.type !== "picture-entity" || !config?.entity) {
        throw new Error("Mini App supports only picture-entity viewers");
      }
      const viewer = document.createElement("miniapp-picture-entity");
      viewer.setConfig(config);
      return viewer;
    },
  });

  function setFatal(message) {
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
    fatalError.hidden = false;
    fatalError.textContent = message;
    startupStatus.textContent = "Ошибка";
  }

  async function authenticate() {
    if (!telegram) {
      throw new Error("Mini App должен быть открыт внутри Telegram.");
    }

    telegram.ready();
    telegram.expand();

    if (!telegram.initData) {
      throw new Error("Telegram не передал initData.");
    }

    await fetchJson("/api/comelit/miniapp/session", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({init_data: telegram.initData}),
    });
  }

  async function refreshBootstrap() {
    bootstrap = await fetchJson("/api/comelit/miniapp/bootstrap");
    actionNonce = bootstrap.action_nonce;
    return bootstrap;
  }

  function doorForEntity(entityId) {
    const entry = (bootstrap?.entity_registry || []).find(
      (candidate) =>
        candidate.entity_id === entityId &&
        candidate.platform === "comelit",
    );
    if (entry?.unique_id === "comelit_main_entrance_open_door") {
      return "entrance";
    }
    if (entry?.unique_id === "comelit_main_gate_open_door") {
      return "gate";
    }
    return null;
  }

  function buildHassAdapter() {
    return {
      states: bootstrap.states || {},
      callWS: async (message) => {
        if (message?.type === "config/entity_registry/list") {
          return bootstrap.entity_registry || [];
        }
        if (message?.type === "config/label_registry/list") {
          return bootstrap.label_registry || [];
        }
        throw new Error("Unsupported Mini App callWS: " + String(message?.type));
      },
      callService: async (domain, service, data) => {
        if (domain !== "button" || service !== "press" || !data?.entity_id) {
          throw new Error("Unsupported Mini App service call");
        }

        const door = doorForEntity(data.entity_id);
        if (!door || !actionNonce) {
          throw new Error("Открытие сейчас недоступно.");
        }

        const usedNonce = actionNonce;
        actionNonce = null;
        try {
          const result = await fetchJson(
            "/api/comelit/miniapp/door/" + encodeURIComponent(door),
            {
              method: "POST",
              headers: {
                "X-Comelit-MiniApp-Request": "1",
                "X-Comelit-Action-Nonce": usedNonce,
              },
            },
          );
          actionNonce = result.action_nonce;
          await refreshState();
          return result;
        } catch (error) {
          // Never retry the Door action. Only refresh state and obtain a new
          // nonce for a later, explicit user click.
          try {
            await refreshBootstrap();
            hass.states = bootstrap.states || {};
            card.hass = hass;
          } catch (_) {
            // Preserve the original action error.
          }
          throw error;
        }
      },
    };
  }

  async function refreshState() {
    if (refreshInFlight) {
      return;
    }
    refreshInFlight = true;
    try {
      const result = await fetchJson("/api/comelit/miniapp/state");
      if (!hass) {
        return;
      }
      hass.states = result.states || {};
      card.hass = hass;
      startupStatus.classList.add("ready");
    } finally {
      refreshInFlight = false;
    }
  }

  function scheduleRefresh() {
    if (refreshTimer) {
      clearInterval(refreshTimer);
    }
    refreshTimer = setInterval(() => {
      refreshState().catch((error) => {
        if (error?.status === 403) {
          setFatal(
            "Сессия Mini App завершена. Закройте окно и откройте «Домофон» снова.",
          );
          return;
        }
        startupStatus.classList.remove("ready");
        startupStatus.textContent =
          "Связь с Home Assistant: " + (error?.message || "ошибка");
      });
    }, 2000);
  }

  async function start() {
    await authenticate();
    await refreshBootstrap();

    await customElements.whenDefined("comelit-card");
    card.setConfig({
      default_tab: "intercom",
      surveillance: {
        include: bootstrap.surveillance_entities || [],
      },
    });

    hass = buildHassAdapter();
    card.hass = hass;

    startupStatus.textContent = "Подключено";
    startupStatus.classList.add("ready");
    scheduleRefresh();
  }

  start().catch((error) => {
    setFatal(error?.message || "Не удалось запустить Comelit Mini App");
  });
})();
