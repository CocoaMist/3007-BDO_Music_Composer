# DeepSeek integration direction

Status: research and architecture proposal only
Official-source audit date: 2026-07-25
Runtime implementation: not started

## Decision

Do not make an LLM part of the transcription, playback, optimizer safety, or
export pipeline. If DeepSeek is added, the recommended first release is an
optional, first-party **AI suggestion provider**:

- disabled by default;
- explicitly selected by the user for each request;
- fed only minimized, locally derived symbolic summaries;
- allowed to create review-only semantic suggestions, never authoritative
  notes or export data;
- validated locally and attached to the existing source fingerprint;
- unavailable without degrading any existing local feature.

“Built in” should mean that the application owns a stable provider adapter and
review UI. It must not mean bundling an API key, silently uploading projects,
placing an LLM in the audio callback, or packaging large model weights in the
one-file executable.

The best MVP target is `deepseek-v4-flash` with thinking disabled and JSON
Output, used for compact role/style/explanation suggestions. `deepseek-v4-pro`
should remain an explicit, higher-cost option for later evaluation. No tool
calls are needed in the MVP.

## Official API snapshot

The following values are current only for the audit date above. The application
must discover available model IDs through `GET /models` and keep model aliases
in configuration, not hard-coded throughout the UI.

| Capability | Official state on 2026-07-25 | Integration consequence |
|---|---|---|
| Models | `deepseek-v4-flash` and `deepseek-v4-pro` | Use concrete V4 IDs. Do not use `deepseek-chat` or `deepseek-reasoner`; the official change log says those legacy names were to be discontinued on 2026-07-24 15:59 UTC. |
| Protocol | OpenAI-compatible Chat Completions at `https://api.deepseek.com`; an Anthropic-compatible endpoint also exists | A small provider interface is sufficient. Compatibility is not identity: only send fields documented by DeepSeek. |
| Input modality | Chat message `content` is a text string | DeepSeek V4 cannot replace Basic Pitch or inspect WAV/MP3 evidence directly. Never upload raw audio merely to turn it into text first. |
| Context/output | 1M-token context; maximum output 384K | These are ceilings, not targets. The desktop request budget should be much smaller and bounded. |
| Thinking | Thinking is enabled by default; supported effort values are `high` and `max` | MVP must explicitly send `thinking.type=disabled`. Thinking mode ignores temperature/top-p style controls and can add material latency and output-token cost. |
| Streaming | SSE streaming is supported; the service may emit keep-alive comments/blank lines while queued | Parse SSE correctly, support cancellation, and never hold the GUI thread. |
| JSON Output | `response_format={"type":"json_object"}` produces valid JSON | It does not prove application-schema validity. The official guide warns that content can occasionally be empty and that truncation can occur. Always validate locally. |
| Tool calls | Function calls are supported; the model only proposes calls and the client executes them | Never expose mutating editor/export/file tools. Strict schema mode is Beta at `/beta`, so it is not an MVP dependency. |
| Context cache | Provider-side disk caching is enabled by default, best effort, and usually cleared after hours to days | Repeated prefixes can lower cost, but this is also a remote persistence boundary that must be disclosed. |
| Isolation | `user_id` can isolate KV cache and scheduling; the value must not contain personal information | If later needed, use a random installation-scoped opaque ID. Do not send account, character, Owner ID, path, or project name. |
| Availability | Cloud availability is not warranted by the terms; an official status page exists | Add timeout, cancellation, circuit breaking, and a local fallback. The editor must remain fully usable offline. |

### Prices on the audit date

Official prices are USD per 1M tokens:

| Model | Input, cache hit | Input, cache miss | Output |
|---|---:|---:|---:|
| `deepseek-v4-flash` | $0.0028 | $0.14 | $0.28 |
| `deepseek-v4-pro` | $0.003625 | $0.435 | $0.87 |

A compact request with 20,000 cache-miss input tokens and 2,000 output tokens
would therefore cost about $0.00336 on Flash or $0.01044 on Pro at these rates.
This example excludes retries and assumes the returned token accounting is the
billed accounting. Thinking tokens are reported inside completion usage, so
thinking mode needs its own output budget.

Prices can change. The UI should show an estimate before sending, record the
actual `prompt_cache_hit_tokens`, `prompt_cache_miss_tokens`, completion tokens,
and cost after the response, and support a user-set monthly ceiling. It should
not promise a fixed price.

## Fit with this repository

The repository already has the right safety boundaries:

