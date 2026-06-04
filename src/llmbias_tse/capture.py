"""Helpers genéricos de interação e captura de resposta.

As UIs das ferramentas mudam com frequência e fazem *streaming* da
resposta (o texto cresce token a token). Em vez de depender de um botão
"parar de gerar" específico de cada uma, a estratégia aqui é genérica e
robusta: ler o texto do último balão de resposta repetidamente e
considerar a resposta **pronta quando o texto para de mudar** por alguns
segundos (estabilização), com um teto de tempo.
"""

from __future__ import annotations

import time
from pathlib import Path


def first_visible(page, selectors: list[str], timeout: float = 15.0):
    """Devolve o primeiro locator visível dentre `selectors` (tenta em ordem).

    Faz polling até `timeout`. Levanta TimeoutError se nenhum aparecer.
    """
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception as e:  # selector inválido / detached
                last_err = e
        time.sleep(0.25)
    raise TimeoutError(
        f"Nenhum dos seletores ficou visível em {timeout}s: {selectors} "
        f"(último erro: {last_err!r})"
    )


def type_text(page, selectors: list[str], text: str) -> None:
    """Foca o composer e digita o texto (funciona em textarea e contenteditable)."""
    box = first_visible(page, selectors)
    box.click()
    # `fill` não funciona bem em contenteditable; usar type via teclado.
    page.keyboard.type(text, delay=8)


def any_visible(page, selectors: list[str]) -> bool:
    """True se ao menos um dos seletores estiver visível agora."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return True
        except Exception:
            continue
    return False


def count_responses(page, response_selector: str) -> int:
    try:
        return page.locator(response_selector).count()
    except Exception:
        return 0


def wait_for_new_response(
    page, response_selector: str, baseline: int, timeout: float = 30.0
) -> None:
    """Espera surgir um novo balão de resposta (count > baseline)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if count_responses(page, response_selector) > baseline:
            return
        time.sleep(0.25)
    raise TimeoutError(
        f"Resposta não apareceu em {timeout}s (selector={response_selector!r})"
    )


def wait_stable_text(
    page,
    response_selector: str,
    stable_for: float = 2.5,
    timeout: float = 240.0,
    poll: float = 0.5,
) -> str:
    """Lê o texto do ÚLTIMO balão de resposta até ele estabilizar.

    Considera pronto quando o texto não muda por `stable_for` segundos.
    Retorna o texto final. Levanta TimeoutError se nunca estabilizar.
    """
    deadline = time.time() + timeout
    last_text = None
    stable_since = None
    while time.time() < deadline:
        try:
            loc = page.locator(response_selector).last
            text = loc.inner_text() if loc.count() > 0 else ""
        except Exception:
            text = last_text or ""

        if text and text == last_text:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= stable_for:
                return text.strip()
        else:
            stable_since = None
            last_text = text
        time.sleep(poll)

    if last_text:
        return last_text.strip()  # devolve o que tiver, mesmo sem estabilizar
    raise TimeoutError(
        f"Resposta não estabilizou em {timeout}s (selector={response_selector!r})"
    )


def wait_until_idle(
    page,
    response_selector: str,
    busy_selectors: list[str],
    quiet_for: float = 1.8,
    timeout: float = 240.0,
    poll: float = 0.4,
) -> str:
    """Espera a geração terminar usando o indicador de 'gerando' (ex.: botão
    de parar). Pronto quando NENHUM `busy_selector` está visível por
    `quiet_for` segundos seguidos e já há texto de resposta.

    Mais robusto que estabilidade-por-texto: imune a chips de citação,
    cursores e contadores que re-renderizam dentro do balão.
    """
    deadline = time.time() + timeout
    idle_since = None
    while time.time() < deadline:
        busy = any_visible(page, busy_selectors)
        try:
            loc = page.locator(response_selector).last
            text = loc.inner_text() if loc.count() > 0 else ""
        except Exception:
            text = ""

        if not busy and text.strip():
            if idle_since is None:
                idle_since = time.time()
            elif time.time() - idle_since >= quiet_for:
                return text.strip()
        else:
            idle_since = None
        time.sleep(poll)

    # Timeout: devolve o que tiver, se houver.
    try:
        text = page.locator(response_selector).last.inner_text()
        if text.strip():
            return text.strip()
    except Exception:
        pass
    raise TimeoutError(
        f"Geração não terminou em {timeout}s "
        f"(response={response_selector!r} busy={busy_selectors})"
    )


def snapshot(page, out_dir: Path, label: str) -> dict[str, str]:
    """Salva HTML + screenshot da página. Devolve os caminhos relativos."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    html_path = out_dir / f"{label}.html"
    png_path = out_dir / f"{label}.png"
    try:
        html_path.write_text(page.content(), encoding="utf-8")
        paths["html"] = str(html_path)
    except Exception:
        pass
    try:
        page.screenshot(path=str(png_path), full_page=True)
        paths["png"] = str(png_path)
    except Exception:
        pass
    return paths
