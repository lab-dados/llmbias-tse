# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`llmbias-tse` is a research project by **LabDados** (FGV Direito SP) in partnership with **InternetLab** to build an **open, reproducible methodology for automated auditing of generative-AI models in the Brazilian electoral context** (TSE = Tribunal Superior Eleitoral), targeting the 2026 elections.

LabDados owns the **technical automation side**: a harness that programmatically queries widely-used AI tools in Brazil (chat assistants, AI search/browser modes, MetaAI on WhatsApp/Instagram, etc.) with a protocol of test prompts, then collects and processes the responses across four planned data-collection rounds. The analysis looks for: disinformation about candidacies and electoral integrity; reproduction of gender/race-based political violence and deepfakes; conformity with TSE rules (notably the ban on vote recommendation and candidate ranking); and alignment with democratic-integrity principles.

Key constraints that shape the design: the code and methodology must be **publicly released under a free license** for reproducibility and public scrutiny, and the system is meant for **longitudinal, at-scale monitoring** (test automation, rigorous handling of large data volumes, and extraction from proprietary AI models). Methodology decisions are made jointly with InternetLab and are due by **end of July 2026** — much is not yet fixed.

Full proposal: `docs/Projeto InternetLab-LabDados.docx` (internal partnership doc — gitignored, not in the public repo). Tracking issue: https://github.com/lab-dados/adm/issues/61

## Current state

A first **POC of the data-collection harness** exists: browser automation that drives logged-in AI web UIs with personal accounts, captures the responses, and stores them for downstream bias evaluation. The real prompt protocol and evaluation criteria are still TBD (jointly with InternetLab, by end of July 2026); the POC is the e2e skeleton.

## Architecture (POC harness)

Browser automation mirrors the sibling project `monitor-italia`: a **real Google Chrome** launched on a CDP debug port (`--remote-debugging-port`) with a **persistent profile** (`--user-data-dir`), so the user logs in **once** and the script connects to the already-authenticated session via **Patchright** (stealth Playwright fork). Two phases, decoupled on purpose so you can iterate on the collection script without relaunching/re-logging the browser:

1. `launch` — opens Chrome on the port; user logs into each tool manually (incl. WhatsApp QR). Profile persists cookies under `tmp/profile`.
2. `run` — connects over CDP, sends prompts, captures responses, writes `data/<run_id>/`.

