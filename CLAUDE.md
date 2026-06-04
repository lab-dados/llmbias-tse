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
- `drivers.py` — one driver class per tool in `REGISTRY` (`chatgpt`, `gemini`, `claude`, `metaai`, `whatsapp_metaai`). Each holds the **per-UI selectors** (composer + assistant-message containers). **These selectors drift and are the thing to fix when capture breaks.** `BaseDriver.send()` = open new chat → type → Enter → wait for response; WhatsApp overrides it.
- `capture.py` — UI-agnostic helpers. Key idea: responses **stream**, so `wait_stable_text()` polls the last response bubble and treats it as done when the text stops changing (no reliance on tool-specific "stop" buttons). Plus `snapshot()` (HTML+PNG).
- `storage.py` — `RunStore` + `Exchange` dataclass. Append-only `exchanges.jsonl` (one record per prompt→response, UTF-8) + raw artifacts per exchange. This is the **LLM-as-a-judge input**, so keep records self-describing.
- `prompts.py` — placeholder "light electoral" prompt list + `pick()`. Will be replaced by the real protocol.

When a driver stops capturing, read the saved snapshot HTML in `data/<run>/artifacts/<tool>/<NN>/` to find the new selector and patch `drivers.py`.

## Tooling and commands

Managed with **`uv`** (build backend `uv_build`), Python **>=3.12**. Deps: `patchright`, `python-dotenv`.

```bash
uv sync                                      # create/update .venv
uv run llmbias-tse launch                    # phase 1: open Chrome, log in manually
uv run llmbias-tse run                        # phase 2: collect (default tools, 2 prompts)
uv run llmbias-tse run --tools chatgpt --n 3  # specific tool / count
uv run llmbias-tse tools                       # list available tool keys
uv add <package>                               # add a dependency
```

No test runner/linter configured yet. When adding tests, prefer `pytest` via `uv add --dev pytest`, run with `uv run pytest` (single test: `uv run pytest path::test_name`). Note: most harness logic needs a live logged-in browser, so favor unit tests around `storage.py`/`prompts.py`/`capture.py` helpers over end-to-end.
