// Chain harness: Mini App projection -> host.js adapter -> Comelit Card gate.
//
// The card source is the production file; the adapter mirrors host.js
// buildHassAdapter() (pinned by test_miniapp_projection_gate.py); the model and
// the gate come from the card's own _intercomModel() / _cameraPresentation() /
// _intercomChannelBusyLabel() -- the same functions the render and the click
// guard consume.  Rendering itself is out of scope here (DOM stubs match the
// existing contract harness).
const fs = require("fs");

class HTMLElementStub {
  attachShadow() {
    return {
      innerHTML: "",
      querySelector() {
        return null;
      },
      querySelectorAll() {
        return [];
      },
      appendChild() {},
      replaceChildren() {},
    };
  }
}
globalThis.HTMLElement = HTMLElementStub;
globalThis.customElements = {
  define() {},
  get() {
    return undefined;
  },
};
globalThis.document = {
  createElement() {
    return {};
  },
};
globalThis.window = { customCards: [] };

const src =
  fs.readFileSync(process.argv[2], "utf8") + "\nglobalThis.__Card = ComelitCard;";
(0, eval)(src);

const fixture = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

function adapterFor(payload) {
  return {
    states: payload.states || {},
    callWS: async (message) => {
      if (message?.type === "config/entity_registry/list") {
        return payload.entity_registry || [];
      }
      if (message?.type === "config/label_registry/list") {
        return payload.label_registry || [];
      }
      throw new Error("Unsupported Mini App callWS: " + String(message?.type));
    },
    callService: async () => {
      throw new Error("unexpected service call");
    },
  };
}

function readGate(card) {
  const model = card._intercomModel();
  const camera = card._cameraPresentation(model);
  const label = card._intercomChannelBusyLabel(model);
  const text =
    label !== null
      ? label
      : card._intercomViewerMode === "ended"
        ? "Открыть камеру заново"
        : card._intercomViewerOpen
          ? "Скрыть камеру"
          : "Показать камеру";
  return {
    channelState: camera.channelState,
    channelPhase: camera.channelPhase,
    available: camera.available,
    label,
    text,
    disabled: !camera.available || label !== null,
  };
}

async function main() {
  const out = [];
  for (const testCase of fixture.cases) {
    const card = new globalThis.__Card();
    card._intercomViewerMode = "webcodecs";
    card._intercomViewerOpen = false;
    // DOM-only side effects: the gate predicates under test do not touch them.
    card._render = () => {};
    card._maybeFocusIncomingCall = () => {};
    card._hass = adapterFor(testCase.bootstrap);
    await card._loadRegistries();
    const before = readGate(card);
    // Periodic /state refresh, applied the way host.js applies it.
    card._hass = adapterFor({
      ...testCase.bootstrap,
      states: testCase.state.states,
    });
    const after = readGate(card);
    out.push({
      name: testCase.name,
      before,
      after,
      registryError: card._registryError ?? null,
      viewerOpen: card._intercomViewerOpen === true,
      viewerMode: card._intercomViewerMode,
    });
  }
  process.stdout.write(JSON.stringify(out));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
