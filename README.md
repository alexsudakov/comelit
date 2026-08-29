# Comelit

Repository for the Comelit ViP integration research and safety PoC.

Current deployment target: CT120.

Canonical implementation source lives under [`safety-poc/`](safety-poc/). Historical v0.5 bootstrap transport artifacts remain under `artifacts/v0.5/` for reproducibility only; future development and deployment are Git-native.

The v0.6 development branch adds a public-safe CT120 evidence collector, payload-redacted CTPP body modeling, offline CTPP/full-transaction models, explicit readiness gates, and a Home Assistant service contract.

Safety rule: real Door transport remains disabled until the offline/runtime gates are complete and a separate explicit controlled live-test gate is approved. Protocol acknowledgement is never treated as proof that the physical relay moved.
