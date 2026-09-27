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

  class MiniAppPictureEntity extends HTMLElement {
    constructor() {
      super();
      this._config = null;
      this._hass = null;
      this._video = null;
      this._hls = null;
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
    }

    _destroyPlayback() {
      if (this._hls) {
        this._hls.destroy();
        this._hls = null;
      }
      if (this._video) {
        this._video.pause();
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

    async _startPlayback(source, generation) {
      const video = this._video;
      if (
        generation !== this._requestGeneration ||
        !this.isConnected ||
        !video
      ) {
        return;
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

    async _openStream(entityId, generation) {
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

        await this._startPlayback(result.url, generation);
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

      const shell = document.createElement("div");
      shell.className = "miniapp-video-shell";

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
        shell.appendChild(label);
      }

      this.replaceChildren(shell);
      const generation = ++this._requestGeneration;
      this._openStream(entityId, generation);
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
