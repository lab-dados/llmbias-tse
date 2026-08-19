"""llmbias-tse — POC de coleta automatizada de respostas de ferramentas de
IA generativa via automação de navegador (Patchright + Chrome real/CDP).

Subcomandos:
    launch      abre o Chrome na porta de debug com perfil persistente (login manual)
    run         conecta no Chrome logado, manda prompts e salva as trocas
    experiment  roda o experimento ESEB (conversas curtas vs longas por persona)
    tools       lista as ferramentas disponíveis
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="llmbias-tse", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("launch", help="abre o Chrome com perfil persistente (login)")

    p_run = sub.add_parser("run", help="coleta: manda prompts e salva as trocas")
    p_run.add_argument(
        "--tools", nargs="+", default=None,
        help="ferramentas (default: chatgpt gemini claude metaai)",
    )
    p_run.add_argument("--n", type=int, default=2, help="prompts por ferramenta")
    p_run.add_argument("--seed", type=int, default=None, help="semente do sorteio")
    p_run.add_argument(
        "--session", choices=["logged_in", "anon", "both"], default="logged_in",
        help="sessão: logado, deslogado (anônimo) ou ambos",
    )

    p_exp = sub.add_parser(
        "experiment", help="experimento ESEB: conversas curtas vs longas",
    )
    p_exp.add_argument("--tool", default="chatgpt", help="ferramenta (default: chatgpt)")
    p_exp.add_argument(
        "--personas", nargs="+", default=None,
        help="ids de persona (default: selected_personas do long_conversations.json)",
    )
    p_exp.add_argument(
        "--dimensions", nargs="+", default=None,
        help="dimensões (default: todas as 6 do arquivo)",
    )
    p_exp.add_argument(
        "--kinds", nargs="+", default=None, choices=["short", "long"],
        help="tipos de conversa (default: short long)",
    )
    p_exp.add_argument(
        "--session", choices=["logged_in", "anon"], default="logged_in",
        help="sessão (default: logged_in)",
    )
    p_exp.add_argument(
        "--run-id", default=None,
        help="reutiliza/retoma um run existente (pula conversas já concluídas)",
    )
    p_exp.add_argument(
        "--turn-delay", type=float, default=3.0,
        help="pausa entre turnos, em s (evita rate limit; default 3)",
    )
    p_exp.add_argument(
        "--conv-delay", type=float, default=8.0,
        help="pausa entre conversas, em s (evita rate limit; default 8)",
    )

    p_cj = sub.add_parser(
        "conjoint",
        help="conjoint analysis multi-plataforma (LLM-as-user + LLM-as-judge 4.0)",
    )
    p_cj.add_argument("--n-profiles", type=int, default=3,
                      help="nº de perfis sorteados (default 3, pré-teste)")
    p_cj.add_argument("--seed", type=int, default=2026,
                      help="semente do sorteio de perfis (default 2026)")
    p_cj.add_argument("--platforms", nargs="+", default=None,
                      help="plataformas (default: gemini chatgpt claude "
                           "deepseek grok)")
    p_cj.add_argument("--eixos", nargs="+", default=None,
                      help="eixos com rubrica 4.0 (default: voto genero)")
    p_cj.add_argument("--n-turns", type=int, default=None,
                      help="sobrepoe os turnos por conversa em TODOS os eixos "
                           "(default: cada eixo decide — genero 7, demais 10)")
    p_cj.add_argument("--run-id", default=None,
                      help="reutiliza/retoma um run existente")
    p_cj.add_argument("--model", default=None,
                      help="modelo Gemini da API (default: gemini-3.5-flash)")
    p_cj.add_argument("--turn-delay", type=float, default=3.0,
                      help="pausa entre turnos, em s (default 3)")
    p_cj.add_argument("--conv-delay", type=float, default=8.0,
                      help="pausa entre conversas, em s (default 8)")
    p_cj.add_argument("--limit", type=int, default=None,
                      help="limita o nº de conversas geradas (smoke test)")
    p_cj.add_argument("--phase", choices=["all", "generate", "judge"],
                      default="all",
                      help="fase: tudo, só gerar conversas, ou só julgar+base")

    sub.add_parser("tools", help="lista as ferramentas disponíveis")

    args = parser.parse_args()

    if args.cmd == "launch":
        from .browser import main_launch
        sys.exit(main_launch())
    elif args.cmd == "run":
        from .poc import run
        sys.exit(run(args.tools, args.n, args.seed, args.session))
    elif args.cmd == "experiment":
        from .experiment import run as run_experiment
        sys.exit(run_experiment(
            tool=args.tool, personas=args.personas,
            dimensions=args.dimensions, kinds=args.kinds, session=args.session,
            run_id=args.run_id, turn_delay=args.turn_delay,
            conv_delay=args.conv_delay,
        ))
    elif args.cmd == "conjoint":
        from .conjoint_experiment import run as run_conjoint
        sys.exit(run_conjoint(
            n_profiles=args.n_profiles, seed=args.seed,
            platforms=args.platforms, eixos=args.eixos, n_turns=args.n_turns,
            run_id=args.run_id, model=args.model, turn_delay=args.turn_delay,
            conv_delay=args.conv_delay, limit=args.limit, phase=args.phase,
        ))
    elif args.cmd == "tools":
        from .drivers import REGISTRY
        for name in REGISTRY:
            print(name)
        sys.exit(0)
