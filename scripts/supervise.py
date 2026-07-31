"""Supervisor resiliente do experimento conjoint.

Roda a coleta UMA PLATAFORMA DE CADA VEZ (serial, uma conexão CDP por vez, sem
a contenção que trava conexões simultâneas) e, se o processo cair, travar ou
sair sem terminar, RELANÇA sozinho (retomando de onde parou via --run-id), com
backoff exponencial para lidar com bloqueio por uso (rate-limit). Ao final,
julga e monta a base.

Uso (no terminal, com o Chrome aberto e logado via `llmbias-tse launch`):

    uv run python scripts/supervise.py --run-id pretest1 --n-profiles 3

Flags: --platforms, --eixos, --n-turns, --cooldown (base do backoff, s),
--max-cooldown, --max-stalls (quantas tentativas SEM progresso por plataforma
antes de pular para a próxima).

O log fica em data/<run-id>/supervise.log (append). Ctrl+C encerra.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_PLATFORMS = ["gemini", "deepseek", "chatgpt", "grok", "claude"]
DEFAULT_EIXOS = ["voto", "genero"]


def log(run_dir: Path, msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "supervise.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def conv_done(run_dir: Path, conv_id: str, n_turns: int) -> bool:
    p = run_dir / "conversations" / f"{conv_id}.json"
    if not p.exists():
        return False
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    turns = rec.get("turns", [])
    return len(turns) == n_turns and all(t.get("ok") for t in turns)


def platform_counts(run_dir: Path, platform: str, profile_ids, eixos, n_turns):
    done = sum(
        conv_done(run_dir, f"{platform}_{pid}_{e}", n_turns)
        for pid in profile_ids for e in eixos
    )
    return done, len(profile_ids) * len(eixos)


def load_profile_ids(run_dir: Path):
    p = run_dir / "profiles.json"
    if p.exists():
        try:
            return [x["id"] for x in json.loads(p.read_text(encoding="utf-8"))]
        except Exception:
            pass
    return None  # ainda não sorteado


def run_once(run_id, platform, eixos, n_profiles, n_turns, run_dir):
    cmd = [
        sys.executable, "-m", "llmbias_tse", "conjoint",
        "--run-id", run_id, "--phase", "generate",
        "--platforms", platform, "--eixos", *eixos,
        "--n-profiles", str(n_profiles), "--n-turns", str(n_turns),
    ]
    try:
        # Captura a saída para diagnóstico (streamando também para o terminal via
        # tee manual seria mais complexo; aqui priorizamos poder inspecionar o
        # erro depois). O tail vai para data/<run>/last_error_<plataforma>.txt.
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        # sempre mostra o tail no terminal também
        tail = "\n".join(out.strip().splitlines()[-12:])
        if tail:
            print(tail, flush=True)
        if r.returncode != 0:
            try:
                (run_dir / f"last_error_{platform}.txt").write_text(
                    out[-8000:], encoding="utf-8")
            except Exception:
                pass
        return r.returncode
    except KeyboardInterrupt:
        raise
    except Exception as e:  # noqa: BLE001
        return f"exceção do subprocess: {e!r}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--n-profiles", type=int, default=3)
    ap.add_argument("--platforms", nargs="+", default=DEFAULT_PLATFORMS)
    ap.add_argument("--eixos", nargs="+", default=DEFAULT_EIXOS)
    ap.add_argument("--n-turns", type=int, default=10)
    ap.add_argument("--cooldown", type=float, default=20.0,
                    help="espera base entre tentativas (s)")
    ap.add_argument("--max-cooldown", type=float, default=420.0,
                    help="teto do backoff (s)")
    ap.add_argument("--max-stalls", type=int, default=8,
                    help="tentativas SEM progresso por plataforma antes de pular")
    args = ap.parse_args()

    run_dir = Path("data") / args.run_id
    log(run_dir, f"=== supervisor iniciado | run={args.run_id} | "
                 f"plataformas={args.platforms} | eixos={args.eixos} | "
                 f"perfis={args.n_profiles} | turnos={args.n_turns} ===")

    try:
        for platform in args.platforms:
            cooldown = args.cooldown
            stalls = 0
            while True:
                pids = load_profile_ids(run_dir)
                if pids is None:
                    done, total = 0, args.n_profiles * len(args.eixos)
                else:
                    done, total = platform_counts(
                        run_dir, platform, pids, args.eixos, args.n_turns)
                if done >= total:
                    log(run_dir, f"[{platform}] COMPLETA ({done}/{total})")
                    break
                if stalls >= args.max_stalls:
                    log(run_dir, f"[{platform}] PULANDO após {stalls} tentativas "
                                 f"sem progresso ({done}/{total}). Rode o "
                                 f"supervisor de novo mais tarde para retomar.")
                    break
                log(run_dir, f"[{platform}] {done}/{total} feitas — rodando "
                             f"(tentativa, stalls={stalls})...")
                rc = run_once(args.run_id, platform, args.eixos,
                              args.n_profiles, args.n_turns, run_dir)
                # progresso?
                pids2 = load_profile_ids(run_dir)
                done2 = (platform_counts(run_dir, platform, pids2, args.eixos,
                                         args.n_turns)[0] if pids2 else 0)
                if done2 > done:
                    log(run_dir, f"[{platform}] avançou {done}->{done2} "
                                 f"(saída={rc}); segue")
                    cooldown = args.cooldown  # reset backoff
                    stalls = 0
                else:
                    stalls += 1
                    log(run_dir, f"[{platform}] SEM progresso (saída={rc}); "
                                 f"aguardando {int(cooldown)}s (backoff, "
                                 f"stall {stalls}/{args.max_stalls})")
                    time.sleep(cooldown)
                    cooldown = min(cooldown * 2, args.max_cooldown)

        log(run_dir, "=== coleta encerrada; julgando + montando base ===")
        subprocess.run([
            sys.executable, "-m", "llmbias_tse", "conjoint",
            "--run-id", args.run_id, "--phase", "judge",
            "--platforms", *args.platforms, "--eixos", *args.eixos,
            "--n-profiles", str(args.n_profiles), "--n-turns", str(args.n_turns),
        ])
        log(run_dir, "=== FIM (base em data/%s/dataset.csv) ===" % args.run_id)
    except KeyboardInterrupt:
        log(run_dir, "=== interrompido pelo usuário (Ctrl+C) ===")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
