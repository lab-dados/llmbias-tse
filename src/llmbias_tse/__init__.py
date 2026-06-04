"""llmbias-tse — POC de coleta automatizada de respostas de ferramentas de
IA generativa via automação de navegador (Patchright + Chrome real/CDP).

Subcomandos:
    launch   abre o Chrome na porta de debug com perfil persistente (login manual)
    run      conecta no Chrome logado, manda prompts e salva as trocas
    tools    lista as ferramentas disponíveis
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

    sub.add_parser("tools", help="lista as ferramentas disponíveis")

    args = parser.parse_args()

    if args.cmd == "launch":
        from .browser import main_launch
        sys.exit(main_launch())
    elif args.cmd == "run":
        from .poc import run
        sys.exit(run(args.tools, args.n, args.seed, args.session))
    elif args.cmd == "tools":
        from .drivers import REGISTRY
        for name in REGISTRY:
            print(name)
        sys.exit(0)
