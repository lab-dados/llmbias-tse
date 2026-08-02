"""Análise dos itens da rubrica 4.0 (LLM-as-judge) sobre um run do conjoint.

Unidade de análise: a RESPOSTA do assistente (turno avaliado). Para cada turno,
marca-se a PRESENÇA (0/1) de cada item da rubrica:
  - tipos substantivos  Tn  (algum achado daquele tipo, qualquer voz)
  - vozes instrumentais Vn  (algum achado com aquela voz)
  - resistências        Rn  (bloco de resistência do turno)
e das células da grade tipo×voz.

Objetivos:
  (1) itens que NUNCA aparecem (candidatos a remoção);
  (2) itens REDUNDANTES: colunas 0/1 idênticas entre turnos (concordância
      completa, n10=n01=0) -> medem a mesma coisa. Distingue redundância
      "genuína" (co-ocorrem como 1) de "trivial" (ambos nunca aparecem).
Tudo no total (por eixo) e por plataforma. Mais leitura de comparabilidade e
variabilidade.

Uso: uv run python scripts/analise_rubrica.py [run_dir]
Gera <run_dir>/relatorio_rubrica.html e <run_dir>/analise_rubrica.json
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from llmbias_tse.rubrics import RESISTENCIAS, RUBRICS, VOZES

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/pretest1")
ANOT = RUN / "annotations"
CONV = RUN / "conversations"
EIXOS = ["voto", "genero"]


# ---------------------------------------------------------------- rótulos
def criteria(eixo: str):
    """Lista ordenada de (codigo, classe, rotulo) dos itens do eixo."""
    r = RUBRICS[eixo]
    out = []
    for t in r.tipos:
        out.append((t.codigo, "tipo", f"{t.codigo} · {t.tipo}"))
    for v in VOZES:
        marca = "" if v.violacao else " (não-violação)"
        out.append((v.codigo, "voz", f"{v.codigo} · {v.nome}{marca}"))
    for rr in RESISTENCIAS:
        out.append((rr.codigo, "resist", f"{rr.codigo} · resistência"))
    return out


def code_label(eixo):
    return {c: lab for c, _, lab in criteria(eixo)}


# ---------------------------------------------------------------- carga
def load():
    """Constrói as linhas por turno e a grade tipo×voz."""
    rows = []            # {platform, eixo, present:set}
    grid = defaultdict(Counter)   # (eixo, plat|'TODAS') -> Counter[(tipo,voz)]
    n_turns_grid = defaultdict(int)
    erros = 0
    for af in sorted(ANOT.glob("*.json")):
        a = json.loads(af.read_text(encoding="utf-8"))
        eixo = a["eixo"]
        conv_id = a.get("conversation_id") or af.stem
        platform = conv_id.rsplit("_", 2)[0]
        for t in a.get("turnos", []):
            if t.get("erro"):
                erros += 1
                continue
            present = set()
            cells = set()
            for ac in t.get("achados", []):
                tp = ac.get("tipo")
                vs = ac.get("voz", []) or []
                if tp:
                    present.add(tp)
                for v in vs:
                    present.add(v)
                    if tp:
                        cells.add((tp, v))
            for rr in t.get("resistencia", []) or []:
                present.add(rr)
            rows.append({"platform": platform, "eixo": eixo, "present": present})
            for c in cells:
                grid[(eixo, platform)][c] += 1
                grid[(eixo, "TODAS")][c] += 1
            n_turns_grid[(eixo, platform)] += 1
            n_turns_grid[(eixo, "TODAS")] += 1
    return rows, grid, n_turns_grid, erros


def resp_lengths():
    """Comprimento médio de resposta por (plataforma, eixo) — confundidor."""
    agg = defaultdict(list)
    for cf in sorted(CONV.glob("*.json")):
        d = json.loads(cf.read_text(encoding="utf-8"))
        eixo = d.get("eixo") or ""
        platform = d.get("platform") or cf.stem.rsplit("_", 2)[0]
        for t in d.get("turns", []):
            if t.get("ok"):
                agg[(platform, eixo)].append(len((t.get("response") or "")))
    return {k: (sum(v) / len(v) if v else 0) for k, v in agg.items()}


# ---------------------------------------------------------------- estatística
def pair_stats(a, b):
    n11 = n10 = n01 = n00 = 0
    for x, y in zip(a, b):
        if x and y:
            n11 += 1
        elif x and not y:
            n10 += 1
        elif not x and y:
            n01 += 1
        else:
            n00 += 1
    n = n11 + n10 + n01 + n00
    agree = (n11 + n00) / n if n else 0.0
    jac_d = n11 + n10 + n01
    jac = (n11 / jac_d) if jac_d else None
    den = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
    phi = ((n11 * n00 - n10 * n01) / den) if den else None
    return dict(n11=n11, n10=n10, n01=n01, n00=n00, agree=agree, jac=jac, phi=phi)


def analyse():
    rows, grid, n_turns_grid, erros = load()
    rlen = resp_lengths()
    platforms = sorted({r["platform"] for r in rows})
    res = {"platforms": platforms, "erros_juiz": erros, "eixos": {}}

    for eixo in EIXOS:
        crit = criteria(eixo)
        codes = [c for c, _, _ in crit]
        erows = [r for r in rows if r["eixo"] == eixo]
        n_all = len(erows)
        # frequência: contagem por (código, plataforma) e total
        freq = {}  # code -> {plat: (count, n)}; 'TODAS'
        for code in codes:
            d = {}
            for plat in platforms + ["TODAS"]:
                sub = erows if plat == "TODAS" else [r for r in erows
                                                     if r["platform"] == plat]
                cnt = sum(1 for r in sub if code in r["present"])
                d[plat] = (cnt, len(sub))
            freq[code] = d

        # colunas binárias (todas as plataformas) p/ redundância
        cols = {code: [1 if code in r["present"] else 0 for r in erows]
                for code in codes}
        pairs = []
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                ca, cb = codes[i], codes[j]
                st = pair_stats(cols[ca], cols[cb])
                st["a"], st["b"] = ca, cb
                pairs.append(st)

        # grade tipo×voz (total)
        gcells = grid[(eixo, "TODAS")]
        # redundância por plataforma (colunas idênticas por plataforma)
        per_plat_ident = {}
        for plat in platforms:
            sub = [r for r in erows if r["platform"] == plat]
            pcols = {code: [1 if code in r["present"] else 0 for r in sub]
                     for code in codes}
            idents = []
            for i in range(len(codes)):
                for j in range(i + 1, len(codes)):
                    ca, cb = codes[i], codes[j]
                    st = pair_stats(pcols[ca], pcols[cb])
                    if st["n10"] == 0 and st["n01"] == 0 and st["n11"] > 0:
                        idents.append((ca, cb, st["n11"], len(sub)))
            per_plat_ident[plat] = idents

        res["eixos"][eixo] = {
            "titulo": RUBRICS[eixo].titulo,
            "n_turnos": n_all,
            "criteria": crit,
            "freq": freq,
            "pairs": pairs,
            "grid_cells": {f"{t}|{v}": c for (t, v), c in gcells.items()},
            "n_turnos_grid": {p: n_turns_grid[(eixo, p)]
                              for p in platforms + ["TODAS"]},
            "per_plat_ident": per_plat_ident,
        }
    res["resp_len"] = {f"{p}|{e}": round(v) for (p, e), v in rlen.items()}
    return res


if __name__ == "__main__":
    out = analyse()
    (RUN / "analise_rubrica.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("análise salva em", RUN / "analise_rubrica.json")
    print("plataformas:", out["platforms"])
    for eixo in EIXOS:
        e = out["eixos"][eixo]
        print(f"\n[{eixo}] {e['n_turnos']} turnos")
        never = [c for c in [cc for cc, _, _ in e["criteria"]]
                 if e["freq"][c]["TODAS"][0] == 0]
        print("  nunca aparecem (total):", never or "nenhum")
        ident = [(p["a"], p["b"], p["n11"]) for p in e["pairs"]
                 if p["n10"] == 0 and p["n01"] == 0 and p["n11"] > 0]
        print("  pares idênticos com co-ocorrência (redundância genuína):",
              ident or "nenhum")
