"""Lança o Google Chrome real numa porta de debug (CDP) com perfil
persistente, e conecta o Patchright a ele.

Padrão herdado do projeto monitor-italia: o Chrome roda como processo
separado, numa porta (`--remote-debugging-port`), com `--user-data-dir`
dedicado. Assim os cookies/sessões **persistem** — você loga **uma vez**
em cada ferramenta (ChatGPT, Gemini, Claude, Meta AI, WhatsApp Web) e o
script conecta na aba já logada quantas vezes quiser, sem relançar o
browser nem refazer login.

Fluxo:
    1. `launch_chrome()`  -> abre o Chrome visível na porta 9222.
    2. (manual) você faz login em cada ferramenta.
    3. `connect()`        -> Patchright conecta via CDP e devolve o context.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Diretório do perfil persistente (cookies, logins). Fora do versionamento.
PROFILE_DIR = Path(os.environ.get("LLMBIAS_PROFILE", "./tmp/profile")).resolve()
# 9333 por padrão para coexistir com outros projetos que usam 9222.
CDP_PORT = int(os.environ.get("LLMBIAS_CDP_PORT", "9333"))
CDP_URL = f"http://localhost:{CDP_PORT}"

# Caminhos comuns do Chrome no Windows; sobrescreva com CHROME_PATH.
_CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH"),
    rf"{os.environ.get('ProgramFiles', '')}\Google\Chrome\Application\chrome.exe",
    rf"{os.environ.get('ProgramFiles(x86)', '')}\Google\Chrome\Application\chrome.exe",
    rf"{os.environ.get('LOCALAPPDATA', '')}\Google\Chrome\Application\chrome.exe",
]


def find_chrome() -> str:
    for cand in _CHROME_CANDIDATES:
        if cand and Path(cand).exists():
            return cand
    raise FileNotFoundError(
        "chrome.exe não encontrado. Instale o Google Chrome ou defina "
        "CHROME_PATH=...\\chrome.exe"
    )


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def launch_chrome(wait_ready: bool = True) -> subprocess.Popen | None:
    """Abre o Chrome na porta CDP com o perfil persistente.

    Se a porta já estiver aberta (Chrome já rodando), não faz nada.
    """
    if _port_open(CDP_PORT):
        print(f"[browser] Chrome já está na porta {CDP_PORT} — reutilizando.")
        return None

    chrome = find_chrome()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        # Não estrangular abas em segundo plano/ocultas. Sem isto, o Chrome
        # atrasa os timers da página quando a janela não está visível, e a
        # detecção de fim-de-resposta (sumiço do botão de parar) trava até o
        # timeout. Com estas flags a coleta roda em velocidade total mesmo
        # com a janela atrás de outras.
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-features=CalculateNativeWinOcclusion",
    ]
    print(f"[browser] Lançando Chrome: porta={CDP_PORT} perfil={PROFILE_DIR}")
    proc = subprocess.Popen(args)

    if wait_ready:
        for _ in range(40):  # ~20s
            if _port_open(CDP_PORT):
                print(f"[browser] CDP pronto em {CDP_URL}")
                break
            time.sleep(0.5)
        else:
            print("[browser] AVISO: porta CDP não respondeu a tempo.")
    return proc


def connect(playwright):
    """Conecta o Patchright ao Chrome via CDP e devolve (browser, context).

    `playwright` é o objeto retornado por `sync_playwright().start()` /
    `with sync_playwright() as playwright`.
    """
    if not _port_open(CDP_PORT):
        raise RuntimeError(
            f"Nada escutando em {CDP_URL}. Rode `uv run llmbias-tse launch` "
            "primeiro e faça login nas ferramentas."
        )
    browser = playwright.chromium.connect_over_cdp(CDP_URL)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    return browser, ctx


def context_for_session(browser, default_ctx, session: str):
    """Devolve o context para a sessão pedida.

    - "logged_in": o context persistente (perfil com seus logins).
    - "anon":      um context isolado novo (sem cookies = deslogado),
                   equivalente a uma janela anônima. O chamador deve
                   fechá-lo (`ctx.close()`) ao terminar.
    """
    if session == "anon":
        return browser.new_context()
    return default_ctx


def main_launch() -> int:
    """Entry point do subcomando `launch`: abre o Chrome e segura o terminal."""
    proc = launch_chrome()
    print()
    print("=" * 60)
    print("Chrome aberto com perfil persistente.")
    print("Faça login (uma vez) nas ferramentas que vai testar:")
    print("  - ChatGPT:   https://chatgpt.com")
    print("  - Gemini:    https://gemini.google.com")
    print("  - Claude:    https://claude.ai")
    print("  - Meta AI:   https://www.meta.ai")
    print("  - WhatsApp:  https://web.whatsapp.com  (escaneie o QR)")
    print()
    print("Depois, em outro terminal: uv run llmbias-tse run")
    print("Mantenha este terminal aberto (fecha o Chrome ao sair). Ctrl+C p/ sair.")
    print("=" * 60)
    try:
        if proc is not None:
            proc.wait()
        else:
            while True:
                time.sleep(60)
    except KeyboardInterrupt:
        print("\n[browser] Encerrando.")
    return 0


if __name__ == "__main__":
    sys.exit(main_launch())
