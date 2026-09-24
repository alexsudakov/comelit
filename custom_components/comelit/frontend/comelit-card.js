const CARD_TAG = "comelit-card";

const INTERCOM_UNIQUE_IDS = Object.freeze({
  entranceCamera: "comelit_entrance_camera",
  entranceMedia: "comelit_entrance_media_session",
  entranceDoor: "comelit_main_entrance_open_door",
  gateDoor: "comelit_main_gate_open_door",
  listenerStatus: "comelit_listener_status",
});

const INTERCOM_CAMERA_UNIQUE_IDS = new Set([
  INTERCOM_UNIQUE_IDS.entranceCamera,
  "comelit_gate_camera",
]);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function domainOf(entityId) {
  return String(entityId || "").split(".", 1)[0];
}

class ComelitCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._entityRegistry = [];
    this._labelRegistry = [];
    this._registryPromise = undefined;
    this._registryError = undefined;
    this._activeTab = "intercom";
    this._selectedCamera = undefined;
    this._viewerGeneration = 0;
    this._viewerElement = undefined;
    this._rendered = false;
  }

  static getStubConfig() {
    return {
      default_tab: "intercom",
      surveillance: {
        include: [],
        exclude: [],
      },
    };
  }

  setConfig(config) {
    if (!config || typeof config !== "object") {
      throw new Error("Comelit card configuration is required");
    }

    const defaultTab =
      config.default_tab === "surveillance" ? "surveillance" : "intercom";

    this._config = {
      ...config,
      surveillance: {
        ...(config.surveillance || {}),
        include: Array.isArray(config.surveillance?.include)
          ? config.surveillance.include
          : [],
        exclude: Array.isArray(config.surveillance?.exclude)
          ? config.surveillance.exclude
          : [],
      },
    };

    this._activeTab = defaultTab;
    this._selectedCamera = undefined;
    this._render();
  }

  set hass(hass) {
    const firstHass = !this._hass;
    this._hass = hass;
    this._loadRegistries();

    if (firstHass || !this._rendered) {
      this._render();
      return;
    }

    this._updateDynamicState();
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return {
      columns: 12,
      min_columns: 6,
    };
  }

  async _loadRegistries() {
    if (!this._hass || this._registryPromise) {
      return this._registryPromise;
    }

    this._registryPromise = Promise.all([
      this._hass.callWS({ type: "config/entity_registry/list" }),
      this._hass.callWS({ type: "config/label_registry/list" }),
    ])
      .then(([entities, labels]) => {
        this._entityRegistry = Array.isArray(entities) ? entities : [];
        this._labelRegistry = Array.isArray(labels) ? labels : [];
        this._registryError = undefined;
      })
      .catch((error) => {
        this._registryError =
          error instanceof Error ? error.message : "registry_unavailable";
      })
      .finally(() => {
        this._render();
      });

    return this._registryPromise;
  }

  _resolveLabelId() {
    const requested = this._config.surveillance?.label;
    if (!requested) {
      return undefined;
    }

    const direct = this._labelRegistry.find(
      (entry) => entry.label_id === requested,
    );
    if (direct) {
      return direct.label_id;
    }

    const normalized = String(requested).trim().toLocaleLowerCase();
    const byName = this._labelRegistry.find(
      (entry) =>
        String(entry.name || "")
          .trim()
          .toLocaleLowerCase() === normalized,
    );
    return byName?.label_id || String(requested);
  }

  _entryForEntity(entityId) {
    return this._entityRegistry.find((entry) => entry.entity_id === entityId);
  }

  _resolveByUniqueId(uniqueId) {
    return this._entityRegistry.find(
      (entry) => entry.platform === "comelit" && entry.unique_id === uniqueId,
    );
  }

  _isIntercomCameraEntry(entry) {
    return (
      entry?.platform === "comelit" &&
      INTERCOM_CAMERA_UNIQUE_IDS.has(entry.unique_id)
    );
  }

  _surveillanceEntities() {
    const surveillance = this._config.surveillance || {};
    const labelId = this._resolveLabelId();
    const include = surveillance.include || [];
    const exclude = new Set(surveillance.exclude || []);
    const ids = new Set();

    if (labelId) {
      for (const entry of this._entityRegistry) {
        if (
          domainOf(entry.entity_id) === "camera" &&
          Array.isArray(entry.labels) &&
          entry.labels.includes(labelId)
        ) {
          ids.add(entry.entity_id);
        }
      }
    }

    for (const entityId of include) {
      if (domainOf(entityId) === "camera") {
        ids.add(entityId);
      }
    }

    const result = [];
    for (const entityId of ids) {
      if (exclude.has(entityId)) {
        continue;
      }

      const entry = this._entryForEntity(entityId);
      if (this._isIntercomCameraEntry(entry)) {
        continue;
      }

      const state = this._hass?.states?.[entityId];
      const name =
        state?.attributes?.friendly_name ||
        entry?.name ||
        entry?.original_name ||
        entityId;

      result.push({
        entityId,
        name,
        state: state?.state || "unavailable",
        available: Boolean(state) && state.state !== "unavailable",
      });
    }

    result.sort((left, right) =>
      String(left.name).localeCompare(String(right.name), undefined, {
        sensitivity: "base",
      }),
    );

    return result;
  }

  _intercomModel() {
    const resolve = (key) => {
      const entry = this._resolveByUniqueId(INTERCOM_UNIQUE_IDS[key]);
      const state = entry ? this._hass?.states?.[entry.entity_id] : undefined;
      return {
        entry,
        state,
      };
    };

    return {
      entranceCamera: resolve("entranceCamera"),
      entranceMedia: resolve("entranceMedia"),
      entranceDoor: resolve("entranceDoor"),
      gateDoor: resolve("gateDoor"),
      listenerStatus: resolve("listenerStatus"),
    };
  }

  _render() {
    if (!this.shadowRoot) {
      return;
    }

    this._viewerGeneration += 1;
    this._viewerElement = undefined;

    const cameras = this._hass ? this._surveillanceEntities() : [];
    if (
      this._selectedCamera &&
      !cameras.some((camera) => camera.entityId === this._selectedCamera)
    ) {
      this._selectedCamera = undefined;
    }
    if (!this._selectedCamera && cameras.length > 0) {
      this._selectedCamera = cameras[0].entityId;
    }

    const content =
      this._activeTab === "surveillance"
        ? this._renderSurveillance(cameras)
        : this._renderIntercom();

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          --comelit-gap: 12px;
        }

        ha-card {
          overflow: hidden;
          padding: 0;
        }

        .tabs {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 4px;
          padding: 8px;
          border-bottom: 1px solid var(--divider-color);
        }

        .tab {
          border: 0;
          border-radius: 10px;
          padding: 10px 12px;
          background: transparent;
          color: var(--primary-text-color);
          font: inherit;
          cursor: pointer;
        }

        .tab.active {
          background: var(--secondary-background-color);
          color: var(--primary-color);
          font-weight: 600;
        }

        .content {
          padding: 12px;
        }

        .notice {
          padding: 18px;
          border-radius: 12px;
          background: var(--secondary-background-color);
          color: var(--secondary-text-color);
        }

        .error {
          color: var(--error-color);
        }

        .camera-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 8px;
          margin-bottom: 12px;
        }

        .camera-choice {
          display: flex;
          align-items: center;
          gap: 8px;
          min-height: 48px;
          padding: 8px 10px;
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font: inherit;
          text-align: left;
          cursor: pointer;
        }

        .camera-choice.selected {
          border-color: var(--primary-color);
          box-shadow: inset 0 0 0 1px var(--primary-color);
        }

        .status-dot {
          width: 9px;
          height: 9px;
          flex: 0 0 9px;
          border-radius: 50%;
          background: var(--success-color, #43a047);
        }

        .status-dot.unavailable {
          background: var(--disabled-text-color);
        }

        .camera-name {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        #viewer {
          min-height: 120px;
        }

        .intercom-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: var(--comelit-gap);
        }

        .intercom-panel {
          padding: 14px;
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          background: var(--card-background-color);
        }

        .intercom-panel h3 {
          margin: 0 0 8px 0;
          font-size: 1rem;
        }

        .meta {
          margin-top: 6px;
          color: var(--secondary-text-color);
          font-size: 0.9rem;
        }
      </style>

      <ha-card>
        <div class="tabs">
          <button
            class="tab ${this._activeTab === "intercom" ? "active" : ""}"
            data-tab="intercom"
          >Домофон</button>
          <button
            class="tab ${this._activeTab === "surveillance" ? "active" : ""}"
            data-tab="surveillance"
          >Видеонаблюдение</button>
        </div>
        <div class="content">
          ${content}
        </div>
      </ha-card>
    `;

    this._bindHandlers();
    this._rendered = true;

    if (this._activeTab === "surveillance" && this._selectedCamera) {
      this._mountViewer(this._selectedCamera);
    } else {
      this._updateDynamicState();
    }
  }

  _updateDynamicState() {
    if (!this._hass || !this.shadowRoot) {
      return;
    }

    if (this._viewerElement) {
      this._viewerElement.hass = this._hass;
    }

    for (const button of this.shadowRoot.querySelectorAll("[data-camera]")) {
      const entityId = button.dataset.camera;
      const state = entityId ? this._hass.states?.[entityId] : undefined;
      const dot = button.querySelector(".status-dot");
      if (dot) {
        dot.classList.toggle(
          "unavailable",
          !state || state.state === "unavailable",
        );
      }
    }

    const listener = this.shadowRoot.querySelector("[data-listener-state]");
    if (listener) {
      const model = this._intercomModel();
      listener.textContent =
        model.listenerStatus.state?.state ||
        (model.listenerStatus.entry ? "unknown" : "entity unavailable");
    }

    for (const button of this.shadowRoot.querySelectorAll("[data-door]")) {
      const model = this._intercomModel();
      const item =
        button.dataset.door === "entrance"
          ? model.entranceDoor
          : model.gateDoor;
      button.textContent = item.state
        ? item.state.state === "unavailable"
          ? "недоступно"
          : "доступно"
        : "entity unavailable";
    }
  }

  _renderSurveillance(cameras) {
    if (this._registryError) {
      return `
        <div class="notice error">
          Не удалось прочитать Home Assistant registry:
          ${escapeHtml(this._registryError)}
        </div>
      `;
    }

    if (!this._config.surveillance?.label &&
        (this._config.surveillance?.include || []).length === 0) {
      return `
        <div class="notice">
          Укажите surveillance.label или surveillance.include.
          Карточка намеренно не показывает все камеры Home Assistant автоматически.
        </div>
      `;
    }

    if (cameras.length === 0) {
      return `
        <div class="notice">
          В выбранном наборе пока нет камер.
        </div>
      `;
    }

    const choices = cameras
      .map(
        (camera) => `
          <button
            class="camera-choice ${camera.entityId === this._selectedCamera ? "selected" : ""}"
            data-camera="${escapeHtml(camera.entityId)}"
          >
            <span class="status-dot ${camera.available ? "" : "unavailable"}"></span>
            <span class="camera-name">${escapeHtml(camera.name)}</span>
          </button>
        `,
      )
      .join("");

    return `
      <div class="camera-grid">${choices}</div>
      <div id="viewer"></div>
    `;
  }

  _renderIntercom() {
    if (!this._hass) {
      return '<div class="notice">Ожидание Home Assistant…</div>';
    }

    const model = this._intercomModel();
    const listener =
      model.listenerStatus.state?.state ||
      (model.listenerStatus.entry ? "unknown" : "entity unavailable");

    const entranceCamera = model.entranceCamera.entry
      ? model.entranceCamera.entry.entity_id
      : "камера недоступна";

    const entranceDoor = model.entranceDoor.state
      ? model.entranceDoor.state.state === "unavailable"
        ? "недоступно"
        : "доступно"
      : "entity unavailable";

    const gateDoor = model.gateDoor.state
      ? model.gateDoor.state.state === "unavailable"
        ? "недоступно"
        : "доступно"
      : "entity unavailable";

    return `
      <div class="intercom-grid">
        <div class="intercom-panel">
          <h3>Подъезд</h3>
          <div class="meta">Камера: ${escapeHtml(entranceCamera)}</div>
          <div class="meta">Открытие: <span data-door="entrance">${escapeHtml(entranceDoor)}</span></div>
        </div>
        <div class="intercom-panel">
          <h3>Калитка</h3>
          <div class="meta">Камера: пока не опубликована интеграцией</div>
          <div class="meta">Открытие: <span data-door="gate">${escapeHtml(gateDoor)}</span></div>
        </div>
      </div>
      <div class="meta">Listener: <span data-listener-state>${escapeHtml(listener)}</span></div>
      <div class="notice" style="margin-top: 12px">
        На этом MVP вкладка «Домофон» только отображает состояние.
        Media/Door actions и call routing будут добавлены отдельным этапом.
      </div>
    `;
  }

  _bindHandlers() {
    for (const button of this.shadowRoot.querySelectorAll("[data-tab]")) {
      button.addEventListener("click", () => {
        this._activeTab = button.dataset.tab;
        this._render();
      });
    }

    for (const button of this.shadowRoot.querySelectorAll("[data-camera]")) {
      button.addEventListener("click", () => {
        this._selectedCamera = button.dataset.camera;
        this._render();
      });
    }
  }

  async _mountViewer(entityId) {
    const target = this.shadowRoot?.querySelector("#viewer");
    if (!target || !this._hass) {
      return;
    }

    const generation = ++this._viewerGeneration;
    target.innerHTML = '<div class="notice">Подключение камеры…</div>';

    try {
      if (typeof window.loadCardHelpers !== "function") {
        throw new Error("loadCardHelpers unavailable");
      }

      const helpers = await window.loadCardHelpers();
      const viewer = await helpers.createCardElement({
        type: "picture-entity",
        entity: entityId,
        camera_view: "live",
        show_name: true,
        show_state: false,
      });

      if (
        generation !== this._viewerGeneration ||
        this._selectedCamera !== entityId ||
        this._activeTab !== "surveillance"
      ) {
        return;
      }

      viewer.hass = this._hass;
      this._viewerElement = viewer;
      const currentTarget = this.shadowRoot?.querySelector("#viewer");
      if (!currentTarget) {
        return;
      }
      currentTarget.replaceChildren(viewer);
    } catch (error) {
      if (generation !== this._viewerGeneration) {
        return;
      }
      const currentTarget = this.shadowRoot?.querySelector("#viewer");
      if (currentTarget) {
        currentTarget.innerHTML = `
          <div class="notice error">
            Не удалось создать стандартный HA camera viewer:
            ${escapeHtml(error instanceof Error ? error.message : error)}
          </div>
        `;
      }
    }
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, ComelitCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((entry) => entry.type === "comelit-card")) {
  window.customCards.push({
    type: "comelit-card",
    name: "Comelit",
    description: "Домофон и стандартные Home Assistant камеры видеонаблюдения",
    preview: false,
  });
}
