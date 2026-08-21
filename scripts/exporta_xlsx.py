"""Exporta todos os dados de um run do conjoint para um único .xlsx (multi-aba).

Atualizado para o desenho de ago/2026: instrumento com roteiro pré-resolvido,
temas como variável independente e PAINEL de juízes (um veredito por juiz).

Abas:
  conversas          um registro por conversa (fatores + temas + agregados)
  turnos             um registro por turno (pergunta, resposta, tamanho)
  achados            um registro por achado, COM a coluna `juiz`
  votos_por_tipo     conversa × tipo: voto de cada juiz + maioria (para a
                     análise de concordância)
  roteiro            conversa × turno: alternativas e exemplares planejados
  perfis             os perfis sorteados
  rubrica_tipos      definições dos tipos, por eixo
  rubrica_vozes      definições das vozes
  rubrica_resistencias  definições das resistências

Uso: uv run python scripts/exporta_xlsx.py [run_dir]
Gera <run_dir>/<run>_dados.xlsx
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from llmbias_tse.rubrics import RESISTENCIAS, RUBRICS, VOZES


def limpa(v):
    """Remove os caracteres de controle que o Excel recusa.

    As respostas das plataformas vêm com controles invisíveis (o Excel rejeita
    qualquer coisa fora do XML 1.0), o que derruba a escrita da planilha
    inteira por causa de uma célula.
    """
    if isinstance(v, str):
        return ILLEGAL_CHARACTERS_RE.sub("", v)
    return v

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/pretest3")
CONV = RUN / "conversations"
ANOT = RUN / "annotations"
FATORES = ["politica", "genero", "idade", "escolaridade", "estilo_conversa",
           "estilo_escrita"]


def _anot(cid: str) -> dict:
    p = ANOT / f"{cid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main() -> None:
    conv_rows, turno_rows, achado_rows, voto_rows, rot_rows = [], [], [], [], []

    for cf in sorted(CONV.glob("*.json")):
        c = json.loads(cf.read_text(encoding="utf-8"))
        cid = c.get("conversation_id") or cf.stem
        plat, eixo = c.get("platform"), c.get("eixo")
        prof = c.get("profile") or {}
        fat = {f: prof.get(f) for f in FATORES}
        a = _anot(cid)
        cobertura = c.get("cobertura_temas") or {}
        por_juiz = a.get("por_juiz") or {}
        juizes = [k for k in por_juiz if "erro" not in por_juiz[k]]

        # --- conversa
        row = {
            "conversation_id": cid, "platform": plat, "eixo": eixo,
            "perfil_id": prof.get("id"), **fat,
            "n_turnos": c.get("n_turns"),
            "instrumento": c.get("instrumento"),
            "n_temas": sum(1 for v in cobertura.values() if v > 0),
            "temas_incluidos": "+".join(k for k, v in cobertura.items() if v > 0),
            "n_juizes": a.get("n_juizes"),
            "painel_completo": a.get("painel_completo"),
            "juizes_com_falha": "+".join(a.get("juizes_com_falha") or []),
            "concordancia_unanime_tipos": a.get("concordancia_unanime_tipos"),
            "achados_total": a.get("achados_total"),
            "achados_violacao": a.get("achados_violacao"),
            "turnos_com_violacao": a.get("turnos_com_violacao"),
            "violou": (int((a.get("achados_violacao") or 0) > 0) if a else None),
            "conversation_url": c.get("conversation_url"),
        }
        for cod, n in cobertura.items():
            row[f"tema_{cod}"] = int(n > 0)
            row[f"aparicoes_{cod}"] = int(n)
            row[f"violou_{cod}"] = (a.get("por_tipo") or {}).get(cod)
        conv_rows.append(row)

        # --- votos por tipo (insumo da análise de concordância)
        for cod in (a.get("por_tipo") or {}):
            vr = {"conversation_id": cid, "platform": plat, "eixo": eixo,
                  "tipo": cod, "tema_incluido": int(cobertura.get(cod, 0) > 0),
                  "aparicoes": int(cobertura.get(cod, 0)),
                  "maioria": (a.get("por_tipo") or {}).get(cod),
                  "votos": (a.get("votos_por_tipo") or {}).get(cod)}
            for j in por_juiz:
                pt = (por_juiz[j].get("por_tipo") or {})
                vr[f"juiz_{j}"] = (int(pt.get(cod, 0) > 0)
                                   if "erro" not in por_juiz[j] else None)
            voto_rows.append(vr)

        # --- turnos
        for t in c.get("turns", []):
            turno_rows.append({
                "conversation_id": cid, "platform": plat, "eixo": eixo,
                "turno": t.get("turn"), "ok": t.get("ok"),
                "pergunta_usuario": t.get("prompt") or "",
                "resposta_modelo": t.get("response") or "",
                "resp_chars": t.get("response_chars"),
                "erro": t.get("error"),
            })

        # --- roteiro planejado
        for t in c.get("roteiro", []) or []:
            for q in t.get("perguntas", []) or []:
                rot_rows.append({
                    "conversation_id": cid, "eixo": eixo,
                    "turno": t.get("ordem"),
                    "n_perguntas_no_turno": t.get("n_perguntas"),
                    "relato": q.get("relato"), "pedido": q.get("pedido"),
                    "fundida": q.get("fundida"),
                    "exemplares": "; ".join(
                        f"{e.get('lista')}={e.get('item')}"
                        for e in (q.get("exemplares") or [])
                    ),
                })

        # --- achados, por juiz
        for j, res in por_juiz.items():
            if "erro" in res:
                continue
            for t in res.get("turnos", []) or []:
                for ac in t.get("achados", []) or []:
                    achado_rows.append({
                        "conversation_id": cid, "platform": plat, "eixo": eixo,
                        "juiz": j, "turno": t.get("turn"),
                        "tipo": ac.get("tipo"),
                        "vozes": "+".join(ac.get("voz") or []),
                        "violacao": ac.get("violacao"),
                        "trecho": ac.get("trecho") or "",
                        "nota": ac.get("nota") or "",
                    })

    perfis = []
    pj = RUN / "profiles.json"
    if pj.exists():
        perfis = json.loads(pj.read_text(encoding="utf-8"))

    rub_tipos = [{"eixo": e, "codigo": t.codigo, "tipo": t.tipo,
                  "pergunta": t.pergunta, "delimitacao": t.delimitacao}
                 for e, g in RUBRICS.items() for t in g.tipos]
    rub_vozes = [{"codigo": v.codigo, "nome": v.nome,
                  "eh_violacao": v.violacao, "definicao": v.definicao}
                 for v in VOZES]
    rub_resist = [{"codigo": r.codigo, "conduta": r.conduta}
                  for r in RESISTENCIAS]

    out = RUN / f"{RUN.name}_dados.xlsx"
    abas = {
        "conversas": conv_rows, "turnos": turno_rows, "achados": achado_rows,
        "votos_por_tipo": voto_rows, "roteiro": rot_rows, "perfis": perfis,
        "rubrica_tipos": rub_tipos, "rubrica_vozes": rub_vozes,
        "rubrica_resistencias": rub_resist,
    }
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        for nome, linhas in abas.items():
            df = pd.DataFrame(linhas)
            # Aplica em TODA coluna: neste pandas as colunas de texto vêm com
            # dtype "str" (não "object"), então filtrar por object silenciava a
            # limpeza inteira. `limpa` já ignora o que não é string.
            for col in df.columns:
                df[col] = df[col].map(limpa)
            df.to_excel(xw, sheet_name=nome, index=False)
    print(f"xlsx salvo: {out}")
    for nome, linhas in abas.items():
        print(f"  {nome:22s} {len(linhas):5d} linhas")


if __name__ == "__main__":
    main()
