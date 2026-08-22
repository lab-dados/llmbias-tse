"""Análise da CONCORDÂNCIA ENTRE JUÍZES do painel (pré-teste ago/2026).

Produz o JSON que alimenta o relatório. O que se quer responder:

  1. Os três juízes medem a mesma coisa? (matriz de confusão por par, κ)
  2. Onde eles divergem — por eixo, por tipo?
  3. Quanto a REGRA DE AGREGAÇÃO muda o resultado final (maioria × união ×
     interseção × cada juiz sozinho)?
  4. A divergência é de conversa ou de turno? (a mesma conta nas duas
     granularidades)

Duas unidades de análise, deliberadamente:
  - CONVERSA × TIPO: o juiz marcou aquele tipo em algum turno da conversa?
  - TURNO × TIPO: o juiz marcou aquele tipo naquele turno?
A segunda é mais exigente (exige concordar em QUAL turno), e a diferença entre
as duas diz se os juízes discordam do fato ou de onde ele está.

Uso: uv run python scripts/analise_juizes.py [run_dir] > analise_juizes.json
"""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/pretest3")
ANOT = RUN / "annotations"
CONV = RUN / "conversations"
JUIZES = ["gemini", "opus", "gpt"]


def _kappa(a: list[int], b: list[int]) -> float | None:
    """Kappa de Cohen para duas listas binárias pareadas."""
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa1, pb1 = sum(a) / n, sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if pe == 1:
        return 1.0 if po == 1 else 0.0
    return (po - pe) / (1 - pe)


def _fleiss(marcas: list[list[int]]) -> float | None:
    """Kappa de Fleiss para N itens avaliados pelos MESMOS k juízes."""
    itens = [m for m in marcas if len(m) >= 2]
    if not itens:
        return None
    k = len(itens[0])
    if any(len(m) != k for m in itens) or k < 2:
        return None
    n = len(itens)
    # P_i: concordância dentro do item
    pis = []
    for m in itens:
        n1 = sum(m)
        n0 = k - n1
        pis.append((n1 * (n1 - 1) + n0 * (n0 - 1)) / (k * (k - 1)))
    pbar = sum(pis) / n
    p1 = sum(sum(m) for m in itens) / (n * k)
    pe = p1 ** 2 + (1 - p1) ** 2
    if pe == 1:
        return 1.0 if pbar == 1 else 0.0
    return (pbar - pe) / (1 - pe)


def carregar():
    """Devolve as marcações nas duas granularidades.

    conversa: [{eixo, plataforma, tipo, marcas:{juiz:0/1}}]
    turno:    [{eixo, plataforma, tipo, turno, marcas:{juiz:0/1}}]
    """
    conversa, turno = [], []
    for f in sorted(ANOT.glob("*.json")):
        a = json.loads(f.read_text(encoding="utf-8"))
        cid = a["conversation_id"]
        plat = cid.rsplit("_", 2)[0]
        eixo = a["eixo"]
        pj = a.get("por_juiz") or {}
        validos = {k: v for k, v in pj.items() if "erro" not in v}
        if len(validos) < 2:
            continue
        tipos = list(a.get("por_tipo") or {})

        # nível conversa
        for t in tipos:
            marcas = {j: int((v.get("por_tipo") or {}).get(t, 0) > 0)
                      for j, v in validos.items()}
            conversa.append({"eixo": eixo, "plataforma": plat, "tipo": t,
                             "conversation_id": cid, "marcas": marcas})

        # nível turno
        turnos_ids = sorted({tt.get("turn")
                             for v in validos.values()
                             for tt in (v.get("turnos") or [])
                             if tt.get("turn") is not None})
        for n in turnos_ids:
            por_juiz_tipos = {}
            for j, v in validos.items():
                marcados = set()
                for tt in (v.get("turnos") or []):
                    if tt.get("turn") != n:
                        continue
                    for ac in (tt.get("achados") or []):
                        if ac.get("violacao"):
                            marcados.add(ac.get("tipo"))
                por_juiz_tipos[j] = marcados
            for t in tipos:
                marcas = {j: int(t in s) for j, s in por_juiz_tipos.items()}
                turno.append({"eixo": eixo, "plataforma": plat, "tipo": t,
                              "turno": n, "conversation_id": cid,
                              "marcas": marcas})
    return conversa, turno


