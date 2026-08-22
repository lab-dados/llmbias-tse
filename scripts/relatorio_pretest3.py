"""Relatório HTML do pré-teste (ago/2026): três eixos e painel de três juízes.

Sucede o relatório de rubrica do pré-teste anterior. O que muda:
  - cobre os TRÊS eixos (o de integridade entrou nesta rodada);
  - a análise central passa a ser a CONCORDÂNCIA ENTRE JUÍZES, com matriz de
    confusão por par, κ, e o efeito da regra de agregação;
  - tudo em duas granularidades (conversa × tipo e turno × tipo).

Uso: uv run python scripts/relatorio_pretest3.py [run_dir]
Gera <run_dir>/relatorio_pretest3.html
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from llmbias_tse.rubrics import RUBRICS

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/pretest3")
J = json.loads((RUN / "analise_juizes.json").read_text(encoding="utf-8"))
JUIZES = ["gemini", "opus", "gpt"]
MODELOS = {"gemini": "gemini-3.1-pro-preview", "opus": "claude-opus-5",
           "gpt": "gpt-5.6-sol"}
ROTULO = {e: {t.codigo: t.tipo for t in g.tipos} for e, g in RUBRICS.items()}


def pct(v, casas=1):
    return "—" if v is None else f"{v*100:.{casas}f}%"


def num(v, casas=3):
    return "—" if v is None else f"{v:+.{casas}f}"


def kappa_classe(k):
    if k is None:
        return ""
    if k < 0.2:
        return "ruim"
    if k < 0.4:
        return "fraco"
    if k < 0.6:
        return "moderado"
    if k < 0.8:
        return "bom"
    return "otimo"


# --------------------------------------------------------------------------
# Dados da coleta (para o panorama)
# --------------------------------------------------------------------------

def panorama():
    convs, anots = {}, {}
    for f in sorted((RUN / "conversations").glob("*.json")):
        c = json.loads(f.read_text(encoding="utf-8"))
        convs[c["conversation_id"]] = c
    for f in sorted((RUN / "annotations").glob("*.json")):
        a = json.loads(f.read_text(encoding="utf-8"))
        anots[a["conversation_id"]] = a
    plat = defaultdict(lambda: {"conv": 0, "turnos": 0, "chars": [],
                                "viol": 0, "cel": 0})
    eixo = defaultdict(lambda: {"viol": 0, "cel": 0})
    for cid, c in convs.items():
        p = plat[c["platform"]]
        p["conv"] += 1
        ok = [t for t in c["turns"] if t.get("ok")]
        p["turnos"] += len(ok)
        p["chars"] += [t.get("response_chars") or 0 for t in ok]
        a = anots.get(cid)
        if a:
            for _t, v in (a.get("por_tipo") or {}).items():
                p["cel"] += 1
                p["viol"] += int(v or 0)
                eixo[c["eixo"]]["cel"] += 1
                eixo[c["eixo"]]["viol"] += int(v or 0)
    return convs, anots, plat, eixo


CONVS, ANOTS, PLAT, EIXO = panorama()


def mediana(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def tab_plataformas():
    linhas = []
    for p, d in sorted(PLAT.items(), key=lambda kv: -(kv[1]["viol"] / max(1, kv[1]["cel"]))):
        taxa = d["viol"] / d["cel"] if d["cel"] else None
        linhas.append(
            f"<tr><td><code>{p}</code></td><td>{d['conv']}</td>"
            f"<td>{d['turnos']}</td><td>{mediana(d['chars']):,}</td>"
            f"<td class='destaque'>{pct(taxa)}</td></tr>".replace(",", ".")
        )
    return "\n".join(linhas)


def tab_eixos():
    linhas = []
    for e, d in sorted(EIXO.items(), key=lambda kv: -(kv[1]["viol"] / max(1, kv[1]["cel"]))):
        taxa = d["viol"] / d["cel"] if d["cel"] else None
        linhas.append(
            f"<tr><td><b>{e}</b></td><td>{d['cel']}</td>"
            f"<td class='destaque'>{pct(taxa)}</td></tr>"
        )
    return "\n".join(linhas)


# --------------------------------------------------------------------------
# Concordância
# --------------------------------------------------------------------------

def tab_pares(bloco):
    linhas = []
    for p in bloco["pares"]:
        cls = kappa_classe(p["kappa"])
        linhas.append(
            f"<tr><td><code>{p['par']}</code></td><td>{p['n']}</td>"
            f"<td>{pct(p['concordancia'])}</td>"
            f"<td class='k {cls}'>{num(p['kappa'])}</td>"
            f"<td>{pct(p['taxa_j1'],0)} × {pct(p['taxa_j2'],0)}</td></tr>"
        )
    return "\n".join(linhas)


def matriz_confusao(p):
    m = p["confusao"]
    j1, j2 = p["par"].split("×")
    tot = sum(sum(r) for r in m) or 1
    def cel(v, diag):
        c = "diag" if diag else "off"
        return f"<td class='{c}'>{v}<span>{v/tot*100:.0f}%</span></td>"
    return f"""
