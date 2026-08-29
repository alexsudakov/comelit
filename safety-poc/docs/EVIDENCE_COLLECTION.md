# CT120 public-safe evidence collection

`./scripts/collect_plan_evidence.sh` is the baseline read-only project evidence collector plus a Git commit/push wrapper.

## Baseline collection

It collects:

- Git source branch and exact source commit;
- toolchain/host capacity metadata;
- currently promoted safety-PoC release identity/version metadata;
- SHA256 identities for legacy/canonical Python source files;
- artifact names and sizes for APK/pcap files, without packet/file contents;
- operator wrapper modes and SHA256 identities;
- existence/mode of the Comelit secret directory, without listing or reading its contents;
- passive network shape: interface names/states, socket protocol/state/ports, default-route count; IP and MAC addresses are omitted;
- Python package versions;
- public-safe AST topology for pinned core sources;
- payload-redacted Door body shape inventory;
- symbol locations across the legacy/canonical source trees.

## Evidence v1 correction

The first collected bundle, commit `153e1864d947e9ff0a5386f2d60b4b87d117c239`, remains valid for source identities, runtime release, operator boundary, toolchain, artifact metadata and passive network shape.

Its `legacy_body_shape_inventory.txt` is **not valid for a P6 body-layout verdict**. The original inventory selected a function by unqualified leaf name, and the legacy source contains both:

- `IconaBridgeClient.open_door`;
- a top-level `open_door` wrapper.

The unqualified selector chose the top-level wrapper. Repository review detected this before deploy or live testing.

## Corrected supplemental collection

`./scripts/collect_plan_evidence_v2.sh` is the required correction/supplement. It:

- pins the source branch/head again;
- records `EVIDENCE_SCHEMA=2`;
- records `CORRECTS_EVIDENCE_COMMIT=153e1864d947e9ff0a5386f2d60b4b87d117c239`;
- requires qualified class-method selection for `IconaBridgeClient._open_door_init` and `IconaBridgeClient.open_door`;
- expands statically recoverable starred body-component lists without emitting literal values;
- records the actual outer-method write/read/open/close/wait call counts and write argument shapes;
- inventories the pinned canonical `VipChannelSession`/`VipSession` control-plane method API and call shapes;
- inventories canonical control-codec dataclass fields without default literal values;
- records selected fixture-test call shapes from `test_channel_session.py`, `test_vip_session.py`, and `test_application_session.py`;
- records the complete canonical Python file tree as path/size/SHA256 metadata only;
- repeats runtime release and operator-wrapper identities.

The corrected collector creates `evidence/ct120-v2-<timestamp>` and writes under `evidence/ct120-v2/<timestamp>/`.

## What collectors explicitly do not collect

- environment variables;
- Git credential-file contents;
- Comelit secret-file names or values;
- OAuth/ViP tokens or other credentials;
- real Door payload literal values;
- packet contents from captures;
- IP addresses or MAC addresses;
- shell command lines of running processes;
- active Comelit connectivity probes;
- any Door/open/unlock action.

## Git behavior

Collectors require a clean named branch, create a timestamped evidence branch, run credential/safety scans plus `git diff --cached --check`, commit only their evidence directory, push it, and return to the original branch.

## Trust model

Evidence branches are source data, not acceptance verdicts. Repository code may parse them, but runtime gates remain fail-closed unless the exact required markers are independently produced by the relevant fixture/read-only verification scripts.

In particular:

- v1 body inventory must not be used for `CTPP_BODY_LAYOUT_RECONCILIATION=PASS`;
- v2 structural evidence still cannot prove byte-exact Door body equivalence by itself;
- no evidence collection authorizes live transport or a physical Door action.
