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
      this._failed = false;
      this._requestGeneration = 0;
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
      this.replaceChildren(error);
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

    _markFirstWebRTCFrame(generation) {
      if (
        this._firstFrameSeen ||
        generation !== this._requestGeneration ||
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
          !this.isConnected ||
          this._peerConnection !== peer ||
          this._firstFrameSeen
        ) {
          return;
        }

        let bytesReceived = 0;
        let framesDecoded = 0;
        try {
          const stats = await peer.getStats();
          stats.forEach((report) => {
            if (
              report.type === "inbound-rtp" &&
              (report.kind === "video" || report.mediaType === "video") &&
              !report.isRemote
            ) {
              bytesReceived += Number(report.bytesReceived || 0);
              framesDecoded += Number(report.framesDecoded || 0);
            }
          });
        } catch (_) {
          // Keep the timing status even if WebRTC stats are unavailable.
        }

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

        if (
          elapsed >= 10 &&
          bytesReceived === 0 &&
          ["new", "checking", "disconnected", "failed"].includes(iceState)
        ) {
          this._setTransportLabel(
            "WebRTC · ICE " + iceState + " · fallback HLS",
          );
          this._fallbackToHls(entityId, generation);
        }
      }, 2000);
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

      this._setTransportLabel("HLS");

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
          video.play().catch(() => {
            // Telegram autoplay policy may still require an explicit Play tap.
          });
        });

        hls.on(HlsClass.Events.ERROR, (_event, data) => {
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
        } catch (_) {
          // Native-HLS autoplay may require an explicit Play tap.
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

    _fallbackToHls(entityId, generation) {
      if (
        this._webrtcFallbackStarted ||
        generation !== this._requestGeneration ||
        !this.isConnected ||
        !this._video
      ) {
        return;
      }

      this._webrtcFallbackStarted = true;
      this._destroyWebRTC();
      this._openHls(entityId, generation);
    }

    _openWebRTC(entityId, generation) {
      if (typeof RTCPeerConnection !== "function") {
        this._fallbackToHls(entityId, generation);
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
        this._fallbackToHls(entityId, generation);
        return;
      }
      this._websocket = socket;
      this._webrtcStartTime = performance.now();
      this._firstFrameSeen = false;
      this._setTransportLabel("WebRTC · подключение…");

      // This timeout covers signaling failure only. A remote track may be
      // announced before the first decodable frame arrives, so first-frame
      // waiting is diagnosed separately instead of being mistaken for success.
      this._webrtcTimer = setTimeout(() => {
        if (!this._remoteStream) {
          this._fallbackToHls(entityId, generation);
        }
      }, 12000);

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
              if (state === "failed") {
                this._fallbackToHls(entityId, generation);
              }
            };

            peer.onconnectionstatechange = () => {
              if (
                peer.connectionState === "failed" &&
                generation === this._requestGeneration
              ) {
                this._fallbackToHls(entityId, generation);
              }
            };

            const offer = await peer.createOffer({
              offerToReceiveAudio: true,
              offerToReceiveVideo: true,
            });
            await peer.setLocalDescription(offer);
            if (
              socket.readyState === WebSocket.OPEN &&
              peer.localDescription?.sdp
            ) {
              socket.send(
                JSON.stringify({
                  type: "offer",
                  sdp: peer.localDescription.sdp,
                }),
              );
            }
          } catch (_) {
            this._fallbackToHls(entityId, generation);
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
            for (const candidate of this._pendingRemoteCandidates.splice(0)) {
              await peer.addIceCandidate(candidate);
            }
          } catch (_) {
            this._fallbackToHls(entityId, generation);
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
            this._fallbackToHls(entityId, generation);
          }
          return;
        }

        if (message.type === "error") {
          this._fallbackToHls(entityId, generation);
        }
      };

      socket.onerror = () => {
        this._fallbackToHls(entityId, generation);
      };
      socket.onclose = () => {
        if (
          generation === this._requestGeneration &&
          !this._webrtcFallbackStarted
        ) {
          this._fallbackToHls(entityId, generation);
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

      const video = document.createElement("video");
      video.className = "miniapp-video";
      video.controls = true;
      video.autoplay = true;
      video.muted = true;
      video.playsInline = true;
      video.setAttribute("playsinline", "");
      video.setAttribute("webkit-playsinline", "");
      this._video = video;
      shell.appendChild(video);

      if (this._config.show_name !== false) {
        const label = document.createElement("div");
        label.className = "miniapp-video-label";
        label.textContent = name;
        this._labelElement = label;
        shell.appendChild(label);
      }

      this.replaceChildren(shell);
      const generation = ++this._requestGeneration;
      this._webrtcFallbackStarted = false;

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