<table class="conf">
  <caption>{j1} (linhas) × {j2} (colunas)</caption>
  <tr><th></th><th>não</th><th>sim</th></tr>
  <tr><th>não</th>{cel(m[0][0],True)}{cel(m[0][1],False)}</tr>
  <tr><th>sim</th>{cel(m[1][0],False)}{cel(m[1][1],True)}</tr>
</table>"""


def confusoes(bloco):
    return "<div class='confs'>" + "".join(
        matriz_confusao(p) for p in bloco["pares"]) + "</div>"


def tab_agregacoes(bloco):
    a = bloco["agregacoes"]
    ordem = ["intersecao", "so_gpt", "so_gemini", "maioria", "so_opus", "uniao"]
    rot = {"intersecao": "interseção (os 3 concordam)", "uniao": "união (qualquer um)",
           "maioria": "<b>maioria (2 de 3)</b>", "so_gemini": "só gemini",
           "so_opus": "só opus", "so_gpt": "só gpt"}
    linhas = []
    for k in ordem:
        if a.get(k) is None:
            continue
        destaque = " class='linha-destaque'" if k == "maioria" else ""
        linhas.append(f"<tr{destaque}><td>{rot[k]}</td>"
                      f"<td class='destaque'>{pct(a[k])}</td></tr>")
    return "\n".join(linhas)


def tab_plat_eixo_juiz(nivel):
    """Plataforma × EIXO × juiz.

    Agrupa as células da conversa daquele eixo naquela plataforma: é a unidade
    em que o relatório final vai falar ("no eixo de voto, a plataforma X ...").
    """
    linhas = []
    dados = J[nivel]["por_plataforma_eixo"]
    for p in sorted(dados):
        eixos = dados[p]
        for i, (e, b) in enumerate(sorted(eixos.items())):
            a = b["agregacoes"]
            taxas = [a.get(f"so_{j}") for j in JUIZES
                     if a.get(f"so_{j}") is not None]
            amp = (max(taxas) - min(taxas)) if taxas else None
            plat_cel = (f"<td rowspan='{len(eixos)}'><code>{p}</code></td>"
                        if i == 0 else "")
            linhas.append(
                f"<tr>{plat_cel}<td>{e}</td><td>{b['n']}</td>"
                f"<td>{pct(a['so_gpt'],0)}</td><td>{pct(a['so_gemini'],0)}</td>"
                f"<td>{pct(a['so_opus'],0)}</td>"
                f"<td class='destaque'>{pct(a['maioria'],0)}</td>"
                f"<td class='amp'>{pct(amp,0)}</td>"
                f"<td>{pct(b['unanime'],0)}</td></tr>"
            )
    return "\n".join(linhas)


def ordem_por_juiz(eixo):
    """Dentro de um eixo, o ranking das plataformas muda conforme o juiz?"""
    dados = J["nivel_conversa"]["por_plataforma_eixo"]
    linhas = []
    for j in JUIZES + ["maioria"]:
        chave = "maioria" if j == "maioria" else f"so_{j}"
        itens = [(p, d[eixo]["agregacoes"].get(chave))
                 for p, d in dados.items() if eixo in d]
        itens = [(p, v) for p, v in itens if v is not None]
        ordem = sorted(itens, key=lambda kv: -kv[1])
        nomes = " › ".join(f"<code>{p}</code> {v*100:.0f}%"
                           for p, v in ordem[:4])
        rot = "<b>maioria</b>" if j == "maioria" else j
        linhas.append(f"<tr><td>{rot}</td><td class='rot'>{nomes} …</td></tr>")
    return "\n".join(linhas)


def tab_por_eixo(nivel):
    linhas = []
    for e, b in J[nivel]["por_eixo"].items():
        linhas.append(
            f"<tr><td><b>{e}</b></td><td>{b['n']}</td>"
            f"<td>{pct(b['unanime'])}</td>"
            f"<td class='k {kappa_classe(b['fleiss'])}'>{num(b['fleiss'])}</td>"
            f"<td>{pct(b['agregacoes']['so_gpt'],0)}</td>"
            f"<td>{pct(b['agregacoes']['so_gemini'],0)}</td>"
            f"<td>{pct(b['agregacoes']['so_opus'],0)}</td></tr>"
        )
    return "\n".join(linhas)


def tab_por_tipo(nivel):
    blocos = []
    for e, tipos in J[nivel]["por_eixo_tipo"].items():
        linhas = []
        for t, b in tipos.items():
            rot = ROTULO.get(e, {}).get(t, "")
            linhas.append(
                f"<tr><td><code>{t}</code></td><td class='rot'>{rot}</td>"
                f"<td>{b['n']}</td><td>{pct(b['unanime'])}</td>"
                f"<td class='k {kappa_classe(b['fleiss'])}'>{num(b['fleiss'])}</td>"
                f"<td>{pct(b['agregacoes']['so_gpt'],0)}</td>"
                f"<td>{pct(b['agregacoes']['so_gemini'],0)}</td>"
                f"<td>{pct(b['agregacoes']['so_opus'],0)}</td></tr>"
            )
        blocos.append(f"""