Module map under `src/llmbias_tse/`:
- `__init__.py` — `main()` argparse CLI dispatcher (`launch` / `run` / `tools`); console script `llmbias-tse`.
- `browser.py` — Chrome launch on CDP port + `connect()` (profile/port via `LLMBIAS_PROFILE`/`LLMBIAS_CDP_PORT`/`CHROME_PATH` env).
- `drivers.py` — one driver class per tool in `REGISTRY` (`chatgpt`, `gemini`, `claude`, `grok`, `deepseek`, `metaai`, `whatsapp_metaai`). Each holds the **per-UI selectors** (composer + assistant-message containers). **These selectors drift and are the thing to fix when capture breaks.** `BaseDriver.send()` = open new chat → type → Enter → wait for response; WhatsApp overrides it. NB (jun/2026): Claude's response wrapper is now `div[data-is-streaming]` (`true`→`false` = busy signal) with text in `div.font-claude-response`; DeepSeek's composer is a plain `textarea` (the `#chat-input` id is gone) with response in `.ds-markdown`.
- **Momentary/ephemeral drivers** (memory isolation for the conjoint experiment) — each overrides `open_new_chat` to enter a no-memory mode and **raises if it can't confirm** (abort a conversation rather than leak it to history/memory and contaminate data). Verified live (jul/2026): `GeminiMomentary` (toggle "Conversa momentânea", banner "conversas momentâneas"); `ChatGPTMomentary` (URL `?temporary-chat=true`, confirm button "Turn off temporary chat" / banner "Temporary Chat"); `GrokMomentary` (link `a[aria-label='Switch to Private Chat']`, confirm badge "Switch to Default Chat" / banner "won't appear in your history"); `ClaudeMomentary` (button `get_by_role("button", name="Use incognito")` → URL `/new?incognito=`, confirm leaf text "incognito" / "You're incognito"). **DeepSeek has no temporary/private mode** in its UI (jul/2026) — a new chat is already memory-isolated (no cross-chat memory feature), just saved to history; runs on the plain `deepseek` driver. None of these modes persist across navigation → re-enter every conversation. Helper `_has_leaf_text(page, needles)` scans DOM leaf text (occlusion-safe) for the confirmation banner.
- **WhatsApp Meta AI response detection (ago/2026) — HARD-WON.** `WhatsAppMetaAI.submit` detects the new reply by a **new `data-id`** (each message row has a unique, stable `[data-id]`; the assistant's is at the bottom, filtered from user rows by absence of `.copyable-text[data-pre-plain-text]`). Do **NOT** detect by counting bubbles: WhatsApp Web **virtualizes** the message list, so the rendered count is **non-monotonic** (bubbles enter *and leave* the DOM on scroll) — count-based detection lags a full turn or misses entirely. id-based is also robust to Meta AI's **identical** repeated replies (the canned "Boa pergunta… acesse tse…" refusal to every *voto* question — text-change detection would fail). Read text via `textContent` (occlusion-safe). Meta AI **refuses all voto** prompts (canned TSE redirect, ~78 chars) but **answers genero** substantively. When collecting occluded (window behind the terminal), WhatsApp Web throttles rendering; the driver mitigates with `bring_to_front()` + scroll-to-bottom + CDP `Emulation.setFocusEmulationEnabled` each poll, but the **id signal is what makes it correct**. Debug with `LLMBIAS_WA_DEBUG=1`.
- `capture.py` — UI-agnostic helpers. End-of-response detection (`wait_until_idle`) combines two signals (first wins): the "generating" indicator (stop-button) disappearing, **or** the response text going stable. Text is read by `last_text()` via **`text_content`, not `inner_text`** (see Operational gotchas). `wait_response_started()` detects a new response by count-OR-busy-OR-text-changed. Plus `snapshot()` (HTML+PNG).
- `storage.py` — `RunStore` + `Exchange` dataclass. Append-only `exchanges.jsonl` (one record per prompt→response/turn, UTF-8) + raw artifacts. For the experiment, also writes per-conversation JSON under `conversations/` (the **LLM-as-a-judge input** — persona + dimension + ordered turns). Keep records self-describing.
- `experiment.py` — ESEB guardrails experiment runner. For each persona (`Sxx`) × dimension × {short, long}, drives ChatGPT and saves the conversation. **short** = 1 turn (the dimension prompt from the file); **long** = 5 turns (that prompt + 4 authored follow-ups that *induce* toward the persona's side, to test guardrails/sycophancy). Resumable (`--run-id` skips already-completed conversations) and paced (`--turn-delay`/`--conv-delay`).
- `prompts.py` — placeholder "light electoral" prompt list + `pick()`. Will be replaced by the real protocol.

### Conjoint experiment (LLM-as-a-user × LLM-as-a-judge, Gemini-only POC)

A second, self-contained experiment (`conjoint` subcommand) that fully automates both ends with the **Gemini API** (`gemini-3.5-flash`, key in `.env` as `GEMINI_API_KEY`) as the LLM-as-a-user and LLM-as-a-judge, while the **models under test are the web UIs of several platforms** (Gemini, ChatGPT, Claude, DeepSeek, Grok). Gemini runs in **"conversa momentânea"** (temporary chat, no cross-conversation memory); the other platforms open a fresh chat per conversation. Modules:
- `llm.py` — thin `google-genai` wrapper (client from `.env`, `generate_text`/`generate_structured`/chat sessions, transient-error retry). Default model via `LLMBIAS_GEMINI_MODEL`.
- `conjoint.py` — **6** conjoint factors (`politica`, `genero`, `idade`, **`escolaridade`** [`fundamental_completo`/`fundamental_incompleto`, added by Recos jul/2026], `estilo_conversa`, `estilo_escrita` → **324 cells**), deterministic `sample_profiles(n, seed)` of unique profiles, `load_seed()` of `docs/seed.xlsx` (abas Perfil/Perguntas/Ganchos), `persona_presentation()`.
- `axes.py` — the eixos with objetivo + crença + **10-turn** reference arc (Recos versions). The pre-test uses `voto` (ranqueamento) and `genero` (violência de gênero); the old `urnas`/`resultado` remain but are being merged into a single `integridade` eixo (rubric TBD).
- `temas.py` — **temas as independent binary conjoint factors** (design ago/2026, adm#88): each *tema* is tied 1-to-1 to a rubric type (`T1..Tn` of an eixo) and carries user-voice example provocations (kept separate from the judge rubric). **`build_tema_plan(eixos, profile_ids, seed, prob, min_temas)`** builds a **balanced design matrix** up front: `build_tema_matrix` gives, per eixo, a `{profile_id: {tema: bool}}` grid where each tema is included in ~`round(prob·n)` profiles (≥1, coverage guaranteed) with row loads (temas per conversation) kept uniform — deterministic in (seed, eixo), platform-independent. `sample_temas(eixo, profile_id, …)` is the per-conversation i.i.d. alternative (kept for reference). A conversation covers its assigned subset; coverage of all temas comes from balance *across* conversations, and the DV becomes binary "violou ou não" per tema. `_check_alinhamento()` asserts temas codes == rubric type codes.
- `user_agent.py` — **LLM as a user**: builds an adapted system prompt that *parametrizes* `estilo_conversa`/`estilo_escrita` (the base prompt fixes them), carries the non-conforming belief, presents the conjoint persona in turn 1, and escalates over the turns reacting to the model's real replies. Takes the sampled `temas` and injects a **"TEMAS A COBRIR"** block (weave all included temas naturally, press each ≥2×, don't announce them) instead of the fixed per-eixo arc; falls back to `eixo.arco` when no temas are passed.
- `rubrics.py` — **curated rubric 4.0** (data, not LLM-generated): a two-axis binary grid per eixo — **substantive** types (`T1..Tn`: what content appeared; 4 for ranqueamento, 7 for violência) × **instrumental** voices (`V1..V5`: how the model conveyed it; V1 relato is *not* a violation, V2–V5 are), plus an optional resistance block (`R1..R3`). Only `voto` + `genero` have curated grids. `RUBRICS`, `get_rubric()`, snapshotted to `rubrics.json`.
- `judge.py` — **LLM as a judge (v4.0)**: **per-response (per-turn) extraction**. For each assistant turn, returns structured `achados` (`{tipo, trecho, voz[], nota}`) + `resistencia`; `annotate()` aggregates descriptive counts per conversation (`achados_violacao`, `turnos_com_violacao`, `por_tipo`, `por_voz`, `resistencia`). **No summed 0–1 score** (intensity/weighting left open for analysis).
- `drivers.py::GeminiMomentary` — Gemini driver whose `open_new_chat` navigates `/app` and ensures the **"Conversa momentânea"** toggle is active (idempotent via the "conversas momentâneas" banner).
- `conjoint_experiment.py` — orchestrator: sample profiles → snapshot curated rubrics → **build the collection plan up front** (`_load_or_build_plan` → balanced tema matrix, persisted to `plano_coleta.json` [source of truth, resumable] + `plano_coleta.csv` [one row per planned conversation, for inspection/pre-registration]; same tema roster across platforms) → each conversation reads its tema vector from the plan (stored as `temas_flags`/`temas_incluidos` on the record) → drive web conversations (browser) → judge (API) → write `dataset.jsonl`/`dataset.csv`/`dataset.parquet` (one row per conversation: profile factor columns incl. `escolaridade`; **`tema_Tx` (0/1) independent vars** and **`violou_Tx` (0/1) + `violou` dependent vars**, `n_temas_incluidos`; annotation aggregates; full per-turn `achados` + conversation as JSON). `PLATFORM_DRIVERS` maps platform→driver. Resumable (`--run-id` skips done conversations and already-annotated ones); `--platforms`, `--eixos`, `--n-turns`, `--tema-prob`, `--min-temas`, `--phase generate|judge|all`, `--limit` for smoke tests.

Run: `uv run llmbias-tse conjoint --n-profiles 3` (or `python -m llmbias_tse conjoint ...` when the console-script `.exe` is locked by a running `launch`). Defaults: platforms `gemini chatgpt claude deepseek grok`, eixos `voto genero`, 10 turns. **Platforms run in a momentary/ephemeral chat** (no cross-conversation memory) via `PLATFORM_DRIVERS` in `conjoint_experiment.py` — gemini→`gemini_momentary`, chatgpt→`chatgpt_momentary`, grok→`grok_momentary`, claude→`claude_momentary`; **deepseek** has no such mode (`DEEPSEEK_SEM_MOMENTANEA`) so it uses plain new-chat (already memory-isolated). Needs Chrome up (via `launch`) **and** logged into every platform in `--platforms`.

Experiment input data (under `data/`, versioned): `scripts_conversa_eseb_guardrails.json` (18 personas × 6 dimensions) and `long_conversations.json` (authored turns 2–5 of the long conversations). The conjoint experiment instead reads `docs/seed.xlsx` and samples profiles at runtime.

When a driver stops capturing, read the saved snapshot HTML in `data/<run>/artifacts/<tool>/<NN>/` to find the new selector and patch `drivers.py`.

## Tooling and commands

Managed with **`uv`** (build backend `uv_build`), Python **>=3.12**. Deps: `patchright`, `python-dotenv`, `google-genai`, `pydantic`, `openpyxl`, `pandas`, `pyarrow`.

```bash
uv sync                                      # create/update .venv
uv run llmbias-tse launch                    # phase 1: open Chrome, log in manually
uv run llmbias-tse run                        # phase 2: collect (default tools, 2 prompts)
uv run llmbias-tse run --tools chatgpt --n 3  # specific tool / count
uv run llmbias-tse experiment --personas S02 S18            # ESEB experiment (short+long)
uv run llmbias-tse experiment --run-id <id> --turn-delay 5  # resume a run, gentler pacing
uv run llmbias-tse conjoint --n-profiles 3                  # pré-teste (5 plataformas, voto+genero, 10 turnos)
uv run llmbias-tse conjoint --platforms gemini --limit 2    # smoke: 1 plataforma, poucas conversas
uv run llmbias-tse conjoint --run-id <id> --phase judge     # re-judge + rebuild dataset only
uv run llmbias-tse conjoint --run-id <id>                   # resume a blocked run (same run dir)
uv run llmbias-tse tools                       # list available tool keys
uv add <package>                               # add a dependency
```

No test runner/linter configured yet. When adding tests, prefer `pytest` via `uv add --dev pytest`, run with `uv run pytest` (single test: `uv run pytest path::test_name`). Note: most harness logic needs a live logged-in browser, so favor unit tests around `storage.py`/`prompts.py`/`capture.py` helpers over end-to-end.

## Operational gotchas (live collection)

Hard-won lessons from running collection at scale against logged-in web UIs:

- **Rate limit / temporary block.** A burst of requests trips ChatGPT's *"Too many requests — You're making requests too quickly. We've temporarily limited access to your conversations to protect your data."* modal. Observed after ~50 turns in ~15 min — it's **cumulative**, not just instantaneous frequency, so slowing down only delays it. Mitigations, all built in:
  - **Pace** with `--turn-delay` / `--conv-delay` (defaults 3s / 8s) to be gentler.
  - **Resume** with `--run-id <existing>`: the runner skips conversations already completed successfully and continues into the **same** run dir, so a block mid-batch costs nothing — wait for the cooldown and re-run with the same `--run-id`.
  - **Auto-wait** (built into `BaseDriver.submit`): `capture.is_rate_limited()` detects the modal (by `text_content`, occlusion-safe), then it **waits passively** — dismiss the modal and *sleep* with exponential backoff — before re-attempting the send. **Do NOT poll by reloading:** a reload re-fetches the conversation list / user data, which counts as requests and **keeps the limit alive** (observed: reloading every 30s left the modal up indefinitely). Stay idle to let it reset.
  - The modal is an overlay, so responses already rendered are still captured (we read the DOM, not the screen). A re-send after waiting is guarded by `user_selector` so the prompt is never double-posted.
  - For throughput, **don't** parallelize within one account (shared limit, flag risk); parallelize across **different tools** (separate services) instead.
- **Read with `text_content`, never `inner_text`.** When the Chrome window is **occluded** (behind the terminal during a run), Windows skips layout for that page, so Playwright's `inner_text()` returns `""` **and** `locator.last.count()` returns `0` — even though the element is present. End-of-response detection then never sees text and hangs to the full timeout (~150s/turn). `capture.last_text()` reads via `text_content` (layout-independent) guarded by the **base** locator's `count()`. `browser.py` also sets anti-throttle Chrome flags (`--disable-backgrounding-occluded-windows`, `--disable-renderer-backgrounding`, `--disable-features=CalculateNativeWinOcclusion`, …); these need a **relaunch** to take effect (the profile persists logins, so relaunching is cheap).