- `bdo_music_theory.ContextClassifier` accepts optional model priors but keeps
  deterministic theory as the base result.
- `OptimizationRequest` is an immutable snapshot.
- `OptimizationPreview` is review-only and is checked by
  `validate_preview()` before it can be materialized.
- transcription candidates and assist decisions remain sidecars until
  Apply/OK.
- the real-time engine permits no I/O or model work in the audio callback.

DeepSeek should sit outside `optimization/builtin.py` and outside the `.bdoopt`
loader. A network credential and privacy policy are application concerns, while
`.bdoopt` packages are trusted local optimizer code. A focused package such as
`ai_assist/` should own the remote/local provider abstraction.

```text
current editor snapshot
        |
        v
local deterministic features
        |
        v
payload minimizer + privacy policy gate
        |
        +------ disabled/offline ------> local deterministic result
        |
        v
background provider request
        |
        v
JSON parse + schema/range/enum validation
        |
        v
source-fingerprint attachment + stale-result check
        |
        v
AI suggestion sidecar
        |
        v
preview / user decision / existing Apply gate
```

Suggested interfaces:

```python
class AiAssistProvider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...
    def suggest(self, request: AiAssistRequest, cancel: CancelToken) -> AiAssistResponse: ...

@dataclass(frozen=True, slots=True)
class AiAssistRequest:
    schema_version: int
    task: Literal["song_roles", "phrase_explanation", "arrangement_intent"]
    public_payload: dict[str, object]
    local_source_fingerprint: str  # wrapper metadata; never sent to the provider

@dataclass(frozen=True, slots=True)
class AiAssistResponse:
    provider_id: str
    model_id: str
    schema_version: int
    suggestions: tuple[SemanticSuggestion, ...]
    usage: TokenUsage
```

The provider request must contain only `public_payload`. The source fingerprint
is retained locally and attached after validation so the existing stale-preview
check remains authoritative.

## Recommended MVP

### User value

Add one compact “AI 建议” action to the existing analysis/review surface. It
should provide:

1. track and phrase role suggestions from local summary features;
2. up to three style or arrangement intents;
3. short explanations of deterministic instrument/articulation candidates;
4. explicit uncertainty and conflicting evidence.

It should not add a general-purpose chatbot. A chat transcript creates more
privacy, state, prompt-injection, and UI-noise problems than musical value.

### Payload

The default cloud payload is a symbolic summary, not the MIDI:

- BPM and supported meter;
- anonymized ephemeral track references such as `t1`, `t2`;
- note count, pitch range, pitch-class histogram, duration/density/polyphony
  summaries, syncopation and swing summaries;
- locally inferred role/key/chord candidates with evidence levels;
- BDO instrument constraints represented by stable IDs and bounded enums;
- the selected task and response schema.

Exclude by default:

- exact note sequences or a complete melody;
- raw or encoded audio, waveform pixels, ONNX evidence, sample features, and
  game sample files;
- BDO binary payloads;
- Owner ID, account/character names, project and track display names, filenames,
  absolute or relative paths;
- lyrics and free-form metadata;
- autosave contents, API keys, logs, and local configuration.

A later “selected phrase” request may include a short relative-time note window
only after a second, task-specific consent screen shows exactly what will be
sent. The whole song must not be silently substituted when no phrase is
selected.

### Response schema

Use JSON Output with a deliberately small schema:

```json
{
  "schema_version": 1,
  "track_priors": [
    {
      "track_ref": "t1",
      "role": "primary_melody",
      "evidence": ["high_register", "low_polyphony"],
      "uncertainty": "medium"
    }
  ],
  "style_priors": [
    {
      "style": "orchestral",
      "evidence": ["instrument_family_mix"],
      "uncertainty": "medium"
    }
  ],
  "summary": "..."
}
```

All objects must reject unknown keys. All strings, arrays, and counts need local
length limits; track references and enum values must resolve to the current
snapshot. Model-reported confidence is not calibrated and must not unlock an
automatic edit. One bounded retry is acceptable for an empty or malformed JSON
response; otherwise fall back to deterministic analysis.

### Model/request defaults

- model: `deepseek-v4-flash`;
- thinking: disabled explicitly;
- streaming: enabled for responsive cancellation, but do not render partial
  JSON as a valid suggestion;
- temperature: low and fixed for repeatability;
- output: small bounded maximum, not the API maximum;
- timeout: separate connect, first-token, idle, and total deadlines;
- retries: at most one for transient/empty/invalid responses, with exponential
  backoff and no retry on authentication, consent, schema, or balance errors;
