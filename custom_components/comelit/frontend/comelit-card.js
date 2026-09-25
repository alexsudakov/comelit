const CARD_TAG = "comelit-card";

const INTERCOM_UNIQUE_IDS = Object.freeze({
  entranceCamera: "comelit_entrance_camera",
  entranceMedia: "comelit_entrance_media_session",
  entranceDoor: "comelit_main_entrance_open_door",
  gateDoor: "comelit_main_gate_open_door",
  listenerStatus: "comelit_listener_status",
  callState: "comelit_call_state",
});

const CALL_STATE_LABELS = Object.freeze({
  idle: "Нет активного вызова",
  ringing: "Входящий вызов",
  answering: "Ответ",
  in_call: "Разговор",
  ending: "Завершение",
  error: "Ошибка вызова",
});

const ACTIVE_CALL_STATES = new Set([
  "ringing",
  "answering",
  "in_call",
  "ending",
]);

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
    this._registryLoaded = false;
    this._registryError = undefined;
    this._activeTab = "intercom";
    this._selectedCamera = undefined;
    this._viewerGeneration = 0;
    this._viewerElement = undefined;
    this._intercomViewerGeneration = 0;
    this._intercomViewerElement = undefined;
    this._intercomViewerOpen = false;
    this._selectedIntercomPanel = "entrance";
    this._doorActionInFlight = new Set();
    this._doorActionMessage = undefined;
    this._rendered = false;
    this._focusedCallEventId = undefined;
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
      this._maybeFocusIncomingCall();
      this._render();
      return;
    }

    if (this._maybeFocusIncomingCall()) {
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
    if (!this._hass || this._registryLoaded || this._registryPromise) {
      return this._registryPromise;
    }

    this._registryPromise = Promise.all([
      this._hass.callWS({ type: "config/entity_registry/list" }),
      this._hass.callWS({ type: "config/label_registry/list" }),
    ])
      .then(([entities, labels]) => {
        this._entityRegistry = Array.isArray(entities) ? entities : [];
        this._labelRegistry = Array.isArray(labels) ? labels : [];
        this._registryLoaded = true;
        this._registryError = undefined;
      })
      .catch((error) => {
        this._registryError =
          error instanceof Error ? error.message : "registry_unavailable";
      })
      .finally(() => {
        this._registryPromise = undefined;
        this._maybeFocusIncomingCall();
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
      callState: resolve("callState"),
    };
  }

  _callPresentation() {
    const model = this._intercomModel();
    const state = model.callState.state;
    const callState = state?.state || "unavailable";
    const panel = state?.attributes?.panel || null;
    const eventId = state?.attributes?.event_id || null;
    const active = ACTIVE_CALL_STATES.has(callState);

    return {
      state: callState,
      label: CALL_STATE_LABELS[callState] || callState,
      panel,
      eventId,
      active,
      mediaAttached: state?.attributes?.media_attached === true,
    };
  }

  _maybeFocusIncomingCall() {
    if (!this._registryLoaded || !this._hass) {
      return false;
    }

    const call = this._callPresentation();
    if (
      call.state !== "ringing" ||
      !call.eventId ||
      call.eventId === this._focusedCallEventId
    ) {
      return false;
    }

    this._focusedCallEventId = call.eventId;
    this._activeTab = "intercom";
    if (call.panel === "entrance" || call.panel === "gate") {
      if (this._selectedIntercomPanel !== call.panel) {
        this._intercomViewerOpen = false;
      }
      this._selectedIntercomPanel = call.panel;
    }
    return true;
  }

  _render() {
    if (!this.shadowRoot) {
      return;
    }

    this._viewerGeneration += 1;
    this._viewerElement = undefined;
    this._intercomViewerGeneration += 1;
    this._intercomViewerElement = undefined;

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

    const intercomContent = this._renderIntercom();
    const surveillanceContent = this._renderSurveillance(cameras);

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

        .tab-content[hidden] {
          display: none;
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
          transition: opacity 120ms ease, border-color 120ms ease;
        }

        .intercom-panel.active-call {
          border-color: var(--primary-color);
          box-shadow: inset 0 0 0 1px var(--primary-color);
        }

        .intercom-panel.call-locked {
          opacity: 0.48;
        }

        .call-banner {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: center;
          margin-bottom: 12px;
          padding: 10px 12px;
          border-radius: 12px;
          background: var(--secondary-background-color);
        }

        .call-banner.active {
          border: 1px solid var(--primary-color);
        }

        .call-panel-name {
          color: var(--secondary-text-color);
          font-size: 0.9rem;
        }

        .intercom-panel.selected-panel {
          border-color: var(--primary-color);
        }

        .panel-select {
          display: flex;
          width: 100%;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          border: 0;
          padding: 0;
          background: transparent;
          color: var(--primary-text-color);
          font: inherit;
          font-size: 1rem;
          font-weight: 600;
          text-align: left;
          cursor: pointer;
        }

        .panel-select:disabled {
          cursor: default;
        }

        .panel-status {
          color: var(--secondary-text-color);
          font-size: 0.82rem;
          font-weight: 400;
          text-align: right;
        }

        .door-action,
        .secondary-action {
          border: 0;
          border-radius: 10px;
          padding: 10px 14px;
          font: inherit;
          cursor: pointer;
        }

        .door-action {
          width: 100%;
          margin-top: 14px;
          background: var(--primary-color);
          color: var(--text-primary-color, white);
          font-weight: 600;
        }

        .secondary-action {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }

        .door-action:disabled,
        .secondary-action:disabled {
          opacity: 0.45;
          cursor: default;
        }

        .intercom-viewer-block {
          margin-top: 12px;
        }

        .viewer-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 8px;
        }

        #intercom-viewer {
          min-height: 120px;
        }

        .notice.compact {
          padding: 12px;
        }

        .action-message {
          margin-top: 12px;
          padding: 12px;
          border-radius: 10px;
          background: var(--secondary-background-color);
          color: var(--secondary-text-color);
        }

        .action-message:empty {
          display: none;
        }

        .runtime-status {
          margin-top: 12px;
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
        <div
          class="content tab-content"
          data-tab-panel="intercom"
          ${this._activeTab === "intercom" ? "" : "hidden"}
        >
          ${intercomContent}
        </div>
        <div
          class="content tab-content"
          data-tab-panel="surveillance"
          ${this._activeTab === "surveillance" ? "" : "hidden"}
        >
          ${surveillanceContent}
        </div>
      </ha-card>
    `;

    this._bindHandlers();
    this._rendered = true;

    if (
      this._selectedIntercomPanel === "entrance" &&
      this._intercomViewerOpen
    ) {
      this._mountIntercomViewer();
    }

    if (this._activeTab === "surveillance" && this._selectedCamera) {
      this._mountViewer(this._selectedCamera);
    }

    this._updateDynamicState();
  }

  _updateDynamicState() {
    if (!this._hass || !this.shadowRoot) {
      return;
    }

    if (this._viewerElement) {
      this._viewerElement.hass = this._hass;
    }
    if (this._intercomViewerElement) {
      this._intercomViewerElement.hass = this._hass;
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

    const model = this._intercomModel();
    const listener = this.shadowRoot.querySelector("[data-listener-state]");
    if (listener) {
      listener.textContent =
        model.listenerStatus.state?.state ||
        (model.listenerStatus.entry ? "unknown" : "entity unavailable");
    }

    const call = this._callPresentation();
    const callState = this.shadowRoot.querySelector("[data-call-state]");
    if (callState) {
      callState.textContent = call.label;
    }
    const callPanel = this.shadowRoot.querySelector("[data-call-panel]");
    if (callPanel) {
      callPanel.textContent = call.panel
        ? call.panel === "entrance"
          ? "Подъезд"
          : "Калитка"
        : "";
    }
    const callMedia = this.shadowRoot.querySelector("[data-call-media]");
    if (callMedia) {
      callMedia.textContent = call.mediaAttached ? "видео активно" : "";
    }

    for (const panel of this.shadowRoot.querySelectorAll("[data-intercom-panel]")) {
      const panelId = panel.dataset.intercomPanel;
      panel.classList.toggle(
        "active-call",
        call.active && call.panel === panelId,
      );
      panel.classList.toggle(
        "call-locked",
        call.active && call.panel && call.panel !== panelId,
      );
    }

    this._updateDoorActionUi(model, call);

    const cameraToggle = this.shadowRoot.querySelector(
      "[data-intercom-camera-toggle]",
    );
    if (cameraToggle) {
      const camera = this._cameraPresentation(model);
      cameraToggle.disabled = !camera.available;
      cameraToggle.textContent = this._intercomViewerOpen
        ? "Скрыть камеру"
        : "Показать камеру";
    }
  }

  _doorPresentation(panel, model, call) {
    const item = panel === "entrance" ? model.entranceDoor : model.gateDoor;
    const state = item.state;
    const lockedByCall =
      call.active && Boolean(call.panel) && call.panel !== panel;
    const inFlight = this._doorActionInFlight.has(panel);
    const pressAllowed =
      Boolean(state) &&
      state.state !== "unavailable" &&
      state.attributes?.standard_press_allowed === true;
    const blockedByMedia = state?.attributes?.blocked_by_media_session === true;

    let status = "Недоступно";
    if (inFlight) {
      status = "Отправка…";
    } else if (lockedByCall) {
      status = "Недоступно во время другого вызова";
    } else if (blockedByMedia) {
      status = "Недоступно во время отдельной media-сессии";
    } else if (pressAllowed) {
      status = "Доступно";
    }

    return {
      item,
      pressAllowed,
      lockedByCall,
      inFlight,
      disabled: !pressAllowed || lockedByCall || inFlight,
      status,
    };
  }

  _cameraPresentation(model) {
    const state = model.entranceCamera.state;
    return {
      entityId: model.entranceCamera.entry?.entity_id || null,
      available: Boolean(state) && state.state !== "unavailable",
    };
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
    const call = this._callPresentation();
    const listener =
      model.listenerStatus.state?.state ||
      (model.listenerStatus.entry ? "unknown" : "entity unavailable");
    const callPanelName = call.panel
      ? call.panel === "entrance"
        ? "Подъезд"
        : "Калитка"
      : "";

    if (call.active && (call.panel === "entrance" || call.panel === "gate")) {
      this._selectedIntercomPanel = call.panel;
    }

    const entranceSelected = this._selectedIntercomPanel === "entrance";
    const gateSelected = this._selectedIntercomPanel === "gate";
    const entranceLocked =
      call.active && Boolean(call.panel) && call.panel !== "entrance";
    const gateLocked =
      call.active && Boolean(call.panel) && call.panel !== "gate";

    const entranceDoor = this._doorPresentation("entrance", model, call);
    const gateDoor = this._doorPresentation("gate", model, call);
    const camera = this._cameraPresentation(model);

    const actionMessage = `
      <div
        data-door-action-message
        class="action-message ${this._doorActionMessage?.kind === "error" ? "error" : ""}"
      >${escapeHtml(this._doorActionMessage?.text || "")}</div>
    `;

    const selectedViewer = entranceSelected
      ? `
        <div class="intercom-viewer-block">
          <div class="viewer-toolbar">
            <strong>Камера подъезда</strong>
            <button
              class="secondary-action"
              data-intercom-camera-toggle
              ${camera.available ? "" : "disabled"}
            >${this._intercomViewerOpen ? "Скрыть камеру" : "Показать камеру"}</button>
          </div>
          ${camera.available
            ? this._intercomViewerOpen
              ? '<div id="intercom-viewer"></div>'
              : '<div class="notice compact">Видео запускается только после нажатия «Показать камеру».</div>'
            : '<div class="notice compact">Камера подъезда сейчас недоступна.</div>'}
        </div>
      `
      : `
        <div class="intercom-viewer-block">
          <div class="viewer-toolbar">
            <strong>Камера калитки</strong>
          </div>
          <div class="notice compact">
            Отдельная камера калитки пока не опубликована интеграцией.
          </div>
        </div>
      `;

    return `
      <div class="call-banner ${call.active ? "active" : ""}">
        <strong data-call-state>${escapeHtml(call.label)}</strong>
        <span class="call-panel-name">
          <span data-call-panel>${escapeHtml(callPanelName)}</span>
          <span data-call-media>${call.mediaAttached ? " · видео активно" : ""}</span>
        </span>
      </div>

      <div class="intercom-grid">
        <section
          class="intercom-panel ${entranceSelected ? "selected-panel" : ""} ${call.active && call.panel === "entrance" ? "active-call" : ""} ${entranceLocked ? "call-locked" : ""}"
          data-intercom-panel="entrance"
        >
          <button
            class="panel-select"
            data-intercom-select="entrance"
            ${entranceLocked ? "disabled" : ""}
          >
            <span>Подъезд</span>
            <span class="panel-status">${escapeHtml(entranceDoor.status)}</span>
          </button>
          <button
            class="door-action"
            data-door-action="entrance"
            ${entranceDoor.disabled ? "disabled" : ""}
          >Открыть подъезд</button>
        </section>

        <section
          class="intercom-panel ${gateSelected ? "selected-panel" : ""} ${call.active && call.panel === "gate" ? "active-call" : ""} ${gateLocked ? "call-locked" : ""}"
          data-intercom-panel="gate"
        >
          <button
            class="panel-select"
            data-intercom-select="gate"
            ${gateLocked ? "disabled" : ""}
          >
            <span>Калитка</span>
            <span class="panel-status">${escapeHtml(gateDoor.status)}</span>
          </button>
          <button
            class="door-action"
            data-door-action="gate"
            ${gateDoor.disabled ? "disabled" : ""}
          >Открыть калитку</button>
        </section>
      </div>

      ${selectedViewer}
      ${actionMessage}

      <div class="meta runtime-status">
        Listener: <span data-listener-state>${escapeHtml(listener)}</span>
      </div>
    `;
  }

  _bindHandlers() {
    for (const button of this.shadowRoot.querySelectorAll("[data-tab]")) {
      button.addEventListener("click", () => {
        this._setActiveTab(button.dataset.tab);
      });
    }

    for (const button of this.shadowRoot.querySelectorAll("[data-camera]")) {
      button.addEventListener("click", () => {
        const entityId = button.dataset.camera;
        if (!entityId || entityId === this._selectedCamera) {
          return;
        }

        this._selectedCamera = entityId;
        for (const candidate of this.shadowRoot.querySelectorAll("[data-camera]")) {
          candidate.classList.toggle(
            "selected",
            candidate.dataset.camera === entityId,
          );
        }

        this._viewerGeneration += 1;
        this._viewerElement = undefined;
        const target = this.shadowRoot.querySelector("#viewer");
        if (target) {
          target.replaceChildren();
        }

        if (this._activeTab === "surveillance") {
          this._mountViewer(entityId);
        }
      });
    }

    for (const button of this.shadowRoot.querySelectorAll("[data-intercom-select]")) {
      button.addEventListener("click", () => {
        const panel = button.dataset.intercomSelect;
        const call = this._callPresentation();
        if (
          panel !== "entrance" &&
          panel !== "gate"
        ) {
          return;
        }
        if (call.active && call.panel && call.panel !== panel) {
          return;
        }
        if (panel !== this._selectedIntercomPanel) {
          this._intercomViewerOpen = false;
        }
        this._selectedIntercomPanel = panel;
        this._doorActionMessage = undefined;
        this._render();
      });
    }

    const cameraToggle = this.shadowRoot.querySelector(
      "[data-intercom-camera-toggle]",
    );
    if (cameraToggle) {
      cameraToggle.addEventListener("click", () => {
        const model = this._intercomModel();
        const camera = this._cameraPresentation(model);
        if (!camera.available || this._selectedIntercomPanel !== "entrance") {
          return;
        }
        this._intercomViewerOpen = !this._intercomViewerOpen;
        this._render();
      });
    }

    for (const button of this.shadowRoot.querySelectorAll("[data-door-action]")) {
      button.addEventListener("click", () => {
        this._pressDoor(button.dataset.doorAction);
      });
    }
  }

  _setActiveTab(nextTab) {
    if (
      (nextTab !== "intercom" && nextTab !== "surveillance") ||
      nextTab === this._activeTab
    ) {
      return;
    }

    this._activeTab = nextTab;

    for (const button of this.shadowRoot.querySelectorAll("[data-tab]")) {
      button.classList.toggle("active", button.dataset.tab === nextTab);
    }

    for (const panel of this.shadowRoot.querySelectorAll("[data-tab-panel]")) {
      panel.hidden = panel.dataset.tabPanel !== nextTab;
    }

    if (nextTab === "surveillance") {
      // Keep the explicitly opened intercom viewer connected to the DOM.
      // This preserves its HA camera-view lease while the user inspects
      // ordinary surveillance cameras.
      if (this._selectedCamera && !this._viewerElement) {
        this._mountViewer(this._selectedCamera);
      }
    } else {
      // Ordinary surveillance viewing is not persistent. Release the hidden
      // surveillance viewer when leaving its tab so it does not keep an RTSP
      // stream alive in the background.
      this._viewerGeneration += 1;
      this._viewerElement = undefined;
      const target = this.shadowRoot.querySelector("#viewer");
      if (target) {
        target.replaceChildren();
      }

      if (
        this._intercomViewerOpen &&
        this._selectedIntercomPanel === "entrance" &&
        !this._intercomViewerElement
      ) {
        this._mountIntercomViewer();
      }
    }

    this._updateDynamicState();
  }

  async _pressDoor(panel) {
    if (!this._hass || (panel !== "entrance" && panel !== "gate")) {
      return;
    }

    const model = this._intercomModel();
    const call = this._callPresentation();
    const door = this._doorPresentation(panel, model, call);
    const entityId = door.item.entry?.entity_id;

    if (door.disabled || !entityId) {
      this._doorActionMessage = {
        kind: "error",
        text: "Открытие сейчас недоступно.",
      };
      this._updateDynamicState();
      return;
    }

    this._doorActionInFlight.add(panel);
    this._doorActionMessage = undefined;
    this._updateDynamicState();

    try {
      // One explicit user press maps to exactly one semantic HA button press.
      // No automatic retry is allowed here.
      await this._hass.callService("button", "press", {
        entity_id: entityId,
      });
      this._doorActionMessage = {
        kind: "info",
        text:
          panel === "entrance"
            ? "Команда открытия подъезда отправлена. Физическое открытие не подтверждается интеграцией."
            : "Команда открытия калитки отправлена. Физическое открытие не подтверждается интеграцией.",
      };
    } catch (error) {
      this._doorActionMessage = {
        kind: "error",
        text: `Команда не выполнена: ${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    } finally {
      this._doorActionInFlight.delete(panel);
      this._updateDynamicState();
    }
  }

  _updateDoorActionUi(model, call) {
    for (const button of this.shadowRoot.querySelectorAll("[data-door-action]")) {
      const panel = button.dataset.doorAction;
      if (panel !== "entrance" && panel !== "gate") {
        continue;
      }
      const door = this._doorPresentation(panel, model, call);
      button.disabled = door.disabled;
      button.textContent =
        door.inFlight
          ? "Отправка…"
          : panel === "entrance"
            ? "Открыть подъезд"
            : "Открыть калитку";

      const panelRoot = this.shadowRoot.querySelector(
        `[data-intercom-panel="${panel}"]`,
      );
      const status = panelRoot?.querySelector(".panel-status");
      if (status) {
        status.textContent = door.status;
      }
    }

    const message = this.shadowRoot.querySelector("[data-door-action-message]");
    if (message) {
      message.textContent = this._doorActionMessage?.text || "";
      message.classList.toggle(
        "error",
        this._doorActionMessage?.kind === "error",
      );
    }
  }

  async _mountIntercomViewer() {
    const target = this.shadowRoot?.querySelector("#intercom-viewer");
    if (
      !target ||
      !this._hass ||
      !this._intercomViewerOpen ||
      this._selectedIntercomPanel !== "entrance"
    ) {
      return;
    }

    const model = this._intercomModel();
    const camera = this._cameraPresentation(model);
    if (!camera.entityId || !camera.available) {
      target.innerHTML = '<div class="notice compact">Камера подъезда недоступна.</div>';
      return;
    }

    const generation = ++this._intercomViewerGeneration;
    target.innerHTML = '<div class="notice compact">Подключение камеры подъезда…</div>';

    try {
      if (typeof window.loadCardHelpers !== "function") {
        throw new Error("loadCardHelpers unavailable");
      }

      const helpers = await window.loadCardHelpers();
      const viewer = await helpers.createCardElement({
        type: "picture-entity",
        entity: camera.entityId,
        camera_view: "live",
        show_name: false,
        show_state: false,
      });

      if (
        generation !== this._intercomViewerGeneration ||
        !this._intercomViewerOpen ||
        this._selectedIntercomPanel !== "entrance"
      ) {
        return;
      }

      viewer.hass = this._hass;
      this._intercomViewerElement = viewer;
      const currentTarget = this.shadowRoot?.querySelector("#intercom-viewer");
      if (currentTarget) {
        currentTarget.replaceChildren(viewer);
      }
    } catch (error) {
      if (generation !== this._intercomViewerGeneration) {
        return;
      }
      const currentTarget = this.shadowRoot?.querySelector("#intercom-viewer");
      if (currentTarget) {
        currentTarget.innerHTML = `
          <div class="notice compact error">
            Не удалось открыть камеру подъезда:
            ${escapeHtml(error instanceof Error ? error.message : error)}
          </div>
        `;
      }
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
