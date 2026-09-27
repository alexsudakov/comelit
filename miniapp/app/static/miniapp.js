(() => {
  "use strict";

  const telegram = window.Telegram?.WebApp;
  const card = document.getElementById("comelitCard");
  const startupStatus = document.getElementById("startupStatus");
  const fatalError = document.getElementById("fatalError");

  let bootstrap = null;
  let hass = null;
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

  class MiniAppPictureEntity extends HTMLElement {
    constructor() {
      super();
      this._config = null;
      this._hass = null;
      this._img = null;
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
      if (this._img) {
        this._img.removeAttribute("src");
      }
    }

    _render() {
      if (!this.isConnected || !this._config?.entity) {
        return;
      }

      const entityId = this._config.entity;
      const state = this._hass?.states?.[entityId];
      const name =
        state?.attributes?.friendly_name ||
        entityId;

      if (!this._img) {
        const wrapper = document.createElement("div");
        wrapper.style.cssText =
          "overflow:hidden;border-radius:12px;background:#000;min-height:120px;";
        this._img = document.createElement("img");
        this._img.alt = name;
        this._img.style.cssText =
          "display:block;width:100%;height:auto;min-height:120px;object-fit:contain;background:#000;";
        this._img.src =
          "/api/ha/camera/" + encodeURIComponent(entityId) + "/mjpeg";
        wrapper.appendChild(this._img);

        if (this._config.show_name !== false) {
          const label = document.createElement("div");
          label.textContent = name;
          label.style.cssText =
            "padding:8px 10px;background:var(--card-background-color);color:var(--primary-text-color);";
          wrapper.appendChild(label);
        }
        this.replaceChildren(wrapper);
      } else {
        this._img.alt = name;
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
    fatalError.hidden = false;
    fatalError.textContent = message;
    startupStatus.textContent = "Ошибка";
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
        detail = body.detail || detail;
      } catch (_) {
        // Keep the status fallback.
      }
      throw new Error(detail);
    }
    if (response.status === 204) {
      return null;
    }
    return response.json();
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

    await fetchJson("/api/auth/telegram", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({init_data: telegram.initData}),
    });
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
        const result = await fetchJson("/api/ha/button-press", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Comelit-MiniApp-Request": "1",
          },
          body: JSON.stringify({entity_id: data.entity_id}),
        });
        await refreshState();
        return result;
      },
    };
  }

  async function refreshState() {
    if (refreshInFlight) {
      return;
    }
    refreshInFlight = true;
    try {
      bootstrap = await fetchJson("/api/ha/bootstrap");
      if (!hass) {
        hass = buildHassAdapter();
      } else {
        hass.states = bootstrap.states || {};
      }
      card.hass = hass;
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
    bootstrap = await fetchJson("/api/ha/bootstrap");

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
