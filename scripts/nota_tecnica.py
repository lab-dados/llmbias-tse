# -*- coding: utf-8 -*-
"""Gera a nota técnica curta: o que mudou no experimento e por quê.

É o documento de apresentação, para leitura em reunião. O par dele é
`conteudo_editorial.py`, que gera o documento longo, com a transcrição de todo
o texto que roda. Este aqui explica; aquele registra.

Os números vêm do código, para que a nota não possa afirmar algo que o
experimento não faz.

    uv run python scripts/nota_tecnica.py

Saída: docs/nota_tecnica.docx
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx_writer import Docx  # noqa: E402

from llmbias_tse import instrument, rubrics  # noqa: E402
from llmbias_tse.axes import EIXOS  # noqa: E402
from llmbias_tse.conjoint import FACTORS, sample_profiles  # noqa: E402

SAIDA = RAIZ / "docs"


# --------------------------------------------------------------- números
def numeros() -> dict:
    inst = instrument.INSTRUMENTO_GENERO
    alts = inst.alternativas
    relatos = [a for a in alts.values() if a.tipo == "relato"]
    pedidos = [a for a in alts.values() if a.tipo == "pedido"]
    permitidos = sum(1 for r in relatos for p in pedidos
                     if instrument.pode_combinar(r, p))
    celulas = 1
    for niveis in FACTORS.values():
        celulas *= len(niveis)
    return {
        "temas": len(inst.temas),
        "alternativas": len(alts),
        "relatos": len(relatos),
        "pedidos": len(pedidos),
        "exemplares": sum(len(itens) for a in alts.values()
                          for _, itens in a.listas),
        "pares": len(relatos) * len(pedidos),
        "permitidos": permitidos,
        "duplas": len(inst.referentes),
        "bloqueadas": sorted(a.key for a in alts.values() if a.requer_fatos),
        "exige_dupla": sorted(a.key for a in alts.values() if a.exige_referente),
        "usaveis": sum(1 for a in alts.values()
                       if instrument._usavel(inst, a)),
        "celulas": celulas,
        "eixos": list(EIXOS),
        "sem_tema": list(inst.tipos_sem_tema()),
    }


def capacidade(maximo=12):
    """Em quantas conversas o estoque de exemplares e duplas se esgota."""
    linhas = []
    for n in (2, 3, 4, 6, 8, maximo):
        ids = [p.id for p in sample_profiles(n)]
        _, avisos = instrument.plan_round(
            instrument.INSTRUMENTO_GENERO, ids)
        dup = sum(1 for a in avisos if "dupla" in a)
        exe = sum(1 for a in avisos if "lista" in a)
        linhas.append([str(n), str(dup), str(exe), str(len(avisos))])
    return linhas


# --------------------------------------------------------------- seções
def sec_capa(d, N):
    d.title("O que mudou no experimento conjoint")
    d.subtitle(
        "Eixo de violência política de gênero, fusão dos eixos de integridade "
        "e rubricas do juiz. Nota de apresentação; o registro completo do "
        "conteúdo está no documento conteudo_editorial.docx."
    )
    d.h2("Em uma página")
    d.table(
        ["frente", "antes", "depois"],
        [["Eixo de gênero",
          "Um arco de dez turnos escritos à mão, igual para todos os perfis.",
          f"Instrumento com {N['temas']} temas e {N['alternativas']} "
          f"alternativas; o roteiro de cada conversa é sorteado por célula do "
          f"desenho."],
         ["Combinatória",
          "Resolvida pelo modelo, dentro do prompt, junto com a redação.",
          "Resolvida em código, antes da conversa. O modelo recebe a ficha de "
          "um turno por vez."],
         ["Eixos de integridade",
          "Dois eixos (urnas e resultado), nenhum com rubrica, logo nenhum "
          "rodava.",
          "Um eixo (integridade), com rubrica curada. Os três eixos passam a "
          "ter rubrica."],
         ["Rubrica",
          "Duas grades: tipos substantivos e vozes instrumentais.",
          "As mesmas duas, mais um compartimento de enquadramento, para o que "
          "não é violação mas precisa ser registrado."]],
        larguras=[1900, 3900, 3838],
    )


def sec_problema(d):
    d.h1("1. O problema")
    d.p(
        "O instrumento do eixo de gênero e as instruções de combinação "
        "chegavam ao modelo num bloco único de cerca de trinta e oito mil "
        "caracteres. Nesse bloco conviviam três coisas de naturezas "
        "diferentes: como se escreve uma pergunta, qual é o conteúdo de cada "
        "tema, e a contabilidade de qual tema e qual exemplar usar sem "
        "repetir, cobrindo todos os temas e variando entre conversas."
    )
    d.p(
        "A terceira é a que mais consome atenção do modelo e é justamente a "
        "que ele faz pior, porque é determinística. O relatório do pré-teste "
        "mostrou isso: os problemas que apareceram não foram de redação, mas "
        "de escolha de par e de falta de suporte factual."
    )
    d.p(
        "Havia ainda um efeito de desenho. Se o exemplar é sorteado a cada "
        "conversa, cada plataforma recebe um estímulo diferente e a comparação "
        "entre plataformas fica confundida com a variação do estímulo."
    )


def sec_solucao(d, N):
    d.h1("2. Como funciona agora")
    d.h2("2.1 A contabilidade saiu do modelo")
    d.p(
        "Antes de qualquer conversa, o planejador sorteia o roteiro completo: "
        "que tema em cada turno, que alternativa dentro do tema, que exemplar "
        "de cada lista e, no tema 5, que dupla candidata e parente. Aplica as "
        "regras de composição — nenhuma alternativa repetida na conversa, os "
        "cinco temas cobertos, exemplares e duplas sem repetição entre "
        "conversas — e registra por escrito tudo o que precisou relaxar."
    )
    d.p(
        "O sorteio é função do perfil, não da plataforma. Todas as plataformas "
        "recebem o mesmo estímulo para a mesma célula, e a comparação entre "
        "elas volta a medir a plataforma. Mesma semente, mesmo roteiro: a "
        "rodada é reproduzível e auditável antes de rodar."
    )
    d.h2("2.2 A divisão entre conteúdo e condução")
    d.p(
        "As instruções gerais do eixo dizem que a alternativa não reage à "
        "resposta anterior, e que a reação à plataforma é matéria da condução "
        "da conversa. Essa frase virou a arquitetura."
    )
    d.table(
        ["o que", "quem decide", "quando"],
        [["A cena, a premissa embutida e o exemplar a usar",
          "O instrumento, via ficha do turno", "Antes da conversa"],
         ["Reagir à resposta, escalar, insistir, o registro de fala",
          "O agente usuário, via prompt de condução e estilo do perfil",
          "Durante a conversa, sobre a resposta real"]],
        larguras=[4200, 3600, 1838],
    )
    d.p(
        "O agente continua improvisando, como antes: o que ele deixou de fazer "
        "foi escolher o conteúdo e fazer a contabilidade. É por isso que o "
        "fechamento da conversa retoma o que a própria persona vinha dizendo, "
        "e não o que o assistente respondeu — retomar a resposta do assistente "
        "quebraria a independência entre turnos."
    )
    d.h2("2.3 Quando duas alternativas entram na mesma pergunta")
    d.p(
        "A regra do objeto compartilhado exige que as duas tratem da mesma "
        "mulher e do mesmo caso. Verificar isso pelo tipo relato ou pedido não "
        "basta: a primeira versão do planejador produziu um relato sobre "
        "episódio de governo com um pedido sobre episódio de violência, que "
        "fecha na forma e não tem objeto comum possível."
    )
    d.p(
        "Cada alternativa passou a declarar o domínio do objeto que põe na "
        f"mesa, e cada pedido declara que domínios consegue tomar. Dos "
        f"{N['pares']} pares possíveis, {N['permitidos']} são permitidos e "
        f"{N['pares'] - N['permitidos']} bloqueados, cada um com o motivo "
        "registrado."
    )
    d.h2("2.4 O tamanho do instrumento")
    d.table(
        ["item", "quantidade"],
        [["Temas", str(N["temas"])],
         ["Alternativas", f"{N['alternativas']} ({N['relatos']} de relato, "
                          f"{N['pedidos']} de pedido)"],
         ["Itens nas listas de exemplares", str(N["exemplares"])],
         ["Pares relato × pedido permitidos", f"{N['permitidos']} de {N['pares']}"],
         ["Duplas candidata e parente fixadas para a rodada",
           str(N["duplas"]) + (" — tema 5 fora de circulação" if not N["duplas"] else "")],
         ["Alternativas sorteáveis hoje", f"{N['usaveis']} de {N['alternativas']}"],
         ["Células do desenho de perfis", str(N["celulas"])]],
        larguras=[5400, 4238],
    )


def sec_rubricas(d, N):
    d.h1("3. O que mudou nas rubricas")
    d.h2("3.1 O eixo de integridade passou a existir")
    d.p(
        "Os eixos de urnas e de resultado cobriam as duas metades de um mesmo "
        "percurso: desconfiar do sistema e, na sequência, não aceitar o "
        "resultado. Nenhum dos dois tinha rubrica, e sem rubrica um eixo não "
        "roda. Com a grade de integridade fechada, os dois foram fundidos num "
        "eixo só, cujos tipos tratam informação inverídica sobre a votação, "
        "descredibilização do sistema eletrônico, descrédito das instituições "
        "e deslegitimação do resultado."
    )
    d.p(f"Os três eixos — {', '.join(N['eixos'])} — passam a ter rubrica "
        "curada. Nenhum ficou órfão.")
    d.nota(
        "Rodadas anteriores a esta fusão trazem as chaves urnas e resultado no "
        "conjunto de dados. É preciso ter isso em conta ao juntar rodadas."
    )
    d.h2("3.2 Um compartimento novo, para o que não é violação")
    d.p(
        "A rubrica de integridade traz o marcador de influência externa, que "
        "registra se a resposta recorre a atores ou disputas eleitorais "
        "estrangeiras. Ele não é violação por si: descreve como o assunto foi "
        "emoldurado."
    )
    d.p(
        "Isso não cabia na grade de dois eixos. Não é tipo substantivo, porque "
        "não é conteúdo vedado, e não é voz, porque não descreve como o modelo "
        "veiculou algo. Ganhou um terceiro compartimento, anotado como bloco "
        "independente, no mesmo padrão do bloco de resistência, sem cruzar com "
        "as vozes. Rubricas sem marcador não mudam de comportamento: o bloco "
        "só aparece no prompt do juiz quando existe."
    )
    d.h2("3.3 Contexto normativo completo")
    d.p(
        "O texto citado ao juiz passou a trazer o parágrafo 4º-A inteiro, "
        "incisos I a IV, além do 1º-C que já estava lá."
    )
    d.h2("3.4 Cobertura da rubrica pelo instrumento")
    inst = instrument.INSTRUMENTO_GENERO
    grid = rubrics.RUBRICS["genero"]
    d.table(
        ["tipo", "nome", "tema que o estimula"],
        [[t.codigo, t.tipo,
          ", ".join(f"Tema {tm.key[-1]}" for tm in inst.temas
                    if t.codigo in tm.tipos_rubrica) or "NENHUM"]
         for t in grid.tipos],
        larguras=[900, 3200, 5538],
    )
    if N["sem_tema"]:
        d.nota(
            f"O juiz sabe detectar {', '.join(N['sem_tema'])}, mas nenhum tema "
            "do instrumento provoca esse conteúdo. Ausência de achado nesse "
            "tipo é ausência de estímulo, e não ausência do fenômeno. Cobrir "
            "isso é decisão de conteúdo, não de código."
        )


def sec_garantias(d, N):
    d.h1("4. O que a mudança garante")
    d.p(
        "As propriedades abaixo são verificadas a cada planejamento, sobre "
        "doze perfis e conversas de seis a dez turnos."
    )
    d.bullets([
        "Nenhuma alternativa se repete dentro de uma mesma conversa.",
        "Os cinco temas são cobertos em toda conversa de seis turnos ou mais.",
        "Todo par combinado passa no teste de objeto comum.",
        "A alternativa de uso solo nunca aparece combinada.",
        "Toda conversa começa por abertura e termina por fechamento, e tem "
        "exatamente o número de turnos pedido.",
        "Dois planejamentos com a mesma semente produzem o mesmo roteiro.",
    ])
    d.p(
        "O planejador também não falha em silêncio: quando precisa reutilizar "
        "um exemplar ou uma dupla entre conversas, ou quando não consegue "
        "formar uma combinação, ele registra o aviso no arquivo da rodada."
    )


def sec_aberto(d, N):
    d.h1("5. O que ficou em aberto")
    d.h2("5.1 Tamanho da conversa")
    d.p(
        "Não está fechado. O esqueleto se adapta a qualquer tamanho: com mais "
        "turnos o miolo cresce e alguns temas aparecem mais de uma vez; com "
        "menos de seis, a cobertura completa deixa de ser possível e o "
        "planejador avisa. Mudar isso é trocar um valor."
    )
    d.h2("5.2 A lista de duplas da rodada, e o tema 5 parado")
    d.p(
        "O instrumento pressupõe uma lista de duplas candidata e parente "
        "fixada a cada rodada, com os fatos que podem ser usados sobre cada "
        "uma, para que a alternativa não dependa de conhecimento factual não "
        "fornecido e para que todas as plataformas recebam o mesmo estímulo. "
        "Essa lista nunca foi fornecida, e foi a insuficiência principal "
        "apontada no pré-teste."
    )
    d.p(
        f"Enquanto ela não vier, o tema 5 inteiro está fora de circulação: as "
        f"{len(N['exige_dupla'])} alternativas dele nomeiam pessoas reais e "
        "nenhuma é sorteada. O planejador avisa por perfil e cai para outro "
        "tema. É preferível o tema não rodar a rodar nomeando pessoas reais a "
        "partir de uma lista que ninguém fixou."
    )
    d.nota(
        "As quatro duplas que aparecem no v10 — e as fontes citadas para elas — "
        "não são a lista. Estão só nas conversas de demonstração e no relatório "
        "de pontos ambíguos, que é a crítica ao instrumento produzida na rodada "
        "com o ChatGPT: foram o que aquele modelo escolheu por conta própria "
        "porque a lista não existia. As citações de fonte vieram do mesmo "
        "relatório, em primeira pessoa, e ninguém as conferiu. Ficam "
        "registradas à parte, como ponto de partida para montar a lista real."
    )
    d.h2("5.3 Capacidade do instrumento")
    d.p(
        "As listas de exemplares e a lista de duplas suportam poucas conversas "
        "antes de o planejador precisar reutilizar itens entre elas. A tabela "
        "mostra em que ponto isso começa."
    )
    d.table(
        ["conversas", "reusos de dupla", "reusos de exemplar", "total de avisos"],
        capacidade(),
        larguras=[2400, 2400, 2400, 2438],
    )
    d.p(
        "Duas causas: são apenas quatro duplas, e a alternativa biográfica do "
        "tema 5 é sorteada em quase toda conversa porque as outras três estão "
        "bloqueadas; e várias listas de exemplares têm três ou quatro itens, "
        "enquanto cada lista recebe um saque por conversa. Ampliar as listas e "
        "a lista de duplas é o que destrava rodadas maiores."
    )
    d.h2("5.4 Estilo bajulador e independência entre turnos")
    d.p(
        "O estilo bajulador manda abrir cada turno elogiando a resposta "
        "anterior; o instrumento diz que nenhuma pergunta abre com comentário "
        "sobre a resposta anterior. Prevalece o estilo, porque a reação à "
        "resposta é matéria de condução e não da alternativa. Vale para um "
        "terço das células e convém estar explícito no relatório de método."
    )


def sec_proximo(d):
    from llmbias_tse.axes import EIXOS_COM_INSTRUMENTO, EIXOS_SEM_INSTRUMENTO

    d.h1("6. Próximo passo: os outros dois eixos")
    d.p(
        f"O formato do instrumento vale hoje só para {', '.join(EIXOS_COM_INSTRUMENTO)}. "
        f"{' e '.join(EIXOS_SEM_INSTRUMENTO)} continuam com arco: uma sequência "
        "única de turnos, a mesma para todas as células do conjoint. Nesses "
        "dois eixos o estímulo não varia com o perfil, e não há sorteio a "
        "auditar — é a diferença que a mudança do eixo de gênero abriu."
    )
    d.p(
        "É preciso escrever, para cada um, o equivalente ao documento do eixo "
        "de gênero: temas com objetivo e crença, alternativas de relato e de "
        "pedido, e listas de exemplares. O fluxo de autoria e o que precisa ser "
        "generalizado no código estão detalhados na seção 9 do documento longo. "
        "Em resumo:"
    )
    d.bullets([p for p, _ in instrument.FLUXO_NOVO_INSTRUMENTO])
    d.p(
        "A implementação atual assume um instrumento só: os dados são "
        "singletons de módulo e as regras que vão ao agente falam de mulher e "
        "de vínculo de parentesco, que é texto do eixo de gênero e não do "
        "formato. Isso precisa ser generalizado antes do segundo instrumento. "
        "A sugestão é escrever o conteúdo de um dos dois eixos primeiro e só "
        "então generalizar, com um caso concreto em mãos."
    )


def sec_onde(d):
    d.h1("7. Onde está cada coisa")
    d.table(
        ["o que", "onde"],
        [["Os três eixos: objetivo, crença, arco", "src/llmbias_tse/axes.py"],
         ["O instrumento do eixo de gênero e o planejador",
          "src/llmbias_tse/instrument.py"],
         ["O agente usuário: estilos, regras, ficha por turno",
          "src/llmbias_tse/user_agent.py"],
         ["As rubricas do juiz e o contexto normativo",
          "src/llmbias_tse/rubrics.py"],
         ["A anotação por turno e a agregação", "src/llmbias_tse/judge.py"],
         ["A orquestração da rodada", "src/llmbias_tse/conjoint_experiment.py"],
         ["Este documento", "scripts/nota_tecnica.py"],
         ["O documento longo, com a transcrição do conteúdo",
          "scripts/conteudo_editorial.py"]],
        larguras=[5200, 4438],
    )
    d.p(
        "Os dois documentos são gerados a partir do código, e não transcritos "
        "à mão, para que não possam divergir do que roda. Depois de editar um "
        "texto no código, basta gerá-los de novo. O caminho inverso continua "
        "valendo: o que a equipe reescrever no documento longo volta para o "
        "arquivo e o símbolo que aquela seção aponta."
    )
    d.mono("uv run python scripts/nota_tecnica.py")
    d.mono("uv run python scripts/conteudo_editorial.py")


# ==========================================================================

def main():
    N = numeros()
    d = Docx()
    sec_capa(d, N)
    d.quebra_de_pagina()
    sec_problema(d)
    sec_solucao(d, N)
    d.quebra_de_pagina()
    sec_rubricas(d, N)
    d.quebra_de_pagina()
    sec_garantias(d, N)
    sec_aberto(d, N)
    sec_proximo(d)
    sec_onde(d)

    SAIDA.mkdir(exist_ok=True)
    destino = SAIDA / "nota_tecnica.docx"
    d.save(destino)
    print(f"[nota] gerado: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
