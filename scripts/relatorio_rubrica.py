"""Gera o relatório HTML da análise da rubrica (lê analise_rubrica.json).

Uso: uv run python scripts/relatorio_rubrica.py [run_dir]
Gera <run_dir>/relatorio_rubrica.html
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/pretest1")
J = json.loads((RUN / "analise_rubrica.json").read_text(encoding="utf-8"))
PLATS = J["platforms"]
PLAB = {"whatsapp_metaai": "WhatsApp", "google_aimode": "Google AI Mode",
        "chatgpt": "ChatGPT", "gemini": "Gemini", "claude": "Claude",
        "deepseek": "DeepSeek", "grok": "Grok"}
pl = lambda p: PLAB.get(p, p)  # noqa: E731


def blue(x):
    """Escala 0..1 -> cor de fundo azul (branco->azul escuro)."""
    if x is None:
        return "#f4f4f6", "#999"
    a = max(0.0, min(1.0, x))
    r = int(247 - a * (247 - 30))
    g = int(250 - a * (250 - 90))
    b = int(252 - a * (252 - 170))
    fg = "#fff" if a > 0.55 else "#111"
    return f"rgb({r},{g},{b})", fg


def diverge(x):
    """Escala -1..1 -> vermelho(neg)-branco(0)-azul(pos)."""
    if x is None:
        return "#eee", "#999"
    a = max(-1.0, min(1.0, x))
    if a >= 0:
        r = int(255 - a * (255 - 30)); g = int(255 - a * (255 - 90)); b = int(255 - a * (255 - 170))
    else:
        t = -a
        r = int(255 - t * (255 - 200)); g = int(255 - t * (255 - 60)); b = int(255 - t * (255 - 60))
    fg = "#fff" if abs(a) > 0.6 else "#111"
    return f"rgb({r},{g},{b})", fg


def esc(s):
    return html.escape(str(s))


def freq_table(eixo, e):
    """Tabela critério × plataforma com taxa de presença (% de turnos)."""
    crit = e["criteria"]
    freq = e["freq"]
    ntg = e["n_turnos_grid"]
    head = "".join(f"<th>{pl(p)}<br><span class='n'>n={ntg.get(p,0)}</span></th>"
                   for p in PLATS)
    rows = []
    classe_cor = {"tipo": "#eef4ff", "voz": "#f3fff0", "resist": "#fff7ed"}
    for code, cls, lab in crit:
        cells = []
        for p in PLATS:
            cnt, n = freq[code][p]
            rate = (cnt / n) if n else None
            bg, fg = blue(rate)
            txt = "—" if rate is None else (f"{rate*100:.0f}%" if rate > 0 else "0")
            title = f"{cnt}/{n}"
            border = "border:2px solid #d33;" if (rate == 0) else ""
            cells.append(f"<td style='background:{bg};color:{fg};{border}' "
                         f"title='{title}'>{txt}</td>")
        cnt_t, n_t = freq[code]["TODAS"]
        rate_t = (cnt_t / n_t) if n_t else None
        bg, fg = blue(rate_t)
        tot_border = "border:2px solid #d33;" if rate_t == 0 else ""
        var = (rate_t * (1 - rate_t)) if rate_t is not None else 0
        rows.append(
            f"<tr><td class='crit' style='background:{classe_cor[cls]}'>{esc(lab)}</td>"
            + "".join(cells)
            + f"<td style='background:{bg};color:{fg};font-weight:700;{tot_border}'>"
            f"{'0' if rate_t==0 else f'{rate_t*100:.0f}%'}</td>"
            f"<td class='var'>{var:.3f}</td></tr>"
        )
    return (f"<table class='grid'><thead><tr><th class='crit'>Item</th>{head}"
            f"<th>TOTAL</th><th title='variância p(1-p)'>var</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def tipoxvoz_table(eixo, e):
    """Heatmap da grade tipo×voz (contagem total de turnos com a célula)."""
    tipos = [c for c, cls, _ in e["criteria"] if cls == "tipo"]
    tlabel = {c: lab.split(" · ")[1] for c, cls, lab in e["criteria"] if cls == "tipo"}
    vozes = [c for c, cls, _ in e["criteria"] if cls == "voz"]
    gc = e["grid_cells"]
    ntot = e["n_turnos_grid"]["TODAS"]
    head = "".join(f"<th>{v}</th>" for v in vozes)
    rows = []
    for t in tipos:
        cells = []
        for v in vozes:
            c = gc.get(f"{t}|{v}", 0)
            rate = c / ntot if ntot else 0
            bg, fg = blue(rate)
            border = "border:2px solid #d33;" if c == 0 else ""
            cells.append(f"<td style='background:{bg};color:{fg};{border}'>{c or '·'}</td>")
        rows.append(f"<tr><td class='crit'>{t} · {esc(tlabel[t])}</td>{''.join(cells)}</tr>")
    return (f"<table class='grid'><thead><tr><th class='crit'>tipo \\ voz</th>{head}</tr>"
            f"</thead><tbody>{''.join(rows)}</tbody></table>")


def redundancia(eixo, e):
    """Matriz phi + listas de pares idênticos e quase-idênticos."""
    crit = e["criteria"]
    codes = [c for c, _, _ in crit]
    lab = {c: l for c, _, l in crit}
    pmap = {(p["a"], p["b"]): p for p in e["pairs"]}
    # matriz phi
    head = "".join(f"<th>{c}</th>" for c in codes)
    rows = []
    for i, ca in enumerate(codes):
        cells = []
        for j, cb in enumerate(codes):
            if ca == cb:
                cells.append("<td style='background:#222;color:#fff'>—</td>")
                continue
            key = (ca, cb) if (ca, cb) in pmap else (cb, ca)
            st = pmap.get(key)
            phi = st["phi"] if st else None
            bg, fg = diverge(phi)
            txt = "" if phi is None else f"{phi:.2f}".replace("0.", ".").replace("-0.", "-.")
            cells.append(f"<td style='background:{bg};color:{fg}'>{txt}</td>")
        rows.append(f"<tr><td class='crit'>{ca}</td>{''.join(cells)}</tr>")
    matriz = (f"<table class='grid small'><thead><tr><th></th>{head}</tr></thead>"
              f"<tbody>{''.join(rows)}</tbody></table>")

    # pares idênticos (n10=n01=0) e quase (<=2 discordâncias)
    ident_gen, ident_triv, quase = [], [], []
    for p in e["pairs"]:
        disc = p["n10"] + p["n01"]
        line = (f"{p['a']} ({esc(lab[p['a']].split(' · ')[1])}) ≡ "
                f"{p['b']} ({esc(lab[p['b']].split(' · ')[1])})")
        info = f"n11={p['n11']}, n00={p['n00']}, φ={'' if p['phi'] is None else f'{p['phi']:.2f}'}"
        if disc == 0 and p["n11"] > 0:
            ident_gen.append(f"<li><b>{line}</b> — {info} · redundância genuína "
                             f"(co-ocorrem {p['n11']}× e ausentes juntos {p['n00']}×)</li>")
        elif disc == 0 and p["n11"] == 0:
            ident_triv.append(f"<li>{line} — idênticos por ambos quase nunca "
                              f"aparecerem (n11=0)</li>")
        elif disc <= 2 and p["n11"] >= 2:
            quase.append((p["n11"], f"<li>{line} — {info}, só {disc} "
                          f"discordância(s)</li>"))
    quase.sort(key=lambda t: -t[0])
    quase_html = "".join(h for _, h in quase[:12])

    def ul(items, empty):
        return f"<ul>{''.join(items)}</ul>" if items else f"<p class='muted'>{empty}</p>"

    # por plataforma
    ppi = e["per_plat_ident"]
    prows = []
    for p in PLATS:
        idents = ppi.get(p, [])
        if idents:
            txt = "; ".join(f"{a}≡{b} (×{n11}/{n})" for a, b, n11, n in idents)
        else:
            txt = "<span class='muted'>nenhum</span>"
        prows.append(f"<tr><td>{pl(p)}</td><td>{txt}</td></tr>")
    por_plat = ("<table class='list'><thead><tr><th>Plataforma</th>"
                "<th>Pares idênticos com co-ocorrência (n turnos ≈30)</th></tr></thead>"
                f"<tbody>{''.join(prows)}</tbody></table>")

    return matriz, ul(ident_gen, "Nenhum par com concordância completa E co-ocorrência (n11&gt;0)."), \
        ul(ident_triv, "—"), ul([q for q in [quase_html] if q] or [], "Nenhum par quase-idêntico relevante."), por_plat


def criticidade():
    """Tabela comprimento médio de resposta × achados por turno (confundidor)."""
    rl = J["resp_len"]
    rows = []
    for p in PLATS:
        for eixo in ["voto", "genero"]:
            e = J["eixos"][eixo]
            n = e["n_turnos_grid"].get(p, 0)
            # média de achados por turno = soma das taxas? melhor: total achados
            # aproximado pela soma de células da grade / n (co-ocorrências)
            length = rl.get(f"{p}|{eixo}", 0)
            rows.append((p, eixo, length, n))
    body = "".join(
        f"<tr><td>{pl(p)}</td><td>{eixo}</td><td>{length}</td><td>{n}</td></tr>"
        for p, eixo, length, n in rows)
    return ("<table class='list'><thead><tr><th>Plataforma</th><th>Eixo</th>"
            "<th>Compr. médio resposta (chars)</th><th>Turnos avaliados</th>"
            f"</tr></thead><tbody>{body}</tbody></table>")


# ---------------------------------------------------------------- montagem
def build():
    secoes = []
    for eixo in ["voto", "genero"]:
        e = J["eixos"][eixo]
        matriz, gen, triv, quase, porplat = redundancia(eixo, e)
        n_all = e["n_turnos"]
        never, rare = [], []
        for code, _, lab in e["criteria"]:
            cnt = e["freq"][code]["TODAS"][0]
            rate = cnt / n_all if n_all else 0
            if cnt == 0:
                never.append(lab)
            elif rate <= 0.05:
                rare.append(f"{lab} ({cnt}/{n_all} = {rate*100:.1f}%)")
        never_html = ("<ul>" + "".join(f"<li><b>{esc(x)}</b> — 0 ocorrências</li>"
                      for x in never) + "</ul>") if never \
            else "<p class='muted'>Nenhum item ficou em exatamente 0 no total.</p>"
        rare_html = ("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in rare)
                     + "</ul>") if rare else "<p class='muted'>—</p>"
        secoes.append(f"""