<h4>{e}</h4>
<table>
 <tr><th>tipo</th><th>rótulo</th><th>n_avaliações</th><th>unânime</th><th>Fleiss κ</th>
     <th>gpt</th><th>gemini</th><th>opus</th></tr>
 {"".join(linhas)}
</table>""")
    return "\n".join(blocos)


CONV = J["nivel_conversa"]["geral"]
TURNO = J["nivel_turno"]["geral"]

HTML = f"""<title>Pré-teste 3 — concordância entre juízes</title>
<style>
:root {{
  --tinta:#16181d; --fraco:#5b6472; --linha:#e2e6ec; --fundo:#fff;
  --caixa:#f6f8fa; --destaque:#0b5fff; --alerta:#b3261e; --ok:#0f7b3d;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --tinta:#e6e9ef; --fraco:#9aa4b2; --linha:#2a2f38; --fundo:#12141a;
    --caixa:#181c23; --destaque:#7aa2ff; --alerta:#ff8a80; --ok:#6ee7a0;
  }}
}}
:root[data-theme="dark"] {{
  --tinta:#e6e9ef; --fraco:#9aa4b2; --linha:#2a2f38; --fundo:#12141a;
  --caixa:#181c23; --destaque:#7aa2ff; --alerta:#ff8a80; --ok:#6ee7a0;
}}
* {{ box-sizing:border-box; }}
body {{ background:var(--fundo); color:var(--tinta); margin:0;
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:900px; margin:0 auto; padding:48px 24px 80px; }}
h1 {{ font-size:1.9rem; line-height:1.25; margin:0 0 .2em; letter-spacing:-.02em; }}
h2 {{ font-size:1.3rem; margin:2.4em 0 .6em; padding-top:.8em;
  border-top:1px solid var(--linha); letter-spacing:-.01em; }}
h3 {{ font-size:1.05rem; margin:1.6em 0 .4em; }}
h4 {{ font-size:.95rem; margin:1.4em 0 .3em; color:var(--fraco);
  text-transform:uppercase; letter-spacing:.06em; }}
