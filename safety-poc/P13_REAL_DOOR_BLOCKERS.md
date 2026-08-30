# P13 first-real-door functional blockers

Scope: fix only defects that directly prevent the first real operator-approved Door-open on CT120. Do not add provenance, release, HA, packaging, or other post-PoC hardening.

## B1 — payload identity uses different byte representation

Current `p13_holder_transform.py` computes `P13_EXPECTED_PAYLOAD_SHA256` from a canonicalized in-memory JSON representation:

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"))
```

But the generated C holder validates at runtime by hashing the raw bytes of `/root/comelit-p13-actuator-prep/real-door-payloads.json`.

`prepare_p13_real_payloads.py` writes that file with `indent=2`, `sort_keys=True`, `ensure_ascii=False` and a trailing newline, so the two byte sequences are not equal. The live holder will therefore fail with `P13_PAYLOAD_IDENTITY=FAIL` before the CTPP Door transaction.

Required fix:

- embed the SHA-256 of the exact raw payload file bytes that the holder will validate at runtime, or make both producer and validator use the same unambiguous byte representation;
- preserve exactly-six-write and target binding checks;
- add a regression test using the exact serialization from `prepare_p13_real_payloads.py` and prove generated holder expected SHA == SHA of the written file bytes.

Do not weaken payload identity checking.

## B2 — operation_id is not propagated to the real wrapper

`p13_wrapper_template.sh` requires:

```bash
OPERATION_ID="${P13_OPERATION_ID:-}"
[[ -n "$OPERATION_ID" ]] || exit 2
```

but `Ct120RealP13Session._run_wrapper_once()` invokes the wrapper without adding `P13_OPERATION_ID` to its subprocess environment. `p13_one_shot_physical.py` also does not export it.

Therefore the real wrapper will exit before invoking the holder/network path even after operator approval.

Required fix:

- bind the exact `operation_id` used by `OneShotExecutor` to the single real wrapper invocation;
- pass it explicitly into `Ct120RealP13Session` and then into the wrapper subprocess environment (preferred), rather than relying on ambient mutable state;
- verify the wrapper receives exactly that operation ID;
- duplicate operation IDs must still never invoke the wrapper twice;
- add an integration test with a fake wrapper that fails unless `P13_OPERATION_ID` equals the requested operation ID.

## Required validation

After B1+B2 only:

- full repository tests green;
- static safety scan green;
- shell parse / py_compile green;
- PR CI green;
- no Comelit network call and no physical Door action during corrective validation.

Then return one exact root command for CT120:

1. exact-sync feature branch;
2. install P13 runtime holder/wrapper;
3. run non-actuating preflight;
4. stop before physical runner.

No new blocker may be introduced unless it directly prevents or makes unsafe the first physical Door-open attempt.

Physical approval has not been granted.