<section>
  <h2>Eixo <span class="eixo">{eixo}</span> — {esc(e['titulo'])}</h2>
  <p class="meta">{e['n_turnos']} respostas avaliadas · {len([c for c in e['criteria'] if c[1]=='tipo'])} tipos, 5 vozes, 3 resistências.</p>

  <h3>1 · Cobertura de cada item (taxa de presença por resposta)</h3>
  <p>Cada célula é a fração de respostas em que o item apareceu. Borda vermelha = 0 (nunca aparece). A última coluna é a variância p(1-p): quanto mais perto de 0, menos o item discrimina.</p>
  {freq_table(eixo, e)}
  <p class="cap"><b>Itens que nunca aparecem no total (0 ocorrências — candidatos diretos a remoção):</b></p>
  {never_html}
  <p class="cap"><b>Itens raros (≤5% das respostas — variância quase nula, discriminam pouco):</b></p>
  {rare_html}

  <h3>Grade tipo × voz (contagem de respostas)</h3>
  <p>Quantas respostas tiveram cada combinação. Células com borda vermelha (·) nunca foram usadas pelo juiz.</p>
  {tipoxvoz_table(eixo, e)}

  <h3>2 · Redundância entre itens (coeficiente φ de correlação)</h3>
  <p>φ = +1 (azul) itens variam juntos; 0 (branco) independentes; −1 (vermelho) opostos. Concordância completa (colunas 0/1 idênticas) ⇒ medem a mesma coisa.</p>
  {matriz}
  <p class="cap"><b>Pares com concordância completa E co-ocorrência (redundância genuína):</b></p>
  {gen}
  <p class="cap"><b>Pares "idênticos" triviais</b> (concordam só porque ambos quase nunca aparecem — já cobertos pelo objetivo 1):</p>
  {triv}
  <p class="cap"><b>Pares quase-idênticos</b> (≤2 discordâncias, ≥2 co-ocorrências) — candidatos a checar:</p>
  {quase}
  <p class="cap"><b>Por plataforma</b> (pares idênticos com co-ocorrência; atenção: ~30 respostas por plataforma, estimativas ruidosas):</p>
  {porplat}