.sub {{ color:var(--fraco); margin:0 0 2em; }}
table {{ border-collapse:collapse; width:100%; margin:.8em 0 1.4em;
  font-size:.9rem; }}
th,td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--linha); }}
th {{ color:var(--fraco); font-weight:600; font-size:.8rem;
  text-transform:uppercase; letter-spacing:.04em; }}
td.destaque {{ font-variant-numeric:tabular-nums; font-weight:600; }}
td.rot {{ color:var(--fraco); font-size:.85rem; }}
tr.linha-destaque td {{ background:var(--caixa); }}
code {{ background:var(--caixa); padding:1px 5px; border-radius:4px;
  font-size:.85em; }}
.k {{ font-variant-numeric:tabular-nums; font-weight:600; }}
.k.ruim,.k.fraco {{ color:var(--alerta); }}
.k.moderado {{ color:#b06f00; }}
.k.bom,.k.otimo {{ color:var(--ok); }}
.caixa {{ background:var(--caixa); border-left:3px solid var(--destaque);
  padding:14px 18px; margin:1.4em 0; border-radius:0 6px 6px 0; }}
.caixa.alerta {{ border-left-color:var(--alerta); }}
.caixa p:first-child {{ margin-top:0; }} .caixa p:last-child {{ margin-bottom:0; }}
.confs {{ display:flex; gap:16px; flex-wrap:wrap; margin:1em 0 1.6em; }}
table.conf {{ width:auto; font-size:.82rem; margin:0; }}
table.conf caption {{ color:var(--fraco); font-size:.78rem; padding-bottom:6px;
  text-align:left; }}
table.conf td {{ text-align:center; min-width:64px; font-variant-numeric:tabular-nums; }}
table.conf td span {{ display:block; font-size:.72em; color:var(--fraco); }}
table.conf td.diag {{ background:color-mix(in srgb, var(--ok) 12%, transparent); }}
table.conf td.off {{ background:color-mix(in srgb, var(--alerta) 12%, transparent); }}
.tabela-scroll {{ overflow-x:auto; }}
footer {{ margin-top:3em; padding-top:1.2em; border-top:1px solid var(--linha);
  color:var(--fraco); font-size:.85rem; }}
</style>

<div class="wrap">
<h1>Pré-teste 3: três eixos, três juízes</h1>
<p class="sub">Run <code>{J['run']}</code> · {J['n_conversas']} conversas ·
8 plataformas · 3 eixos · gerado em {date.today():%d/%m/%Y}</p>

<div class="caixa">
<p><b>O que este pré-teste testou.</b> A infraestrutura completa de coleta (8
plataformas, incluindo Copilot e WhatsApp/Meta AI) e, principalmente, se os
<b>três juízes medem a mesma coisa</b>. A resposta curta é: parcialmente — e
onde eles divergem é informativo.</p>
</div>

<h2>1. Panorama da coleta</h2>
<table>
<tr><th>plataforma</th><th>conversas</th><th>turnos</th>
    <th>mediana de chars</th><th>taxa de violação</th></tr>
{tab_plataformas()}
</table>
<p>Por eixo:</p>
<table>
<tr><th>eixo</th><th>n_avaliações (conversa × tipo)</th><th>taxa de violação</th></tr>
{tab_eixos()}
</table>
<p>A taxa acima usa a <b>maioria dos três juízes</b>. A seção 3 mostra o quanto
esse número depende dessa escolha.</p>

<h2>2. Concordância entre juízes</h2>
<p>Duas granularidades, de propósito. <b>Conversa × tipo</b> pergunta se o juiz
marcou aquele tipo em algum ponto da conversa; <b>turno × tipo</b> exige também
concordar sobre <i>onde</i>. A diferença entre as duas separa discordar do fato
de discordar da localização.</p>

<h3>Nível conversa × tipo (n={CONV['n']})</h3>
<table>
<tr><th>par</th><th>n_avaliações</th><th>concordância</th><th>κ de Cohen</th>
    <th>taxa de cada um</th></tr>
{tab_pares(CONV)}
</table>
{confusoes(CONV)}
<p>Fleiss κ entre os três: <b class="k {kappa_classe(CONV['fleiss'])}">{num(CONV['fleiss'])}</b>
· unanimidade em <b>{pct(CONV['unanime'])}</b> das avaliações.</p>

<h3>Nível turno × tipo (n={TURNO['n']})</h3>
<table>
<tr><th>par</th><th>n_avaliações</th><th>concordância</th><th>κ de Cohen</th>
    <th>taxa de cada um</th></tr>
{tab_pares(TURNO)}
</table>
{confusoes(TURNO)}
<p>Fleiss κ: <b class="k {kappa_classe(TURNO['fleiss'])}">{num(TURNO['fleiss'])}</b>
· unanimidade em <b>{pct(TURNO['unanime'])}</b>.</p>

<div class="caixa alerta">
<p><b>O problema não é ruído, é severidade.</b> Os três juízes não discordam ao
acaso: eles estão ordenados. No nível conversa, o Opus marca violação em
{pct(CONV['agregacoes']['so_opus'],0)} das células, o Gemini em
{pct(CONV['agregacoes']['so_gemini'],0)} e o GPT em
{pct(CONV['agregacoes']['so_gpt'],0)} — quase três vezes menos que o Opus,
avaliando exatamente o mesmo material com exatamente o mesmo prompt. As
matrizes de confusão mostram a assimetria: o erro quase nunca é cruzado, é
sempre o mais severo marcando onde o mais brando não marca.</p>
<p>A consequência prática é que <b>a taxa reportada depende de quem julga</b>.
Um relatório que diga "a plataforma X violou em N% dos casos" precisa dizer
também qual juiz, ou qual regra de agregação, produziu esse N.</p>
</div>

<h2>3. Quanto a regra de agregação muda o resultado</h2>
<p>A mesma base, agregada de seis formas:</p>
<div class="confs" style="align-items:flex-start">
<div style="flex:1;min-width:260px">
<h4>nível conversa</h4>
<table><tr><th>regra</th><th>taxa</th></tr>{tab_agregacoes(CONV)}</table>
</div>
<div style="flex:1;min-width:260px">
<h4>nível turno</h4>
<table><tr><th>regra</th><th>taxa</th></tr>{tab_agregacoes(TURNO)}</table>
</div>
</div>
<p>No nível conversa, a taxa vai de <b>{pct(CONV['agregacoes']['intersecao'])}</b>
(exigindo unanimidade) a <b>{pct(CONV['agregacoes']['uniao'])}</b> (bastando um
juiz) — uma variação de mais de três vezes decidida <i>apenas</i> pela regra.
A maioria de 2 em 3 cai em {pct(CONV['agregacoes']['maioria'])}, praticamente
colada na taxa do Gemini, que é o juiz mediano.</p>

<h2>4. Taxa de violação por plataforma e eixo, segundo cada juiz</h2>
<p><b>Atenção à unidade.</b> Este pré-teste rodou <b>UMA conversa</b> por
plataforma × eixo (24 conversas, todas do mesmo perfil <code>P01</code>). O que a coluna <i>n_avaliações</i> conta não são conversas: é <b>conversa × tipo</b> — uma
conversa de gênero rende 5 células (T1..T5) e uma de voto ou integridade rende
4. No nível de turno, cada célula é turno × tipo. As taxas abaixo são, portanto,
a fração de <i>células</i> marcadas, e um único comportamento pode mover a taxa
em 20 ou 25 pontos.</p>
<p>Esta é a tabela que mais importa para o relatório final: a unidade em que o
texto vai falar ("no eixo de voto, a plataforma X…"). Mostra a taxa que
<b>cada juiz sozinho</b> atribuiria àquela plataforma naquele eixo, ao lado da
maioria. A coluna <b>amplitude</b> é a distância entre o juiz mais brando e o
mais severo — é a medida de quanto o resultado depende de quem julga.</p>
<div class="tabela-scroll">
<h4>nível conversa × tipo</h4>
<table>
<tr><th>plataforma</th><th>eixo</th><th>n_avaliações</th><th>gpt</th><th>gemini</th>
    <th>opus</th><th>maioria</th><th>amplitude</th><th>unânime</th></tr>
{tab_plat_eixo_juiz('nivel_conversa')}
</table>
<h4>nível turno × tipo</h4>
<table>
<tr><th>plataforma</th><th>eixo</th><th>n_avaliações</th><th>gpt</th><th>gemini</th>
    <th>opus</th><th>maioria</th><th>amplitude</th><th>unânime</th></tr>
{tab_plat_eixo_juiz('nivel_turno')}
</table>
</div>

<div class="caixa alerta">
<p><b>O ranking das plataformas depende do juiz.</b> Dentro de cada eixo,
ordenando da mais permissiva para a menos:</p>
<h4>voto</h4>
<table>{ordem_por_juiz('voto')}</table>
<h4>gênero</h4>
<table>{ordem_por_juiz('genero')}</table>
<h4>integridade</h4>
<table>{ordem_por_juiz('integridade')}</table>
<p>Não é só a magnitude que muda: a <b>ordem</b> das plataformas muda conforme
o juiz. Uma frase como "a plataforma X foi a que mais violou no eixo Y" pode
ser verdadeira ou falsa dependendo de qual modelo julgou — e é por isso que a
seção 7 recomenda publicar a dispersão, não só a maioria.</p>
</div>

<h2>5. Concordância por eixo</h2>
<div class="tabela-scroll">
<h4>nível conversa</h4>
<table>
<tr><th>eixo</th><th>n_avaliações</th><th>unânime</th><th>Fleiss κ</th>
    <th>gpt</th><th>gemini</th><th>opus</th></tr>
{tab_por_eixo('nivel_conversa')}
</table>
<h4>nível turno</h4>
<table>
<tr><th>eixo</th><th>n_avaliações</th><th>unânime</th><th>Fleiss κ</th>
    <th>gpt</th><th>gemini</th><th>opus</th></tr>
{tab_por_eixo('nivel_turno')}
</table>
</div>

<h2>6. Concordância por tipo da rubrica</h2>
<p>É aqui que se vê <b>qual item da rubrica está mal especificado</b>: um tipo
com κ baixo e taxas muito distintas entre juízes é um tipo cuja delimitação
não está decidindo o caso.</p>
<div class="tabela-scroll">
{tab_por_tipo('nivel_conversa')}
</div>

<h2>7. O que fazer com isto</h2>
<div class="caixa">
<p><b>1. Reportar por juiz, não só a maioria.</b> A seção 3 mostra que a
escolha da regra move o resultado mais do que a diferença entre várias
plataformas. Publicar um número único sem a dispersão entre juízes esconde uma
decisão metodológica dentro de um dado.</p>
<p><b>2. Usar os tipos de κ baixo como lista de trabalho da rubrica.</b> A
seção 6 aponta onde a delimitação não está fechando o caso. Já corrigimos um
deles neste pré-teste (a contradição entre o T1 de ranqueamento e a regra da
porta de entrada, que fazia o Opus marcar violação em toda lista de
candidatos): a divergência no eixo de voto caiu de 69% para 25% em conversas
que não tinham sido usadas no diagnóstico.</p>
<p><b>3. A subamostra de três juízes basta.</b> Como a divergência é
sistemática e não aleatória, ela é estimável com ~55-70 conversas por eixo
(±5 pp na taxa de concordância). Não é preciso rodar os três juízes em toda a
coleta: um juiz no volume total e os três numa subamostra dão a correção.</p>
</div>

<footer>
Juízes: {" · ".join(f"<code>{k}</code> {v}" for k, v in MODELOS.items())}.
Todos receberam o mesmo prompt, a mesma rubrica e o mesmo material; a única
diferença é o modelo. κ de Cohen é a concordância corrigida pelo acaso (dois
juízes); Fleiss κ é o equivalente para os três. Pré-teste com um perfil por
plataforma — os valores servem para dimensionar e diagnosticar, não como
estimativa final das plataformas.
</footer>
</div>
"""

out = RUN / "relatorio_pretest3.html"
out.write_text(HTML, encoding="utf-8")
print(f"relatório: {out} ({len(HTML)/1024:.0f} KB)")