- cache: keep the system prompt and schema as a stable prefix to improve cache
  hits, while disclosing that the provider creates remote disk cache entries.

Acceptance criteria:

- 100% of accepted responses pass the local schema and stale-source checks;
- zero formal `Note`, `TrackState`, playback, or export mutations before Apply;
- offline/provider failure leaves deterministic results unchanged;
- no prohibited field appears in captured request fixtures;
- P50/P95 latency, empty/malformed rate, token use, cost, and suggestion
  acceptance are measured;
- suggestions are evaluated against a fixed local corpus before Pro or
  note-affecting experiments are offered.

## Privacy and security design

Adding the official cloud API changes the application's current “no upload”
property. The release must update the README, first-run disclosure, privacy
copy, and settings before the first network call.

### Required controls

1. **Off by default.** Existing and migrated projects remain local. Merely
   entering an API key must not enable background requests.
2. **Explicit action.** Every request begins from a user command. No startup,
   autosave, import, transcription, or background-project scan may call an LLM.
3. **Payload preview.** Show a concise data-category summary and provide an
   expandable exact JSON preview before the first cloud request and whenever
   the payload class expands.
4. **Provider distinction.** Clearly distinguish `关闭`, `本地端点`, and
   `DeepSeek 云端`. A non-loopback custom endpoint is remote and receives the
   same warning as a cloud provider.
5. **Secret storage.** Store API keys in Windows Credential Manager or an
   equivalent OS secret store. Never put them in `project.json`, the local
   config file, environment diagnostics, crash reports, logs, command lines,
   source code, or the executable. An environment variable is acceptable only
   for development.
6. **Network policy.** Verify TLS and allow only the configured host. Do not
   follow a redirect to a different host while carrying authorization.
   Loopback local endpoints may use HTTP; non-loopback HTTP is rejected.
7. **Minimal logging.** Log provider/model, timing, status category, schema
   version, token/cache counts, and a one-way local payload digest. Do not log
   prompts, outputs, `reasoning_content`, tool arguments/results, secrets, or
   user data.
8. **Deletion.** Let users clear local AI suggestion history and credentials
   independently. Do not claim this deletes provider-side caches or records.
9. **Opaque isolation ID.** If `user_id` is used, generate a random opaque
   installation ID. Do not derive it from Owner ID, username, machine name, or
   project data.
10. **Prompt-injection containment.** Treat track names, lyrics, filenames, and
    imported metadata as untrusted data. They are excluded by default, never
    concatenated into system instructions, and never gain access to tools.

### What can and cannot be promised

DeepSeek's official context-cache documentation says API request prefixes are
written to a provider-side disk cache and are normally cleared after hours to
days. Its privacy policy says personal data may be processed and stored in the
People's Republic of China. The Open Platform terms require the downstream
developer to disclose its own end-user personal-data processing rules and have
an appropriate legal basis or consent.

The general Terms of Use say Inputs and Outputs may, after security and
de-identification measures, be used to provide or improve services, with an
“Improve the model for everyone” opt-out. The official Open Platform terms do
not state an API-specific zero-retention or no-training guarantee, and the
official privacy policy explicitly says downstream end-user processing rules
are not covered by that privacy policy.

Therefore this project must not advertise DeepSeek cloud requests as
zero-retention, no-training, local-only, anonymous, or suitable for secrets.
Before shipping, the maintainer should obtain and review the exact policy shown
for the API account/region being used and seek legal review where required.
Users who need a local-only workflow should use the disabled mode or a verified
loopback endpoint.

The Open Platform terms also restrict prominent or misleading use of DeepSeek
branding. The product should use a neutral “AI 建议” surface with the provider
named in settings/status, should not use DeepSeek's logo without permission,
and must not imply official partnership or endorsement.

## Local deployment direction

Cloud V4 and local open-weight DeepSeek are different product choices:

- The official DeepSeek organization did not publish a V4 weights repository
  or official V4 local-deployment instructions found in this audit. Treat
  `deepseek-v4-flash` and `deepseek-v4-pro` as cloud API models unless DeepSeek
  publishes an official local release later.
- Full DeepSeek-V3 has 671B total parameters with 37B active per token. The
  official demo uses multi-process/model-parallel deployment and is not a
  reasonable dependency for a Windows one-file MIDI editor.
- The official DeepSeek-R1 repository provides distilled Qwen models at
  1.5B/7B/14B/32B and distilled Llama models at 8B/70B, with vLLM and SGLang
  serving examples. These are candidates for a user-managed local service, not
  for bundling into the application.
