"""Runner do experimento de CONJOINT ANALYSIS (pré-teste multi-plataforma).

Pipeline:
  1. Sorteia N perfis únicos (6 fatores, incl. escolaridade) de forma
     determinística.
  2. Carrega a rubrica curada 4.0 (grade tipo × voz) de cada eixo — só há
     rubrica para `voto` (ranqueamento) e `genero` (violência de gênero).
  3. Para cada plataforma × perfil × eixo, conduz uma conversa de N turnos
     (default 10) contra a plataforma sob teste no browser: o LLM as a user
     (API gemini-3.5-flash) gera cada turno reagindo à resposta real da
     plataforma, escalando a posição não conforme. O Gemini roda em conversa
     momentânea (sem memória); as demais plataformas abrem um chat novo a cada
     conversa.
  4. Aplica o LLM as a judge (v4.0) a cada conversa: extrai achados POR
     RESPOSTA (tipo × voz) e agrega contagens descritivas (sem escore somado).
  5. Escreve a base final (uma linha por conversa) em dataset.jsonl/csv/parquet.

Tudo sob data/<run_id>/. Resumível: conversas já concluídas e anotadas são
puladas ao reusar --run-id.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd
from patchright.sync_api import sync_playwright

from . import browser, capture, llm
from .axes import EIXOS
from .conjoint import Profile, load_seed, persona_presentation, sample_profiles
from .drivers import REGISTRY
from .judge import annotate
from .rubrics import RUBRICS, RubricGrid, get_rubric
from .storage import RunStore, _now_iso
from .user_agent import UserAgent

# Plataforma -> (driver no REGISTRY, rótulo de modo de isolamento).
# Isolamento de memória entre conversas (para não contaminar o experimento),
# todos verificados ao vivo (jul/2026):
#   gemini  -> conversa momentânea
#   chatgpt -> conversa temporária (?temporary-chat=true)
#   grok    -> conversa privada (Switch to Private Chat)
#   claude  -> conversa incognito (Use incognito -> /new?incognito=)
#   deepseek-> NÃO tem modo temporário; usa chat novo. É isolado por não ter
#             memória entre conversas (sem "reference chat history"); a única
#             diferença é que a conversa fica salva no histórico (não afeta a
#             independência entre conversas). Ver DEEPSEEK_SEM_MOMENTANEA.
PLATFORM_DRIVERS: dict[str, tuple[str, str]] = {
    "gemini": ("gemini_momentary", "momentanea"),
    "chatgpt": ("chatgpt_momentary", "temporaria"),
    "grok": ("grok_momentary", "privada"),
    "claude": ("claude_momentary", "incognito"),
    "deepseek": ("deepseek", "chat_novo"),
}

# DeepSeek não oferece conversa temporária/privada na UI (jul/2026). Um chat
# novo já é isolado (a plataforma não tem memória entre conversas), mas fica
# salvo no histórico da conta.
DEEPSEEK_SEM_MOMENTANEA = True

DEFAULT_PLATFORMS = ["gemini", "chatgpt", "claude", "deepseek", "grok"]
DEFAULT_EIXOS = list(RUBRICS.keys())  # ["voto", "genero"]
DEFAULT_N_TURNS = 10


# --------------------------------------------------------------------------
# Persistência auxiliar
# --------------------------------------------------------------------------

def _save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _load_or_sample_profiles(store: RunStore, n: int, seed: int) -> list[Profile]:
    path = store.dir / "profiles.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        print(f"[conjoint] reusando {len(raw)} perfis de {path}")
        return [Profile(**p) for p in raw]
    profiles = sample_profiles(n, seed=seed)
    _save_json(path, [asdict(p) for p in profiles])
    print(f"[conjoint] sorteados {len(profiles)} perfis (seed={seed}) -> {path}")
    return profiles


def _snapshot_rubrics(store: RunStore, eixos: list[str]) -> dict[str, RubricGrid]:
    rubrics = {e: get_rubric(e) for e in eixos}
    path = store.dir / "rubrics.json"
    if not path.exists():
        _save_json(path, {k: r.to_dict() for k, r in rubrics.items()})
        print(f"[conjoint] rubricas 4.0 (curadas) registradas em {path}")
    return rubrics


def _conv_path(store: RunStore, conv_id: str) -> Path:
    return store.dir / "conversations" / f"{conv_id}.json"


def _conv_done(store: RunStore, conv_id: str, n_turns: int) -> bool:
    p = _conv_path(store, conv_id)
    if not p.exists():
        return False
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    turns = rec.get("turns", [])
    return len(turns) == n_turns and all(t.get("ok") for t in turns)


# --------------------------------------------------------------------------
# Fase 1 — geração das conversas (browser + LLM as a user)
# --------------------------------------------------------------------------

def _run_one_conversation(page, store, driver, platform, mode, profile: Profile,
                          eixo_key: str, seed_data, model, n_turns: int,
                          turn_delay: float) -> dict:
    eixo = EIXOS[eixo_key]
    conv_id = f"{platform}_{profile.id}_{eixo_key}"
    print(f"\n[conjoint] === {conv_id} | {profile.fatores()} ===")
    record = {
        "run_id": store.run_id,
        "conversation_id": conv_id,
        "platform": platform,
        "mode": mode,
        "model_user_agent": model,
        "profile": asdict(profile),
        "eixo": eixo_key,
        "tema": eixo.tema,
        "persona": persona_presentation(profile),
        "n_turns": n_turns,
        "started_at": _now_iso(),
        "finished_at": None,
        "conversation_url": None,
        "turns": [],
    }
    try:
        driver.open_new_chat(page)
    except Exception as e:
        # NÃO roda os turnos se o chat isolado não abriu: em modo normal isso
        # vazaria a conversa ao histórico (memória entre conversas). Salva sem
        # turnos -> não conta como concluída -> retomada refaz.
        print(f"[conjoint] {conv_id}: ABORTADA — chat isolado não abriu: {e!r}")
        record["error"] = repr(e)
        record["finished_at"] = _now_iso()
        store.save_conversation(record)
        return record

    ua = UserAgent(profile, eixo, seed_data, n_turns=n_turns, model=model)
    prev_response: str | None = None
    for ti in range(1, n_turns + 1):
        t0 = _now_iso()
        try:
            user_msg = ua.next_turn(prev_response)
        except Exception as e:
            print(f"[conjoint] [{conv_id}] ERRO ao gerar turno {ti}: {e!r}")
            record["turns"].append({
                "turn": ti, "prompt": "", "response": "", "ok": False,
                "error": f"user_agent: {e!r}", "started_at": t0,
                "finished_at": _now_iso(), "response_chars": 0, "artifacts": {},
            })
            break
        ok, err, resp = True, None, ""
        try:
            resp = driver.submit(page, user_msg)
        except Exception as e:
            ok, err = False, repr(e)
            print(f"[conjoint] [{conv_id}] ERRO no turno {ti} (web): {e!r}")
        art = capture.snapshot(
            page, store.turn_artifacts_dir(conv_id, ti),
            "ok" if ok else "error",
        )
        print(f"[conjoint] [{conv_id}] turno {ti}/{n_turns}: "
              f"user={user_msg[:60]!r} -> resp={len(resp)} chars ok={ok}")
        record["turns"].append({
            "turn": ti,
            "prompt": user_msg,
            "response": resp,
            "ok": ok,
            "error": err,
            "started_at": t0,
            "finished_at": _now_iso(),
            "response_chars": len(resp),
            "artifacts": art,
        })
        record["conversation_url"] = driver.conversation_url(page)
        record["finished_at"] = _now_iso()
        if not ok:
            break
        prev_response = resp
        time.sleep(turn_delay)

    store.save_conversation(record)
    return record


def generate_conversations(store: RunStore, profiles, platforms, eixos,
                           seed_data, model, n_turns, turn_delay, conv_delay,
                           limit=None) -> None:
    planned = [(pl, p, e)
               for pl in platforms for p in profiles for e in eixos]
    todo = [(pl, p, e) for (pl, p, e) in planned
            if not _conv_done(store, f"{pl}_{p.id}_{e}", n_turns)]
    if limit:
        todo = todo[:limit]
    print(f"[conjoint] conversas planejadas: {len(planned)} | "
          f"a fazer agora: {len(todo)} | plataformas: {platforms} | "
          f"turnos/conversa: {n_turns}")
    if not todo:
        print("[conjoint] nada a gerar (todas já concluídas).")
        return

    drivers = {pl: REGISTRY[PLATFORM_DRIVERS[pl][0]]() for pl in platforms}
    modes = {pl: PLATFORM_DRIVERS[pl][1] for pl in platforms}

    with sync_playwright() as pw:
        b, ctx = browser.connect(pw)
        # Cria a PRÓPRIA aba PRIMEIRO (o contexto nunca fica sem página), depois
        # fecha as abas remanescentes (de execuções anteriores que caíram/foram
        # mortas antes de fechar a própria aba). Ordem importa: fechar a última
        # página do contexto CDP mata o contexto e faz o new_page falhar
        # (TargetClosedError). Sem essa limpeza, os alvos se acumulam e TRAVAM o
        # connect_over_cdp seguinte. Seguro porque a coleta roda SERIAL.
        page = ctx.new_page()
        for _pg in list(ctx.pages):
            if _pg is page:
                continue
            try:
                _pg.close()
            except Exception:
                pass
        page.set_default_timeout(60000)
        try:
            for i, (pl, p, e) in enumerate(todo):
                if i:
                    time.sleep(conv_delay)
                _run_one_conversation(page, store, drivers[pl], pl, modes[pl],
                                      p, e, seed_data, model, n_turns, turn_delay)
        finally:
            try:
                page.close()
            except Exception:
                pass


# --------------------------------------------------------------------------
# Fase 2 — julgamento (API, extração por turno)
# --------------------------------------------------------------------------

def judge_conversations(store: RunStore, rubrics: dict[str, RubricGrid],
                        model) -> None:
    conv_dir = store.dir / "conversations"
    anot_dir = store.dir / "annotations"
    anot_dir.mkdir(parents=True, exist_ok=True)
    convs = sorted(conv_dir.glob("*.json"))
    print(f"[conjoint] julgando {len(convs)} conversas...")
    for cp in convs:
        rec = json.loads(cp.read_text(encoding="utf-8"))
        conv_id = rec["conversation_id"]
        out_path = anot_dir / f"{conv_id}.json"
        if out_path.exists():
            continue
        if rec["eixo"] not in rubrics:
            continue
        if not (rec.get("turns") and any(t.get("ok") for t in rec["turns"])):
            print(f"[conjoint] pulando {conv_id} (sem turnos válidos)")
            continue
        rubric = rubrics[rec["eixo"]]
        try:
            anot = annotate(rec, rubric, model=model)
        except Exception as e:
            print(f"[conjoint] ERRO ao julgar {conv_id}: {e!r}")
            continue
        anot["conversation_id"] = conv_id
        _save_json(out_path, anot)
        print(f"[conjoint] {conv_id}: {anot['achados_violacao']} achados de "
              f"violação em {anot['turnos_com_violacao']}/"
              f"{anot['n_turnos_avaliados']} turnos")


# --------------------------------------------------------------------------
# Fase 3 — base final
# --------------------------------------------------------------------------

def build_dataset(store: RunStore, rubrics: dict[str, RubricGrid]) -> Path:
    conv_dir = store.dir / "conversations"
    anot_dir = store.dir / "annotations"
    rows = []
    for cp in sorted(conv_dir.glob("*.json")):
        rec = json.loads(cp.read_text(encoding="utf-8"))
        conv_id = rec["conversation_id"]
        ap = anot_dir / f"{conv_id}.json"
        anot = json.loads(ap.read_text(encoding="utf-8")) if ap.exists() else None
        prof = rec["profile"]
        rows.append({
            "id": conv_id,
            "run_id": rec["run_id"],
            "platform": rec["platform"],
            "mode": rec["mode"],
            "eixo": rec["eixo"],
            "tema": rec["tema"],
            # fatores do perfil (uma coluna cada)
            "politica": prof["politica"],
            "genero": prof["genero"],
            "idade": prof["idade"],
            "escolaridade": prof["escolaridade"],
            "estilo_conversa": prof["estilo_conversa"],
            "estilo_escrita": prof["estilo_escrita"],
            "perfil_id": prof["id"],
            # agregados descritivos da anotação (sem escore somado)
            "n_turnos_avaliados": anot["n_turnos_avaliados"] if anot else None,
            "achados_total": anot["achados_total"] if anot else None,
            "achados_violacao": anot["achados_violacao"] if anot else None,
            "turnos_com_violacao": anot["turnos_com_violacao"] if anot else None,
            "n_turns_ok": sum(1 for t in rec["turns"] if t.get("ok")),
            # dicts completos (por tipo / voz / resistência + achados + conversa)
            "por_tipo": json.dumps(anot["por_tipo"] if anot else {},
                                   ensure_ascii=False),
            "por_voz": json.dumps(anot["por_voz"] if anot else {},
                                  ensure_ascii=False),
            "resistencia": json.dumps(anot["resistencia"] if anot else {},
                                      ensure_ascii=False),
            "achados": json.dumps(anot["turnos"] if anot else [],
                                  ensure_ascii=False),
            "conversa": json.dumps(rec["turns"], ensure_ascii=False),
            "persona": rec["persona"],
        })
    df = pd.DataFrame(rows)
    jsonl = store.dir / "dataset.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    csv = store.dir / "dataset.csv"
    df.to_csv(csv, index=False, encoding="utf-8-sig", sep=";")
    try:
        df.to_parquet(store.dir / "dataset.parquet", index=False)
    except Exception as e:
        print(f"[conjoint] (parquet pulado: {e!r})")
    print(f"[conjoint] base final: {len(rows)} linhas -> {csv}")
    if not df.empty and df["achados_violacao"].notna().any():
        print("[conjoint] achados de violação (média) por eixo × plataforma:")
        piv = (df.dropna(subset=["achados_violacao"])
                 .groupby(["eixo", "platform"])["achados_violacao"]
                 .mean().round(2))
        print(piv.to_string())
    return csv


# --------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------

def run(n_profiles: int = 3, seed: int = 2026,
        platforms: list[str] | None = None, eixos: list[str] | None = None,
        run_id: str | None = None, model: str | None = None,
        n_turns: int = DEFAULT_N_TURNS, turn_delay: float = 3.0,
        conv_delay: float = 8.0, limit: int | None = None,
        phase: str = "all") -> int:
    platforms = platforms or list(DEFAULT_PLATFORMS)
    eixos = eixos or list(DEFAULT_EIXOS)
    model = model or llm.DEFAULT_MODEL

    unknown_pl = [p for p in platforms if p not in PLATFORM_DRIVERS]
    if unknown_pl:
        print(f"[conjoint] plataformas desconhecidas: {unknown_pl}. "
              f"Disponíveis: {list(PLATFORM_DRIVERS)}")
        return 1
    unknown_ex = [e for e in eixos if e not in RUBRICS]
    if unknown_ex:
        print(f"[conjoint] eixos sem rubrica curada 4.0: {unknown_ex}. "
              f"Disponíveis: {list(RUBRICS)}")
        return 1

    store = RunStore(run_id)
    print(f"[conjoint] run_id={store.run_id} | plataformas={platforms} | "
          f"eixos={eixos} | perfis={n_profiles} | turnos={n_turns} | "
          f"modelo juiz/usuário={model}")
    seed_data = load_seed()
    profiles = _load_or_sample_profiles(store, n_profiles, seed)
    rubrics = _snapshot_rubrics(store, eixos)

    if phase in ("all", "generate"):
        generate_conversations(store, profiles, platforms, eixos, seed_data,
                               model, n_turns, turn_delay, conv_delay,
                               limit=limit)
    if phase in ("all", "judge"):
        judge_conversations(store, rubrics, model)
        build_dataset(store, rubrics)

    print(f"\n[conjoint] Concluído. Dados em: {store.dir}")
    return 0
