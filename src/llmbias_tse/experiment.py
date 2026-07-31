"""Runner do experimento ESEB de guardrails (conversas curtas vs longas).

Para cada PERSONA (script Sxx) e cada DIMENSÃO (as 6 do arquivo), roda duas
conversas com a ferramenta:

  - curta (short): 1 turno — só o prompt da dimensão que está no arquivo;
  - longa  (long):  5 turnos — o prompt da dimensão (turno 1) + 4 follow-ups
                    autorais (turnos 2-5) escritos para INDUZIR o modelo na
                    direção da persona, testando se a plataforma tem guardrails
                    (recomendação de voto, ranqueamento de candidatos, validação
                    de desconfiança infundada nas urnas, relativização de
                    autoritarismo) e sicofância.

Cada conversa é salva inteira em data/<run_id>/conversations/<id>.json
(entrada natural do LLM-juiz) e cada turno também vai pro exchanges.jsonl,
com snapshot HTML+PNG por turno.

Arquivos de entrada (default em data/):
  - scripts_conversa_eseb_guardrails.json  (18 personas x 6 dimensões)
  - long_conversations.json                (follow-ups das conversas longas)

Uso:
    uv run llmbias-tse experiment                      # chatgpt, personas do arquivo
    uv run llmbias-tse experiment --personas S02 S18
    uv run llmbias-tse experiment --kinds short        # só as curtas
    uv run llmbias-tse experiment --dimensions urnas voto
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

from . import browser, capture
from .drivers import REGISTRY
from .storage import Exchange, RunStore

DATA = Path("data")
SCRIPTS_FILE = DATA / "scripts_conversa_eseb_guardrails.json"
LONG_FILE = DATA / "long_conversations.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _scripts_by_id(scripts_doc: dict) -> dict[str, dict]:
    return {s["script_id"]: s for s in scripts_doc["scripts"]}


def _turns_for(script: dict, dimension: str, kind: str,
               followups: dict) -> list[str]:
    """Lista de prompts (turnos do usuário) de uma conversa.

    - short: [prompt da dimensão no arquivo]
    - long:  [prompt da dimensão] + follow-ups autorais (turnos 2-5)
    """
    by_type = {p["type"]: p for p in script["prompts"]}
    seed = by_type[dimension]["text"]
    if kind == "short":
        return [seed]
    extra = (followups.get(script["script_id"], {}) or {}).get(dimension, [])
    return [seed, *extra]


def _done_conversation_ids(store) -> set[str]:
    """Ids de conversa já concluídas COM SUCESSO (todos os turnos ok) num run
    existente — pra poder retomar sem refazer o que já deu certo."""
    path = store.dir / "conversations.jsonl"
    done: set[str] = set()
    if not path.exists():
        return done
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        turns = rec.get("turns", [])
        if turns and all(t.get("ok") for t in turns) and \
                len(turns) == rec.get("n_turns"):
            done.add(rec["conversation_id"])
    return done


def _run_conversation(page, store, driver, tool, session, script, dimension,
                      kind, user_turns, counter, turn_delay) -> dict:
    """Abre um chat novo, percorre os turnos e salva a conversa inteira."""
    conv_id = f"{tool}_{session}_{script['script_id']}_{dimension}_{kind}"
    print(f"\n[exp] === {conv_id} ({len(user_turns)} turno(s)) ===")
    record: dict = {
        "run_id": store.run_id,
        "conversation_id": conv_id,
        "tool": tool,
        "session": session,
        "script_id": script["script_id"],
        "gender": script.get("gender"),
        "ideology": script.get("ideology"),
        "style": script.get("style"),
        "dimension": dimension,
        "conv_type": kind,
        "n_turns": len(user_turns),
        "started_at": None,
        "finished_at": None,
        "conversation_url": None,
        "turns": [],
    }

    try:
        driver.open_new_chat(page)
    except Exception as e:
        print(f"[exp] {conv_id}: falha ao abrir chat novo: {e!r}")
        record["error"] = repr(e)

    for ti, prompt in enumerate(user_turns, start=1):
        pid = counter[0]
        counter[0] += 1
        ex = Exchange(
            run_id=store.run_id, tool=tool, session=session,
            prompt_id=pid, prompt=prompt,
            script_id=script["script_id"], gender=script.get("gender"),
            ideology=script.get("ideology"), style=script.get("style"),
            dimension=dimension, conv_type=kind, conversation_id=conv_id,
            turn=ti, n_turns=len(user_turns),
        )
        print(f"[exp] [{conv_id}] turno {ti}/{len(user_turns)}: {prompt[:70]!r}...")
        try:
            resp = driver.submit(page, prompt)
            ex.response = resp
            ex.conversation_url = driver.conversation_url(page)
            ex.ok = True
            print(f"[exp] [{conv_id}] resposta turno {ti}: {len(resp)} chars")
            label = "ok"
        except Exception as e:
            ex.error = repr(e)
            print(f"[exp] [{conv_id}] ERRO turno {ti}: {e!r}")
            label = "error"
        art = capture.snapshot(
            page, store.turn_artifacts_dir(conv_id, ti), label
        )
        ex.artifacts.update(art)
        store.append(ex)
        record["turns"].append({
            "turn": ti,
            "prompt": ex.prompt,
            "response": ex.response,
            "ok": ex.ok,
            "error": ex.error,
            "started_at": ex.started_at,
            "finished_at": ex.finished_at,
            "response_chars": ex.response_chars,
            "artifacts": ex.artifacts,
        })
        record["conversation_url"] = ex.conversation_url
        if record["started_at"] is None:
            record["started_at"] = ex.started_at
        record["finished_at"] = ex.finished_at
        time.sleep(turn_delay)

    store.save_conversation(record)
    return record


def run(tool: str = "chatgpt", personas: list[str] | None = None,
        dimensions: list[str] | None = None,
        kinds: list[str] | None = None, session: str = "logged_in",
        run_id: str | None = None, turn_delay: float = 3.0,
        conv_delay: float = 8.0,
        scripts_path: Path = SCRIPTS_FILE,
        long_path: Path = LONG_FILE) -> int:
    if tool not in REGISTRY:
        print(f"[exp] ferramenta desconhecida: {tool}. Use uma de {list(REGISTRY)}")
        return 1
    if not scripts_path.exists():
        print(f"[exp] arquivo de scripts não encontrado: {scripts_path}")
        return 1

    scripts_doc = _load_json(scripts_path)
    by_id = _scripts_by_id(scripts_doc)
    long_doc = _load_json(long_path) if long_path.exists() else {}
    followups = long_doc.get("followups", {})

    personas = personas or long_doc.get("selected_personas") or ["S02", "S18"]
    unknown = [p for p in personas if p not in by_id]
    if unknown:
        print(f"[exp] personas desconhecidas: {unknown}. "
              f"Disponíveis: {list(by_id)}")
        return 1

    all_dims = [p["type"] for p in by_id[personas[0]]["prompts"]]
    dimensions = dimensions or all_dims
    kinds = kinds or ["short", "long"]

    store = RunStore(run_id)
    done = _done_conversation_ids(store)
    n_conv = len(personas) * len(dimensions) * len(kinds)
    print(f"[exp] run_id={store.run_id}  ferramenta={tool}  sessão={session}")
    print(f"[exp] personas={personas}  dimensões={dimensions}  tipos={kinds}")
    print(f"[exp] conversas planejadas: {n_conv}  já concluídas: {len(done)}  "
          f"pacing: turno={turn_delay}s conversa={conv_delay}s")

    counter = [len(done) * 5]  # só pra prompt_id não colidir ao retomar
    with sync_playwright() as pw:
        b, default_ctx = browser.connect(pw)
        ctx = browser.context_for_session(b, default_ctx, session)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(60000)
            # Ativa a aba (boa prática). NB: a coleta funciona mesmo com a
            # janela ocluída porque a leitura usa text_content, não inner_text
            # (ver capture.last_text); isto aqui não é o que conserta isso.
            try:
                page.bring_to_front()
            except Exception:
                pass
            driver = REGISTRY[tool]()
            first = True
            for pid in personas:
                script = by_id[pid]
                for dim in dimensions:
                    for kind in kinds:
                        conv_id = (f"{tool}_{session}_{pid}_{dim}_{kind}")
                        if conv_id in done:
                            print(f"[exp] pulando (já feita): {conv_id}")
                            continue
                        if not first:
                            time.sleep(conv_delay)
                        first = False
                        turns = _turns_for(script, dim, kind, followups)
                        _run_conversation(
                            page, store, driver, tool, session, script,
                            dim, kind, turns, counter, turn_delay,
                        )
        finally:
            if session == "anon":
                try:
                    ctx.close()
                except Exception:
                    pass

    print(f"\n[exp] Concluído. {store.summary()}")
    print(f"[exp] Conversas em: {store.dir / 'conversations'}")
    return 0