def confusao(regs, j1, j2):
    """Matriz 2×2 entre dois juízes: [[nn, ns], [sn, ss]]."""
    m = [[0, 0], [0, 0]]
    for r in regs:
        if j1 in r["marcas"] and j2 in r["marcas"]:
            m[r["marcas"][j1]][r["marcas"][j2]] += 1
    return m


def pares(regs):
    out = []
    for j1, j2 in combinations(JUIZES, 2):
        sub = [r for r in regs if j1 in r["marcas"] and j2 in r["marcas"]]
        a = [r["marcas"][j1] for r in sub]
        b = [r["marcas"][j2] for r in sub]
        if not a:
            continue
        conc = sum(1 for x, y in zip(a, b) if x == y) / len(a)
        out.append({
            "par": f"{j1}×{j2}", "n": len(a),
            "concordancia": conc, "kappa": _kappa(a, b),
            "confusao": confusao(sub, j1, j2),
            "taxa_j1": sum(a) / len(a), "taxa_j2": sum(b) / len(b),
        })
    return out


def agregacoes(regs):
    """Como a taxa final muda conforme a regra de agregação."""
    def taxa(f):
        vals = [f(list(r["marcas"].values())) for r in regs if r["marcas"]]
        return sum(vals) / len(vals) if vals else None
    fora = {
        "maioria": lambda v: int(sum(v) * 2 >= len(v)),
        "uniao": lambda v: int(any(v)),
        "intersecao": lambda v: int(all(v)),
    }
    out = {k: taxa(f) for k, f in fora.items()}
    for j in JUIZES:
        vals = [r["marcas"][j] for r in regs if j in r["marcas"]]
        out[f"so_{j}"] = (sum(vals) / len(vals)) if vals else None
    return out


def bloco(regs, chave=None):
    """Estatísticas de um conjunto de marcações, opcionalmente agrupado."""
    if chave is None:
        marcas = [list(r["marcas"].values()) for r in regs]
        return {
            "n": len(regs),
            "fleiss": _fleiss(marcas),
            "unanime": (sum(1 for m in marcas if len(set(m)) == 1) / len(marcas)
                        if marcas else None),
            "pares": pares(regs),
            "agregacoes": agregacoes(regs),
        }
    grupos = {}
    for r in regs:
        grupos.setdefault(r[chave], []).append(r)
    return {k: bloco(v) for k, v in sorted(grupos.items())}


def main() -> None:
    conversa, turno = carregar()
    saida = {
        "run": RUN.name,
        "n_conversas": len({r["conversation_id"] for r in conversa}),
        "nivel_conversa": {
            "geral": bloco(conversa),
            "por_eixo": bloco(conversa, "eixo"),
            "por_plataforma": bloco(conversa, "plataforma"),
            "por_plataforma_eixo": {
                p: bloco([r for r in conversa if r["plataforma"] == p], "eixo")
                for p in sorted({r["plataforma"] for r in conversa})
            },
            "por_eixo_tipo": {
                e: bloco([r for r in conversa if r["eixo"] == e], "tipo")
                for e in sorted({r["eixo"] for r in conversa})
            },
        },
        "nivel_turno": {
            "geral": bloco(turno),
            "por_eixo": bloco(turno, "eixo"),
            "por_plataforma": bloco(turno, "plataforma"),
            "por_plataforma_eixo": {
                p: bloco([r for r in turno if r["plataforma"] == p], "eixo")
                for p in sorted({r["plataforma"] for r in turno})
            },
            "por_eixo_tipo": {
                e: bloco([r for r in turno if r["eixo"] == e], "tipo")
                for e in sorted({r["eixo"] for r in turno})
            },
        },
    }
    print(json.dumps(saida, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
