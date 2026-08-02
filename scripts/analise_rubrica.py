"""Análise dos itens da rubrica 4.0 (LLM-as-judge) sobre um run do conjoint.

IMPORTANTE (níveis): a rubrica é uma grade tipo×voz. Cada achado do juiz é
UM tipo (Tn) + um VETOR de vozes (Vn) que o qualificam. Logo tipo e voz vivem
em níveis diferentes e NÃO se comparam entre si (a voz descreve o tipo). A
redundância é analisada DENTRO de cada eixo da grade:
  - entre TIPOS   (T-vs-T): unidade = resposta (turno). Dois tipos redundantes
    aparecem sempre nas mesmas respostas.
  - entre VOZES   (V-vs-V): unidade = ACHADO (trecho). Duas vozes redundantes
    são atribuídas sempre ao mesmo trecho.
  - entre RESIST. (R-vs-R): unidade = resposta.
A relação tipo↔voz é descrita pelo PERFIL DE VOZES POR TIPO (para cada T, o
vetor de Vs), não por concordância.

Cobertura (objetivo 1): presença por resposta de cada item (candidatos a
remoção = nunca aparecem). Redundância (objetivo 2): kappa/phi dentro de classe.

Uso: uv run python scripts/analise_rubrica.py [run_dir]
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
VCODES = [v.codigo for v in VOZES]
RCODES = [r.codigo for r in RESISTENCIAS]


def criteria(eixo: str):
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


# ---------------------------------------------------------------- carga
def load():
    turns = []     # {platform, eixo, present:set}  (nível resposta)
    achados = []   # {platform, eixo, tipo, voz:set} (nível achado)
    n_turns = defaultdict(int)     # (eixo, plat|'TODAS') -> nº respostas
    n_ach = defaultdict(int)       # (eixo, plat|'TODAS') -> nº achados
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
            for ac in t.get("achados", []):
                tp = ac.get("tipo")
                vs = set(ac.get("voz", []) or [])
                if tp:
                    present.add(tp)
                    achados.append({"platform": platform, "eixo": eixo,
                                    "tipo": tp, "voz": vs})
                    n_ach[(eixo, platform)] += 1
                    n_ach[(eixo, "TODAS")] += 1
                present |= vs
            for rr in t.get("resistencia", []) or []:
                present.add(rr)
            turns.append({"platform": platform, "eixo": eixo, "present": present})
            n_turns[(eixo, platform)] += 1
            n_turns[(eixo, "TODAS")] += 1
    return turns, achados, n_turns, n_ach, erros


FATORES = ["politica", "idade", "escolaridade", "estilo_conversa",
           "estilo_escrita", "genero"]


def load_scores():
    """Escore de violação por conversa. Fatores vêm do dataset.jsonl; os escores
    são computados das anotações (nível turno).
      taxa  = células (turno x tipo) com violação / (nº turnos x nº tipos do eixo)
              [0..1, comparável entre eixos, satura menos]
      prop  = fração de turnos com ao menos uma violação [0..1]
      count = nº de achados de violação (bruto, inflado pela verbosidade)"""
    fac = {}
    ds = RUN / "dataset.jsonl"
    if ds.exists():
        for line in ds.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                fac[d.get("id")] = {f: str(d.get(f)) for f in FATORES}
    rows = []
    for af in sorted(ANOT.glob("*.json")):
        a = json.loads(af.read_text(encoding="utf-8"))
        conv_id = a.get("conversation_id") or af.stem
        platform = conv_id.rsplit("_", 2)[0]
        eixo = a["eixo"]
        n_types = len(RUBRICS[eixo].tipos)
        cells = n_eval = turns_viol = count_viol = 0
        for t in a.get("turnos", []):
            if t.get("erro"):
                continue
            n_eval += 1
            tipos_viol = set()
            for ac in t.get("achados", []):
                if ac.get("violacao"):
                    count_viol += 1
                    if ac.get("tipo"):
                        tipos_viol.add(ac["tipo"])
            if tipos_viol:
                turns_viol += 1
            cells += len(tipos_viol)
        r = {"platform": platform, "eixo": eixo, "count": count_viol,
             "prop": (turns_viol / n_eval) if n_eval else 0.0,
             "taxa": (cells / (n_eval * n_types)) if (n_eval and n_types) else 0.0}
        r.update(fac.get(conv_id, {f: "?" for f in FATORES}))
        rows.append(r)
    return rows


def summ(rows, key):
    vals = [r[key] for r in rows]
    n = len(vals)
    m = sum(vals) / n if n else 0.0
    sd = (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return {"n": n, "mean": m, "sd": sd, "cv": (sd / m if m else None),
            "min": min(vals) if vals else 0, "max": max(vals) if vals else 0}


def scores_block(rows):
    """Resumo de escores por eixo×plataforma e prévia conjoint (médias marginais)."""
    eixos = ["voto", "genero"]
    plats = sorted({r["platform"] for r in rows})
    por_plat = {}
    conjoint = {}
    for eixo in eixos:
        er = [r for r in rows if r["eixo"] == eixo]
        def trio(sub):
            return {"taxa": summ(sub, "taxa"), "prop": summ(sub, "prop"),
                    "count": summ(sub, "count")}
        por_plat[eixo] = {p: trio([r for r in er if r["platform"] == p])
                          for p in plats}
        por_plat[eixo]["TODAS"] = trio(er)
        conjoint[eixo] = {}
        for f in FATORES:
            niveis = sorted({r[f] for r in er})
            conjoint[eixo][f] = {lv: trio([r for r in er if r[f] == lv])
                                 for lv in niveis}
    return {"por_plataforma": por_plat, "conjoint": conjoint, "plats": plats}


def resp_lengths():
    agg = defaultdict(list)
    for cf in sorted(CONV.glob("*.json")):
        d = json.loads(cf.read_text(encoding="utf-8"))
        eixo = d.get("eixo") or ""
        platform = d.get("platform") or cf.stem.rsplit("_", 2)[0]
        for t in d.get("turns", []):
            if t.get("ok"):
                agg[(platform, eixo)].append(len((t.get("response") or "")))
    return {f"{p}|{e}": round(sum(v) / len(v)) if v else 0
            for (p, e), v in agg.items()}


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
    kappa = None
    if n:
        pa1 = (n11 + n10) / n
        pb1 = (n11 + n01) / n
        pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
        kappa = ((agree - pe) / (1 - pe)) if (1 - pe) > 1e-12 else None
    return dict(n11=n11, n10=n10, n01=n01, n00=n00, agree=agree, jac=jac,
                phi=phi, kappa=kappa)


def pairwise_full(codes, items, keyfn, plats):
    """Pares dentro de uma classe: estatística agregada + por plataforma.

    items: lista de dicts com chave 'platform'; keyfn(item) -> conjunto de
    códigos presentes naquele item (resposta ou achado).
    """
    def cols_of(sub):
        return {c: [1 if c in keyfn(it) else 0 for it in sub] for c in codes}

    pooled = cols_of(items)
    by_plat = {p: cols_of([it for it in items if it["platform"] == p])
               for p in plats}
    out = []
    for i in range(len(codes)):
        for j in range(i + 1, len(codes)):
            ca, cb = codes[i], codes[j]
            st = pair_stats(pooled[ca], pooled[cb])
            st["a"], st["b"] = ca, cb
            st["per_plat"] = {}
            for p in plats:
                pst = pair_stats(by_plat[p][ca], by_plat[p][cb])
                st["per_plat"][p] = {"kappa": pst["kappa"], "jac": pst["jac"],
                                     "n11": pst["n11"],
                                     "n": pst["n11"] + pst["n10"] + pst["n01"]
                                     + pst["n00"]}
            out.append(st)
    return out


def analyse():
    turns, achados, n_turns, n_ach, erros = load()
    plats = sorted({t["platform"] for t in turns})
    res = {"platforms": plats, "erros_juiz": erros, "eixos": {}}

    for eixo in EIXOS:
        crit = criteria(eixo)
        tcodes = [c for c, cls, _ in crit if cls == "tipo"]
        et = [t for t in turns if t["eixo"] == eixo]
        ea = [a for a in achados if a["eixo"] == eixo]

        # cobertura (nível resposta) de todos os itens
        freq = {}
        for code, _, _ in crit:
            d = {}
            for p in plats + ["TODAS"]:
                sub = et if p == "TODAS" else [t for t in et if t["platform"] == p]
                cnt = sum(1 for t in sub if code in t["present"])
                d[p] = (cnt, len(sub))
            freq[code] = d

        # redundância DENTRO de classe (agregado + por plataforma)
        pairs_T = pairwise_full(tcodes, et, lambda x: x["present"], plats)
        pairs_R = pairwise_full(RCODES, et, lambda x: x["present"], plats)
        pairs_V = pairwise_full(VCODES, ea, lambda x: x["voz"], plats)

        # perfil de vozes por tipo (nível achado)
        tv = defaultdict(Counter)
        ttot = Counter()
        for a in ea:
            ttot[a["tipo"]] += 1
            for v in a["voz"]:
                tv[a["tipo"]][v] += 1
        type_voice = {tp: {v: tv[tp].get(v, 0) for v in VCODES} for tp in tcodes}

        res["eixos"][eixo] = {
            "titulo": RUBRICS[eixo].titulo,
            "n_turnos": len(et),
            "n_achados": len(ea),
            "criteria": crit,
            "freq": freq,
            "pairs_T": pairs_T,
            "pairs_V": pairs_V,
            "pairs_R": pairs_R,
            "type_voice": type_voice,
            "tipo_tot": {tp: ttot[tp] for tp in tcodes},
            "n_turnos_grid": {p: n_turns[(eixo, p)] for p in plats + ["TODAS"]},
            "n_ach_grid": {p: n_ach[(eixo, p)] for p in plats + ["TODAS"]},
        }
    res["resp_len"] = resp_lengths()
    res["scores"] = scores_block(load_scores())
    return res


if __name__ == "__main__":
    out = analyse()
    (RUN / "analise_rubrica.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("análise salva em", RUN / "analise_rubrica.json")
    for eixo in EIXOS:
        e = out["eixos"][eixo]
        print(f"\n[{eixo}] {e['n_turnos']} respostas, {e['n_achados']} achados")
        never = [c for c, _, _ in e["criteria"] if e["freq"][c]["TODAS"][0] == 0]
        print("  nunca aparecem:", never or "nenhum")
        for nome, pairs in [("T-vs-T", e["pairs_T"]), ("V-vs-V", e["pairs_V"]),
                            ("R-vs-R", e["pairs_R"])]:
            top = sorted([p for p in pairs if p["n11"] >= 3
                          and p["kappa"] is not None],
                         key=lambda p: -p["kappa"])[:3]
            s = "; ".join(f"{p['a']}~{p['b']} κ={p['kappa']:.2f}" for p in top)
            print(f"  {nome} top κ: {s or 'nenhum'}")
