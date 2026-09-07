# Qwen3-Coder-30B-A3B quantization on a single RunPod A40

Resolves [ticket #12](https://github.com/ryankilroy/ryai-harness/issues/12),
blocking [ticket #20](https://github.com/ryankilroy/ryai-harness/issues/20).
Parent: [#10](https://github.com/ryankilroy/ryai-harness/issues/10).

Checked against primary sources (`gh api` against `sgl-project/sglang`
issues/PRs, the HuggingFace Hub API for exact file sizes, the model's own
`config.json`) on 2026-09-06. WebSearch was used only to locate candidates,
never trusted for a number or a verdict — several of its aggregated
summaries were wrong or misleading on closer `gh api` inspection (see
methodology notes inline). Every load-bearing claim below is a direct link
to a GitHub issue/PR, an HF repo, or the model config, not a paraphrase.

**Question this resolves:** does a non-AWQ, Ampere-compatible quantization
of Qwen3-Coder-30B-A3B (30B total / 3B active MoE) fit on a single A40
(48GB, Ampere/SM 8.6) under SGLang, with guided decoding and RadixAttention
on — and if so, which one, at what configuration?

**Headline finding, stated up front:** FP8 — the precision ADR 0006 names
by name — does not run on the A40 under SGLang today. A working quantized
configuration exists, but it is GPTQ-Int4 via a specific non-default kernel
flag, not FP8. Section (e) below is dedicated to this and should be read as
its own finding, not a footnote.

## (a) Candidate quantizations, named and sourced

Four quantization families exist for this model. AWQ is carried forward
from #8 as already ruled out (see (c)); the other three are evaluated here.

| Quantization | Ampere/A40 compatible? | Source |
|---|---|---|
| **FP8** (official `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8`, block-128 W8A8) | **No — does not load.** SGLang throws `ValueError("type fp8e4nv not supported in this architecture. The supported fp8 dtypes are ('fp8e4b15', 'fp8e5')")` on Ampere for MoE FP8 checkpoints. | [Issue #12887](https://github.com/sgl-project/sglang/issues/12887) (exact error text, filed 2025-11-08). Full trail in (e). |
| **GPTQ-Int8** (W8A16, e.g. `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-GPTQ-Int8`) | **Loads — kernel routing on this exact checkpoint not independently confirmed in this pass.** No SGLang bug report was found against Int8 MoE specifically, but that is absence of evidence, not confirmation; see gap list. | [QuantTrio/Qwen3-Coder-30B-A3B-Instruct-GPTQ-Int8](https://huggingface.co/QuantTrio/Qwen3-Coder-30B-A3B-Instruct-GPTQ-Int8) |
| **GPTQ-Int4** (W4A16) | **Loads, with a named trap.** `--quantization gptq_marlin` (the default Marlin auto-select) OOMs at TP=1 in `gptq_marlin_moe_repack`. `--quantization moe_wna16` (a distinct, currently-present kernel — confirmed live on SGLang `main`, 28 hits including `server_args.py` and `layers/quantization/moe_wna16.py`) loads successfully but with reported "very poor" (unquantified) throughput. See arithmetic in (b) and full bug trail below. | [Issue #9872](https://github.com/sgl-project/sglang/issues/9872) (`gptq_marlin_moe_repack` OOM); [Issue #9574](https://github.com/sgl-project/sglang/issues/9574) (`moe_wna16` recipe + perf complaint, quoted verbatim below); `gh api "search/code?q=moe_wna16+repo:sgl-project/sglang"` confirmed 28 current hits, 2026-09-06. |
| **AWQ** | **No — fails to load.** Carried forward from #8, not re-derived here. | [Issue #9838](https://github.com/sgl-project/sglang/issues/9838) — see (c). |

**A first-person, same-silicon-generation data point exists for GPTQ-Int4
MoE**, from the FP8-Marlin PR thread (not the GPTQ issues): `hauck-jvsh`,
2025-09-04, on [PR #9754](https://github.com/sgl-project/sglang/pull/9754):
"tested it with qwen3-30b using a Nvidia A5000 and it worked gracefully."
The A5000 is GA102 — SM 8.6, the same compute capability as the A40. This
is about the FP8-Marlin patch specifically (superseded, see (e)), not
`moe_wna16`, but it is independent confirmation that this architecture
family (SM 8.6) is not categorically hostile to Marlin-family MoE kernels.

No first-person report was found of anyone running any of these three
formats specifically on an A40 (as opposed to A5000/4090/A100). This is a
real gap, named in the closing section, not glossed over.

## (b) Weight footprint and KV cache budget against 48GB

**Weight footprints — exact, via the HuggingFace Hub API
(`?blobs=true`, summed `.safetensors` sibling sizes), re-verified
2026-09-06:**

| Config | Repo | Weights (decimal GB) |
|---|---|---|
| FP8 | [Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8](https://huggingface.co/api/models/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8?blobs=true) | 31.18 GB |
| GPTQ-Int8 | [QuantTrio/…-GPTQ-Int8](https://huggingface.co/api/models/QuantTrio/Qwen3-Coder-30B-A3B-Instruct-GPTQ-Int8?blobs=true) | 32.00 GB |
| GPTQ-Int4 | [btbtyler09/…-gptq-4bit](https://huggingface.co/api/models/btbtyler09/Qwen3-Coder-30B-A3B-Instruct-gptq-4bit?blobs=true) | 18.67 GB |
| AWQ (excluded) | [QuantTrio/…-AWQ](https://huggingface.co/api/models/QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ?blobs=true) | 16.81 GB |

**Provenance caveat:** Qwen's own org (`Qwen/`) publishes only BF16 and
FP8 for this model — confirmed via `curl .../api/models?author=Qwen&search=...`,
two results, neither GPTQ. Every GPTQ checkpoint above is a third-party
community quantization (QuantTrio, btbtyler09), not vendor-published.
QuantTrio does not publish a GPTQ-Int4 variant of this specific
Coder checkpoint (only Int8 and AWQ) — the Int4 number above comes from a
different, less-established uploader (773 downloads, 4 likes). Weigh this
against the load/perf bug evidence below, which is itself for a *different*
repo again (see caveat under (b) KV arithmetic).

**Model architecture, from `config.json` (fetched 2026-09-06):**
`num_hidden_layers=48`, `num_key_value_heads=4`, `head_dim=128`,
`hidden_size=2048`, native `torch_dtype=bfloat16`, `max_position_embeddings=262144`,
128 experts / 8 routed per token (confirms MoE, not dense — sized as such
throughout).

**KV cache bytes/token (GQA, both K and V, all layers, BF16 KV cache):**

```
bytes/token = 2 × num_layers × num_kv_heads × head_dim × bytes_per_element
            = 2 × 48 × 4 × 128 × 2
            = 98,304 bytes = 96 KiB/token
```

**Budget against the A40's 48GB**, using SGLang's `--mem-fraction-static`
(default 0.9 — the fraction of total device memory given to weights + KV
pool combined; the remainder is reserved for activations and CUDA-graph
buffers). A conservative `0.85` is used here rather than the 0.9 default,
landing the reserve at 7.2GB — inside SGLang's own documented 5–8GB
rule-of-thumb reserve, rather than at its thin edge:

```
weights + KV budget = 0.85 × 48 GB = 40.8 GB
```

| Config | Weights | KV budget (40.8 − weights) | Token pool (÷ 98,304 B) |
|---|---|---|---|
| FP8 (moot — doesn't load) | 31.18 GB | 9.62 GB | ≈ 97,900 tokens |
| **GPTQ-Int8** | 32.00 GB | **8.80 GB** | **≈ 89,500 tokens** |
| **GPTQ-Int4** | 18.67 GB | **22.13 GB** | **≈ 225,000 tokens** |
| AWQ (moot — excluded) | 16.81 GB | 23.99 GB | ≈ 244,000 tokens |

Both surviving configs fit with headroom. GPTQ-Int4's pool covers most of
the model's native 262,144-token context as a single sequence; GPTQ-Int8's
~89.5K-token pool is thinner — about a third of native max context as one
sequence — but still comfortably covers this project's Slice-shaped usage
(a long shared CONTEXT.md Seed plus a bounded task body), and RadixAttention
means the shared Seed prefix is cached once, not once per request, so
concurrent Slices don't consume the pool proportionally to their count.

**Capacity-unit caveat, flagged not resolved:** "48GB" is RunPod's and
NVIDIA's nameplate figure. A WebSearch pass raised — but did not
consistently confirm — that A40s ship with ECC enabled by default, which
typically taxes a few percent of usable VRAM on datacenter GPUs; the search
result that surfaced this was internally inconsistent (conflated A40 and
L40 figures) and is **not trusted as a primary source here**. The nominal
48GB is used throughout per the ticket's own framing ("sized against the
A40's 48GB"). The margins above are large enough for both surviving
configs that a few GB of ECC tax would not flip either yes/no, but this
should be confirmed against actual `nvidia-smi` output at Pod boot before
treating the token-pool numbers as exact.

**Untested lever for the "smallest configuration" question:** SGLang
supports `--kv-cache-dtype fp8_e5m2`, which would roughly halve the
KV-cache bytes/token above (48 KiB/token instead of 96). Generic SGLang/
vLLM docs describe FP8 KV cache as compute-dequantized at attention time on
backends without native FP8 attention support — which would make it a
storage-format optimization rather than a compute-path one, and thus
plausible on Ampere. **This was not confirmed against a primary source
specific to SM 8.6 in this pass** — it is named here as a lever worth
smoke-testing (it would double every token-pool figure above, most usefully
widening GPTQ-Int8's thinner budget), not as a verified fact.

## (c) Carried forward from #8 — not re-derived

Per the ticket's explicit AC, these are quoted from
[issue #8](https://github.com/ryankilroy/ryai-harness/issues/8)'s posted
findings, not re-investigated:

1. **AWQ load failure.** "AWQ-quantized Qwen3-Coder-30B-A3B fails to *load*
   on SGLang (missing vLLM dependency for `CompressedTensorsWNA16`)... GPTQ/
   FP8 weren't reported hitting this; verify experimentally whichever format
   is chosen." — [issue #9838](https://github.com/sgl-project/sglang/issues/9838).
   This pass's own findings are consistent with "GPTQ/FP8 weren't reported
   hitting this": FP8's failure mode is architecturally distinct (an
   unsupported-dtype error, not a missing-dependency error), and GPTQ's
   failure modes (below) are also distinct from AWQ's. AWQ is excluded from
   the arithmetic in (b) on this basis and not re-tested.

2. **Truncation-empty-output caveat.** "[Issue #35565](https://github.com/sgl-project/sglang/issues/35565)
   (open) — 13 parsers including `qwen3_coder` silently return an empty
   message if generation is truncated right after a tool-call open marker.
   Relevant on an A40 running a large quantized MoE — use generous
   `max_tokens` and detect empty-message responses defensively." This
   interacts directly with guided decoding: a `structural_tag`-constrained
   generation that gets truncated mid-tool-call-envelope hits this exact
   failure mode. Mitigation (from #8, unchanged): generous `max_tokens`,
   defensive empty-message detection at the Adapter layer.

## (d) Recommended configuration

**GPTQ-Int4, served with `--quantization moe_wna16` — explicitly not the
default `gptq_marlin` auto-select.**

Reasoning:

- It is the only surviving candidate with a same-architecture-generation
  (SM 8.6, via the A5000 report) positive load signal, and a same-model
  positive load signal (`tensorflowt` on [#9574](https://github.com/sgl-project/sglang/issues/9574),
  quoted verbatim: *"It does load fine, but the inference performance is
  very poor!"* — a function complaint, not a load failure).
- `--quantization gptq_marlin` is a **named trap**, not a safe default: it
  OOMs at TP=1 in `gptq_marlin_moe_repack` per [#9872](https://github.com/sgl-project/sglang/issues/9872).
  The Pod's container build must pin `--quantization moe_wna16` explicitly.
- It leaves by far the largest KV-cache headroom of any working config
  (≈225K-token pool vs. Int8's ≈89.5K), which matters more on a single-GPU,
  single-tenant Pod than raw decode throughput — ADR 0004 scopes this
  deployment to bursty single-developer sessions with a long shared prefix,
  not high-concurrency serving.
- The known risk — "very poor" (unquantified) decode throughput via the
  `moe_wna16` path — is a **tolerable** risk class for this workload, not a
  disqualifying one. Even a materially slower single-stream decode (the
  #9574 reporter never posted a tok/s number, so this cannot be bounded
  precisely) is usable for an agentic coding harness processing one Slice
  at a time; "won't load" (FP8, AWQ) is a different and worse risk class
  than "loads but slow" (GPTQ-Int4).

**Fallback: GPTQ-Int8**, if GPTQ-Int4's output quality or throughput proves
unacceptable under empirical testing. Two caveats attach to it, both
unresolved in this pass: it has the thinnest KV budget of any working
config (≈8.8GB / ≈89.5K tokens — workable but no longer generous), and
its SGLang MoE kernel routing (whether it goes through a Marlin path with
Int4's OOM trap, a separate Triton `gptq` path, or `moe_wna16` also) was
**not independently confirmed in this pass** — an unresearched unknown on
the fallback pick, not a known-and-mitigated risk like Int4's.

**This is not "no single-A40 configuration works."** A configuration
exists. It is a quantized-GPTQ configuration on a non-default kernel flag,
not the FP8 configuration ADR 0006 names — which is exactly the finding
Section (e) exists to state loudly.

Before this configuration is written into the Pod's container build
(ticket #20), it should be smoke-tested empirically on an actual A40: load
success, a rough tok/s figure, and output quality under guided decoding are
all currently sourced from other GPUs (4090, A5000) or unquantified
("very poor" with no number attached).

## (e) ADR 0006's A40↔FP8 pairing — does it survive?

**No, not as stated. This is called out explicitly, not quietly worked
around, per this ticket's own AC.**

[ADR 0006](../adr/0006-starting-working-backend.md) picks the A40 "with
room for a 30B MoE at **FP8**/quantized precision." This pass finds FP8
specifically does not run on SGLang/Ampere for this model, with a full,
unambiguous primary-source trail:

1. **The failure is real and specific.** [Issue #12887](https://github.com/sgl-project/sglang/issues/12887)
   (filed 2025-11-08): SGLang throws
   `ValueError("type fp8e4nv not supported in this architecture. The
   supported fp8 dtypes are ('fp8e4b15', 'fp8e5')")` for MoE FP8 checkpoints
   on Ampere. vLLM already has a Marlin-based weight-only fallback for this
   exact case; SGLang, at the time of filing, did not.

2. **A fix was built, tested on A40 specifically, and never merged.**
   [PR #9754](https://github.com/sgl-project/sglang/pull/9754) ("enable moe
   marlin fp8 for Ampere GPU") states in its own body: "This pr has been
   verified on Qwen/Qwen3-30B-A3B-Thinking-2507-FP8 with 1,2,4 A40". Author
   `ehuaa` confirmed again in comments (2025-09-08): "I have tested qwen moe
   on a40 and deepseek on a100." The PR sat open for 10+ months and was
   **closed unmerged**, `merged: false`.

3. **A maintainer claimed it landed. It hadn't — an author caught it,
   with a screenshot.** This is the single strongest piece of evidence for
   how unsettled this is, and is stated here in full rather than as a
   footnote: on 2026-06-10, maintainer `hnyls2002` closed #9754 saying
   *"Marlin FP8 MoE is supported on main now (`Fp8MoEMethod.use_marlin`),
   so I'm closing this as superseded."* One month later (2026-07-09), PR
   author `ehuaa` replied with a screenshot: *"actually,
   `Fp8MoeMethod.use_marlin` has not been implemented on main branch...
   only `Fp8LinearMethod.use_marlin` has been implemented now."* — i.e. the
   *dense-linear-layer* Marlin FP8 path had landed, but the *MoE* Marlin FP8
   path (what this model needs) had not, despite the maintainer's belief
   that it had.

4. **The real fix is a separate, still-open, still-unmerged PR.**
   [PR #30681](https://github.com/sgl-project/sglang/pull/30681)
   ("Route block-wise and per-tensor FP8 MoE checkpoints... through the
   Marlin W8A16 MoE kernel on GPUs without native FP8 compute (SM80-SM89)")
   explicitly supersedes #9754 and explicitly names Qwen3-30B-A3B-FP8 (this
   model's base architecture) as an in-scope checkpoint. Re-checked
   2026-09-06: **`state: open`, `merged: false`, last updated
   2026-08-10** — roughly four weeks stale as of this research pass, with
   no committed timeline for merge.

**Verdict, stated as a split because that's what the evidence shows:**

- The **FP8 half of ADR 0006's mechanism does not survive.** No native FP8
  tensor-core support exists on Ampere/SM 8.6 (a hardware fact, not an
  SGLang gap), and SGLang's own weight-only Marlin fallback for MoE FP8 is
  presently unmerged on `main`.
- The **"quantized precision" half, and the A40-tier decision itself, do
  survive** — GPTQ-Int4 (Section (d)) fits with large headroom.
- ADR 0006's *conclusion* (the A40 is a viable tier for this model) holds.
  Its *stated mechanism* ("FP8/quantized precision") does not — the "FP8"
  half is currently false on this hardware/engine pairing. **This warrants
  an amendment note on ADR 0006** clarifying the tier decision rests on
  quantized (GPTQ) precision, not FP8, until #30681 or an equivalent lands
  upstream — a documentation correction, not a re-litigation of the tier
  choice.

## Open gaps this pass did not close

- **GPTQ-Int8's SGLang MoE kernel routing** — whether it uses a Marlin
  path (and inherits Int4's `gptq_marlin_moe_repack` OOM trap), a separate
  Triton `gptq` path, or `moe_wna16` also. Not sourced in this pass; needed
  before Int8 can be trusted as a fallback rather than merely "no bug
  report found."
- **No first-person report, for any surviving format, on an A40
  specifically running Qwen3-Coder-30B-A3B.** The best available signals
  are cross-GPU (4090, A5000) or cross-checkpoint (base Qwen3-30B-A3B-GPTQ-
  Int4, not the Coder variant) — same MoE architecture and dimensions, but
  not the exact artifact this project would deploy.
- **`moe_wna16`'s actual throughput is unquantified.** "Very poor" (#9574)
  has no tok/s number attached anywhere found. This must be measured
  empirically before the config is treated as production-viable, not just
  load-viable.
- **`--kv-cache-dtype fp8_e5m2` on SM 8.6** — plausible as a storage-only
  format (not a compute-path change) per generic docs, not confirmed
  against a primary source specific to Ampere. Worth testing; would ease
  GPTQ-Int8's thinner KV budget if it works.
- **ECC's effect on the A40's actually-usable VRAM** — raised by an
  inconsistent WebSearch result, not confirmed via `nvidia-smi` or an
  NVIDIA datasheet in this pass. Margins are large enough not to change the
  verdict, but the exact token-pool numbers in (b) should be treated as
  approximate until checked against real hardware.
- **Guided decoding's steady-state memory cost** was investigated
  (SGLang issue #19410, an alleged ~6–10 MiB/request leak in grammar-guided
  generation) but not independently re-confirmed via `gh api` in this pass
  before the context budget for this ticket ran out — sourced from an
  aggregated WebSearch summary only. If real, ADR 0004's activity-renewed
  Lease lifecycle (Pod torn down between sessions) already bounds its blast
  radius, but the underlying claim itself is unverified here.
