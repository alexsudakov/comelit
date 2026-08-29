# CT120 public-safe evidence collection

`./scripts/collect_plan_evidence.sh` is a read-only project evidence collector plus a Git commit/push wrapper.

## What it collects

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

## What it explicitly does not collect

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

The collector requires a clean named branch. It creates a timestamped branch:

`evidence/ct120-YYYYMMDDTHHMMSSZ`

and writes reports under:

`evidence/ct120/YYYYMMDDTHHMMSSZ/`

Before commit it performs a high-risk credential-pattern scan, a safety-marker scan, `git diff --cached --check`, and a scope check proving only the evidence directory is staged. It then commits and pushes that branch using the already configured Git credential helper, prints the evidence commit, and switches back to the original branch.

## Trust model

The evidence branch is source data, not an acceptance verdict. Repository code may parse it, but runtime gates remain fail-closed unless the exact required markers are independently produced by the relevant fixture/read-only verification scripts.
