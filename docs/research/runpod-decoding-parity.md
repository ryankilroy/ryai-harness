# RunPod worker-vllm and SGLang/vLLM decoding-feature parity

Resolves [ticket #2](https://github.com/ryankilroy/ryai-harness/issues/2) on
[the Model Backend infra map](https://github.com/ryankilroy/ryai-harness/issues/1).

Checked against primary sources only (official docs, official repo READMEs)
on 2026-09-03, given the prior research report's warning that this space is
heavily polluted with fabricated model/benchmark content. Two initial
WebSearch passes surfaced exactly that contamination (e.g. claims that
XGrammar ships built-in structural tags for "DeepSeek V4" and "Qwen 3.6" —
both names the prior report already flagged as unconfirmed fabrications) and
were discarded in favor of direct fetches of official docs.

## (a) Does RunPod's stock `worker-vllm` expose guided decoding?

**No — unchanged from the prior report's finding.** Checked both
[docs.runpod.io's vLLM OpenAI-compatibility page](https://docs.runpod.io/serverless/vllm/openai-compatibility)
and the [runpod-workers/worker-vllm README](https://github.com/runpod-workers/worker-vllm):

- The documented request parameters (common OpenAI params + "additional vLLM
  parameters" like `best_of`, `top_k`, `repetition_penalty`) do **not**
  include `guided_json`, `guided_grammar`, `guided_choice`, `guided_regex`,
  or `structural_tag`.
- The README documents `ENABLE_AUTO_TOOL_CHOICE` and `TOOL_CALL_PARSER` env
  vars for tool calling, but nothing dedicated to guided/structured decoding.
- It does document a `VLLM_EXTRA_ARGS` env var — "escape hatch for appending
  additional CLI flags verbatim" — which could in principle set a
  server-wide `--structured-outputs-config.backend` at boot. This does not
  solve the actual need: the Harness needs **per-request** grammars (a
  different Tool Call schema per call), and nothing in the documented request
  body accepts a per-request schema. This is a real gap, not a documentation
  gap — the worker's request/response contract doesn't have a slot for it.

**Conclusion unchanged:** run a plain vLLM or SGLang server in your own
container (Pod or custom serverless worker), not the stock `worker-vllm`
template, if per-request constrained decoding is required.

## (b) vLLM vs SGLang feature parity

**Structural Tag (split reasoning/scratchpad from constrained tool-call
envelope) — confirmed available in both engines' current docs, not just
theoretical:**

- vLLM's [structured outputs docs](https://docs.vllm.ai/en/latest/features/structured_outputs.html)
  list `structural_tag` as a first-class supported request parameter:
  "Follow a JSON schema within a set of specified tags within the generated
  text," with a worked example in the vLLM repo's
  `examples/features/structured_outputs/` directory.
- SGLang's [structured outputs docs](https://docs.sglang.io/docs/advanced_features/structured_outputs)
  document "XGrammar latest structural tag format" via a `structural_tag`
  sampling param using `triggered_tags` — a marker (e.g. `<function=`)
  that activates a constrained JSON-schema region, letting free-form
  reasoning precede it in the same generation.
- This is a stronger position than the prior report implied ("directly
  useful for the split-channel approach") — it's a documented, shipped
  parameter in both engines' current APIs today, not a pending integration.

**Structured-output backends, both engines:** XGrammar (default in both),
plus `guidance`/`llguidance` and `outlines` as alternates. SGLang's own docs
recommend XGrammar explicitly ("better performance and utility"); no
independent throughput comparison was re-verified in this pass (the prior
report's SqueezeBits benchmark citations were not re-checked against a
primary source here — treat those as still coming from the original report,
not confirmed in this session).

**Native tool-call parsers (vLLM, from
[docs.vllm.ai/tool_calling](https://docs.vllm.ai/en/stable/features/tool_calling/)):**

| Model family | `--tool-call-parser` |
|---|---|
| Hermes (Nous, newer than Hermes 2 Pro), Qwen2.5, QwQ-32B | `hermes` |
| Qwen3-Coder (480B-A35B, 30B-A3B) | `qwen3_xml` |
| Mistral-7B-Instruct-v0.3 and compatible | `mistral` |
| DeepSeek-V3 / V3.1 | `deepseek_v3` / `deepseek_v31` |
| Kimi-K2 | `kimi_k2` |
| GLM-4.5 / 4.7 | `glm45` / `glm47` |
| Llama 3.1/3.2/4 | `llama3_json`, `pythonic`, `llama4_pythonic` |

**Devstral has no dedicated parser name found in vLLM's docs.** Devstral is
Mistral-architecture, so it likely uses the generic `mistral` parser, but
this is an inference from architecture lineage, not something the fetched
docs state explicitly — **flag as unconfirmed**, worth a direct check
against Devstral's own model card/tokenizer config before committing to it
in the "starting Working Backend" ticket.

**SGLang's equivalent parser names were not independently re-verified in
this session** (the prior report cited `hermes`/`qwen25`) — this stayed
unconfirmed rather than re-checked against SGLang's current docs; worth
closing before the serving-stack ADR is finalized if SGLang is the pick.

## Open gaps this pass did not close

- SGLang's tool-call parser names/flags, current as of now.
- Whether Devstral specifically needs its own parser or genuinely works
  under `mistral` in practice (not just by architecture family).
- No independent throughput/latency re-measurement of XGrammar vs
  guidance/llguidance vs outlines at concurrency — still resting on the
  prior report's citations, not reconfirmed here.