- The R1 repository and weights use the MIT license, while Qwen-derived models
  retain Apache 2.0 ancestry and Llama-derived models retain the applicable
  Llama license. Every selected model/runtime still needs its own notice and
  redistribution review.

Recommended local design:

1. support a configurable OpenAI-compatible endpoint behind the same
   `AiAssistProvider` interface;
2. require explicit model ID and run a read-only capability probe;
3. prefer loopback and show whether the endpoint is local or remote;
4. let the user install, update, and run the inference service separately;
5. do not download weights automatically and do not bundle CUDA, vLLM, SGLang,
   or model files in PyInstaller;
6. benchmark each local model against the same schema-validity and musical
   acceptance corpus—do not imply that an R1 distill equals V4.

This keeps the desktop package reproducible, avoids competing with the ONNX
transcription process for memory, and gives privacy-sensitive users an
independent deployment path.

## Later phases

### Phase 2: selected-phrase expert review

- Optional `deepseek-v4-pro`, thinking enabled only for a selected phrase.
- Read-only tools may expose already minimized local facts such as
  `get_phrase_summary`, `get_instrument_constraints`, and
  `get_deterministic_analysis`.
- Tool arguments and results are validated and size-bounded.
- No filesystem, shell, network, editor mutation, playback, export, project
  save, or credential tool is exposed.
- When thinking-mode tool calls are used, the official protocol requires
  replaying `reasoning_content` in later tool turns. Keep it only in volatile
  job memory and erase it when the job ends.
- Beta strict tool mode may be evaluated, but local validation remains
  mandatory because the client executes the call.

### Phase 3: high-level optimization intent

The LLM may propose only bounded musical intents such as role, density target,
articulation policy ID, or instrument-family preference. A deterministic local
compiler converts accepted intents into an `OptimizationPreview`; the existing
host validates all operations and the user applies them.

The model must never directly emit `ReplaceNote`, `InsertNote`, `DeleteNote`,
`CreateTrack`, `EffectChange`, raw `Note(...)`, or BDO binary fields. This phase
requires a frozen evaluation corpus, deterministic replay fixtures, per-song
worst-regression checks, and a fail-closed release gate.

## Tasks that must remain local and deterministic

DeepSeek is not suitable as the authority for:

- audio decoding, source separation, pitch/onset/offset inference, or fragment
  cleanup;
- exact note timing, quantization, pitch correction, velocity, or `ntype`;
- real-time playback, sample lookup, mixing, limiting, scheduling, or waveform
  painting;
- BDO instrument-range enforcement, drum canonicalization, 730-note splitting,
  binary layout, encryption, Owner ID validation, or export;
- project migration, autosave recovery, undo/redo, selection, or routing;
- accepting/rejecting transcription candidates without user review;
- detecting the source instrument from text summaries and presenting it as
  verified audio evidence;
- executing model-selected files, shell commands, URLs, plugins, or network
  requests;
- making game-evidence claims or overriding manually locked decisions;
- any action that must be deterministic, idempotent, low-latency, offline, or
  safe when the provider is unavailable.

The LLM can explain, classify, and propose. Existing local algorithms validate,
preview, and apply.

## Official sources

All sources below are first-party DeepSeek pages or repositories and were
checked on 2026-07-25:

- [API quick start and compatibility](https://api-docs.deepseek.com/)
- [Models and current pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [Model-list endpoint](https://api-docs.deepseek.com/api/list-models)
- [Chat Completions schema](https://api-docs.deepseek.com/api/create-chat-completion)
- [Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)
- [JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- [Tool calls and Beta strict mode](https://api-docs.deepseek.com/guides/tool_calls/)
- [Provider-side context caching](https://api-docs.deepseek.com/guides/kv_cache/)
- [Rate limits and `user_id` isolation](https://api-docs.deepseek.com/quick_start/rate_limit)
- [API change log](https://api-docs.deepseek.com/updates/)
- [Official service status](https://status.deepseek.com/)
- [DeepSeek Open Platform Terms of Service](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html)
- [DeepSeek Terms of Use](https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html)
- [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)
- [Official DeepSeek GitHub organization](https://github.com/deepseek-ai)
- [DeepSeek-V3 repository and deployment notes](https://github.com/deepseek-ai/DeepSeek-V3)
- [DeepSeek-R1 repository, distill models, deployment, and licenses](https://github.com/deepseek-ai/DeepSeek-R1)