</section>""")

    crit_html = criticidade()
    body = "\n".join(secoes)
    return TEMPLATE.format(
        plats=", ".join(pl(p) for p in PLATS),
        nvoto=J["eixos"]["voto"]["n_turnos"],
        ngenero=J["eixos"]["genero"]["n_turnos"],
        erros=J["erros_juiz"],
        secoes=body,
        criticidade=crit_html,
    )


TEMPLATE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Análise da rubrica LLM-as-judge — pré-teste llmbias-tse</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1a1a1a; line-height: 1.5; max-width: 1100px; margin: 0 auto; padding: 32px 28px; }}
  h1 {{ font-size: 1.7rem; margin: 0 0 4px; }}
  h2 {{ font-size: 1.25rem; margin: 34px 0 6px; border-bottom: 2px solid #222; padding-bottom: 4px; }}
  h3 {{ font-size: 1.05rem; margin: 22px 0 6px; color: #223; }}
  p {{ margin: 6px 0; }}
  .sub {{ color: #555; margin-bottom: 18px; }}
  .eixo {{ font-family: monospace; background: #222; color: #fff; padding: 1px 8px; border-radius: 4px; font-size: .95rem; }}
  .meta {{ color: #666; font-size: .9rem; }}
  .cap {{ margin-top: 14px; }}
  .muted {{ color: #999; font-style: italic; }}
  table {{ border-collapse: collapse; margin: 8px 0 4px; font-size: .82rem; }}
  table.grid td, table.grid th {{ border: 1px solid #e2e2e6; padding: 3px 7px; text-align: center; min-width: 34px; }}
  table.grid th {{ background: #f0f0f3; font-weight: 600; }}
  table.grid td.crit, table.grid th.crit {{ text-align: left; white-space: nowrap; font-weight: 600; background: #fafafa; }}
  table.grid.small td, table.grid.small th {{ min-width: 26px; padding: 2px 4px; font-size: .74rem; }}
  td.var {{ color: #777; font-size: .74rem; }}
  .n {{ font-weight: 400; color: #888; font-size: .7rem; }}
  table.list {{ font-size: .86rem; width: 100%; }}
  table.list td, table.list th {{ border: 1px solid #e2e2e6; padding: 4px 9px; text-align: left; }}
  table.list th {{ background: #f0f0f3; }}
  ul {{ margin: 4px 0 4px 4px; padding-left: 20px; }}
  li {{ margin: 3px 0; }}
  .box {{ background: #f7f8fa; border: 1px solid #e4e6ea; border-radius: 8px; padding: 14px 18px; margin: 14px 0; }}
  .box.warn {{ background: #fff8f0; border-color: #f0d9b8; }}
  .box.key {{ background: #eef6ff; border-color: #cfe3fb; }}
  .legend {{ font-size: .8rem; color: #666; }}
  @media print {{ body {{ padding: 0; max-width: none; }} h2 {{ page-break-after: avoid; }}
    section {{ page-break-inside: avoid; }} table {{ page-break-inside: avoid; }} }}
</style></head><body>
<h1>Análise dos itens da rubrica do LLM-as-judge</h1>
<p class="sub">Pré-teste llmbias-tse · run <code>pretest1</code> · plataformas: {plats}<br>
Unidade de análise: a <b>resposta do assistente</b> (turno avaliado). {nvoto} respostas no eixo voto, {ngenero} no eixo gênero.
Cada item da rubrica (tipo Tn, voz Vn, resistência Rn) é marcado como presente (1) ou ausente (0) por resposta.</p>

<div class="box key">
<b>Como ler:</b> o objetivo é auditar a própria rubrica. <b>Objetivo 1</b>: itens que o juiz nunca marca (frequência 0) são candidatos a remoção.
<b>Objetivo 2</b>: itens cujas colunas 0/1 são idênticas entre as respostas (concordância completa) medem a mesma coisa e podem ser fundidos.
Distinguimos redundância <i>genuína</i> (itens que co-ocorrem como 1) de <i>trivial</i> (concordam só porque ambos quase nunca aparecem).
</div>

{secoes}

<section>
  <h2>3 · Leitura crítica: os escores são comparáveis? Têm variabilidade?</h2>
  <div class="box warn">
  <b>Comparabilidade.</b> As contagens brutas de achados <b>não</b> são diretamente comparáveis entre plataformas: o número de marcações cresce com o <b>comprimento e a quantidade de conteúdo</b> da resposta. Plataformas verbosas (Grok, DeepSeek, Google AI Mode) têm muito mais superfície para o juiz marcar do que respostas curtas (o WhatsApp/Meta AI recusa o voto em ~78 caracteres). Binarizar por <b>presença na resposta</b> (como nesta análise) atenua parte do viés de contagem, mas o comprimento ainda infla a chance de presença. Comparações honestas exigem normalizar por resposta e, idealmente, por extensão.
  </div>
  <p>Comprimento médio de resposta e nº de respostas avaliadas por plataforma × eixo (o confundidor):</p>
  {criticidade}
  <div class="box">
  <b>Variabilidade.</b> Um item só serve para avaliar se <b>varia</b>. Itens com taxa 0 (nunca) ou próxima de 0/1 têm variância p(1−p)≈0 e não discriminam plataformas — ver a coluna <code>var</code> das tabelas de cobertura. Itens no meio da escala (taxa ~0,3–0,7) são os que carregam informação.
  </div>
  <div class="box">
  <b>Tamanho amostral.</b> São ~30 respostas por plataforma×eixo (3 perfis × 10 turnos). Estimativas <b>por plataforma</b> de itens raros são muito ruidosas: um único achado muda a taxa em ~3 pontos. As conclusões por plataforma são indicativas; as robustas vêm do total por eixo (150–180 respostas). Redundância "por plataforma" com n≈30 acha pares idênticos por acaso — tratar como hipótese, não conclusão.
  </div>
  <div class="box key">
  <b>Síntese para revisar a rubrica.</b> (i) Remover/rever os itens sem nenhuma ocorrência no total; (ii) revisar os pares de redundância genuína (fundir ou diferenciar melhor a definição); (iii) para os eixos com pouca variabilidade, considerar personas/ganchos que exercitem os tipos hoje silenciosos antes do experimento completo; (iv) fixar a unidade de escore (presença por resposta) e normalizar por extensão para tornar as plataformas comparáveis.
  </div>
</section>
<p class="legend">Gerado automaticamente a partir de <code>data/pretest1/annotations/</code> por <code>scripts/analise_rubrica.py</code> + <code>scripts/relatorio_rubrica.py</code>. Erros transitórios do juiz re-julgados; {erros} turnos com erro remanescentes.</p>
</body></html>"""


if __name__ == "__main__":
    out = build()
    p = RUN / "relatorio_rubrica.html"
    p.write_text(out, encoding="utf-8")
    print("relatório salvo em", p)
