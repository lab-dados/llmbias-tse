"""Runner do POC: conecta no Chrome já logado, manda alguns prompts em
cada ferramenta, captura as respostas e salva tudo (JSONL + artefatos).

Roda os mesmos prompts em uma ou mais SESSÕES:
    - logged_in: perfil persistente (suas contas logadas)
    - anon:      context isolado, sem cookies (versão deslogada)
Cada registro é marcado com a sessão, para o LLM-juiz comparar lado a lado.

Este é o esqueleto do e2e de coleta:
    launch (login manual)  ->  run (coleta)  ->  data/<run_id>/  ->  LLM-juiz

Uso:
    uv run llmbias-tse run                                  # logado, 2 prompts
    uv run llmbias-tse run --tools gemini --session both    # logado + deslogado
    uv run llmbias-tse run --tools chatgpt gemini --n 3
"""

from __future__ import annotations

import time

from patchright.sync_api import sync_playwright

from . import browser, capture, prompts
from .drivers import DEFAULT_TOOLS, REGISTRY
from .storage import Exchange, RunStore

SESSION_ALIASES = {
    "logged_in": ["logged_in"],
    "anon": ["anon"],
    "both": ["logged_in", "anon"],
}


def _get_page(ctx):
    """Reutiliza uma aba existente ou cria uma nova."""
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def _collect(page, store, tools, chosen_prompts, session) -> None:
    for tool in tools:
        driver = REGISTRY[tool]()
        print(f"\n[poc] === {tool} ({session}) ===")
        for i, prompt in enumerate(chosen_prompts):
            ex = Exchange(
                run_id=store.run_id, tool=tool, session=session,
                prompt_id=i, prompt=prompt,
            )
            print(f"[poc] [{tool}/{session}] prompt {i}: {prompt!r}")
            try:
                resp = driver.send(page, prompt)
                ex.response = resp
                ex.conversation_url = driver.conversation_url(page)
                ex.ok = True
                print(f"[poc] [{tool}/{session}] resposta: {len(resp)} chars")
                label = "ok"
            except Exception as e:
                ex.error = repr(e)
                print(f"[poc] [{tool}/{session}] ERRO: {e!r}")
                label = "error"
            art = capture.snapshot(
                page, store.artifacts_dir(session, tool, i), label
            )
            ex.artifacts.update(art)
            store.append(ex)
            time.sleep(1.0)


def run(tools: list[str], n: int, seed: int | None = None,
        session: str = "logged_in") -> int:
    tools = tools or DEFAULT_TOOLS
    unknown = [t for t in tools if t not in REGISTRY]
    if unknown:
        print(f"[poc] ferramentas desconhecidas: {unknown}")
        print(f"[poc] disponíveis: {list(REGISTRY)}")
        return 1
    if session not in SESSION_ALIASES:
        print(f"[poc] sessão inválida: {session}. Use: {list(SESSION_ALIASES)}")
        return 1
    sessions = SESSION_ALIASES[session]

    chosen_prompts = prompts.pick(n, seed=seed)
    store = RunStore()
    print(f"[poc] run_id={store.run_id}  ferramentas={tools}  "
          f"sessões={sessions}  prompts={len(chosen_prompts)}")

    with sync_playwright() as pw:
        b, default_ctx = browser.connect(pw)
        for sess in sessions:
            ctx = browser.context_for_session(b, default_ctx, sess)
            try:
                page = _get_page(ctx)
                page.set_default_timeout(60000)
                _collect(page, store, tools, chosen_prompts, sess)
            finally:
                if sess == "anon":
                    try:
                        ctx.close()  # fecha a janela anônima
                    except Exception:
                        pass

    print(f"\n[poc] Concluído. {store.summary()}")
    print(f"[poc] Artefatos e JSONL em: {store.dir}")
    return 0
