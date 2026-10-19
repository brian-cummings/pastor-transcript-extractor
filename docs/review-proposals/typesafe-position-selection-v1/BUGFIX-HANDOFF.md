# Source-proof lookup repair

The stopped attempt completed 20 paid requests (529,118 input tokens; $0.022222956 list price). It then passed a source-proof fingerprint string into a validator expecting the full sealed object. This was a local implementation bug. The regression now exercises a positive nomination with the real persisted binding shape, rather than only withholding paths.

Brian authorized fixing the bug and running again. [The versioned repair decision](execution-repair-v1.json) binds the unchanged input, original bounds, all 20 receipts and corrected code. The same command now replays those verified responses, resolves their sealed proofs and sends only the previously unsent tail: **at most 10 new requests, at most 30 total**. It preserves the original stop, responses and attempt lock. No completed or uncertain send can be resubmitted. A separate persistent continuation lock prevents another automatic attempt after interruption.

```bash
pte analysis structure-readiness --typesafe-selection --run-selection --approve-input 19a1137161528d5c4eec95242148f05abb155b2fe710d2a0d59846cceabaa8a2
```

Optional provider-free check:

```bash
pte analysis structure-readiness --typesafe-selection --check-only --json
```

**102 focused tests pass.** The receipt prefix also passed offline seal/wire/cache/accounting verification. No new provider requests, output repair, question/model changes or source audit occurred during this bugfix. The original numerical/token/cost limits remain; continuation conservatively reserves the earlier 20 full 45-second request timeouts against the original 1,800-second active-time cap, leaving at most 900 seconds. Measurement/admission and collection/projection remain held.

Historical implementation pins are checked against Git `92a97d1` for the specific repaired adapter, executor and regression test only. The original input/receipts remain immutable; the repair decision separately pins the current code. This is a transport/proof recovery, not a semantic result or another experiment.
