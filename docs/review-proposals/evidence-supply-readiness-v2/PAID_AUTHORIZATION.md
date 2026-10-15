# V2 bounded paid validation authorized — 2026-10-14

Brian authorizes the frozen six-source V2 diagnostic run: at most 4,680 cumulative attempts, including failed/lost replies, zero automatic retries, pinned `jev-1.13.0`, and a $12.579840 public-list-price ceiling. The [machine-readable authorization](paid-authorization-v2.json) supersedes the earlier preparation-only payment hold. The frozen packet, source boundaries, exact checks, model questions and acceptance criteria remain unchanged. No execution result has yet been reported.

Brian executes this command; Codex does not run or monitor the job:

```sh
pte analysis evidence-supply-review --revision v2 --execute \
  --approve-paid-packet 42510f580522e3ef3b8d0b6993491887a3b9c13e2433b1c900a66cd750a75f30
```

The run measures semantic correctness and usable evidence among supplied candidates. The known 16 G2 and 13 G3 positive exact-span supply misses remain disclosed. Semantic outputs from other candidates may be useful, but do not retroactively turn those misses into exact supply hits or establish complete-reference-slate discovery PASS. Integrity failures, measurement errors, supply misses and conservative withholding remain separate.

Results are `evaluation/evidence-supply-readiness-v2/results-v2.md` and `results-v2.json`. Codex owns the source audit and concrete PASS/PARTIAL/FAIL recommendation; Brian decides from that report. Any interrupted or failed attempt requires a separate recovery decision before replacement spending.

Brian proposes a small real collection followed by V1 pastor projection after a successful readiness decision. Prepare that concrete scope after interpreting the results. Broader collection and projection/scoring remain held until then. G1/G2/G3 and the accepted consumer remain closed; a supply failure alone does not reopen their contracts.
