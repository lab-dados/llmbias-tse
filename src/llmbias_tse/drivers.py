"""Drivers por ferramenta: como abrir um chat novo, digitar e ler a resposta.

Cada UI tem seus próprios seletores. Eles MUDAM com frequência — quando
um driver parar de capturar, ajuste os seletores aqui (e olhe o snapshot
HTML salvo em data/<run>/artifacts/... para achar o seletor certo).

Estratégia comum (BaseDriver.send):
    1. navega para a URL de "chat novo" (conversa limpa por prompt);
    2. digita o prompt no composer;
    3. envia (Enter);
    4. espera surgir um balão de resposta novo e estabilizar o texto;
    5. devolve o texto.

WhatsApp Web é suficientemente diferente para sobrescrever send().
"""

from __future__ import annotations

import re
import time

from . import capture


class BaseDriver:
    name: str = "base"
    new_chat_url: str = ""
    # Seletores do composer (tentados em ordem; textarea ou contenteditable).
    composer_selectors: list[str] = []
    # Seletor que casa com TODOS os balões de resposta do assistente.
    response_selector: str = ""
    # Seletores visíveis ENQUANTO a resposta é gerada (ex.: botão de parar).
    # Quando somem, a geração terminou. Se vazio, cai no fallback de
    # estabilidade-por-texto (menos robusto).
    busy_selectors: list[str] = []
    # Tempo extra após carregar a página antes de digitar.
    settle_s: float = 1.5
    # Teto de espera pela resposta (ferramentas com busca na web são lentas).
    response_timeout: float = 240.0

    def open_new_chat(self, page) -> None:
        page.goto(self.new_chat_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(self.settle_s)

    def send(self, page, prompt: str) -> str:
        self.open_new_chat(page)
        baseline = capture.count_responses(page, self.response_selector)
        capture.type_text(page, self.composer_selectors, prompt)
        page.keyboard.press("Enter")
        capture.wait_for_new_response(
            page, self.response_selector, baseline, timeout=40
        )
        if self.busy_selectors:
            return capture.wait_until_idle(
                page, self.response_selector, self.busy_selectors,
                timeout=self.response_timeout,
            )
        return capture.wait_stable_text(
            page, self.response_selector, timeout=self.response_timeout
        )

    def conversation_url(self, page) -> str:
        return page.url


class ChatGPT(BaseDriver):
    name = "chatgpt"
    new_chat_url = "https://chatgpt.com/"
    composer_selectors = [
        "#prompt-textarea",
        "div[contenteditable='true']#prompt-textarea",
        "textarea[data-testid='prompt-textarea']",
        "textarea",
    ]
    response_selector = "[data-message-author-role='assistant']"
    # Confirmado por instrumentação: stop-button visível durante a geração.
    busy_selectors = [
        "button[data-testid='stop-button']",
        "button[aria-label*='Stop']",
        "button[aria-label*='Parar']",
    ]


class Gemini(BaseDriver):
    name = "gemini"
    new_chat_url = "https://gemini.google.com/app"
    composer_selectors = [
        "div.ql-editor[contenteditable='true']",
        "rich-textarea div[contenteditable='true']",
        "textarea",
    ]
    response_selector = "message-content, .model-response-text"
    busy_selectors = [
        "button[aria-label*='Stop']",
        "button[aria-label*='Parar']",
        "button.send-button.stop",
    ]
    settle_s = 2.0


class Claude(BaseDriver):
    name = "claude"
    new_chat_url = "https://claude.ai/new"
    composer_selectors = [
        "div[contenteditable='true'].ProseMirror",
        "div[contenteditable='true']",
    ]
    response_selector = "div.font-claude-message, [data-testid='assistant-message']"
    busy_selectors = [
        "button[aria-label*='Stop']",
        "button[aria-label*='Parar']",
    ]
    settle_s = 2.0


class MetaAI(BaseDriver):
    name = "metaai"
    new_chat_url = "https://www.meta.ai/"
    composer_selectors = [
        "textarea",
        "div[contenteditable='true']",
    ]
    # Best-effort; ajuste após inspecionar o snapshot na 1ª execução.
    response_selector = "div[dir='auto']"
    settle_s = 2.5


class WhatsAppMetaAI(BaseDriver):
    """Meta AI dentro do WhatsApp Web.

    Requer QR escaneado uma vez (persiste no perfil) E a conversa do
    Meta AI **aberta manualmente** (chat ativo). O driver opera no chat
    ativo — não navega/busca (a busca do WhatsApp Web é volátil).

    Contexto limpo por prompt: como não há "chat novo" no WhatsApp, envia
    `/reset-all-ais` antes de cada prompt para zerar a memória do Meta AI.

    Seletores confirmados por inspeção (jun/2026); a UI muda — reinspecione
    com tmp/inspect_wa.py se quebrar.
    """

    name = "whatsapp_metaai"
    new_chat_url = "https://web.whatsapp.com/"
    # Regex do timestamp que o WhatsApp cola no fim do balão (ex.: "\n\n09:56").
    _ts_re = re.compile(r"\s*\d{1,2}:\d{2}(\s?[AaPp][Mm])?\s*$")
    # Composer do chat ativo (aria-label "Type a message to Meta AI").
    composer_selectors = [
        "[role='textbox'][data-tab='10']",
        "footer [role='textbox']",
    ]
    # Balões recebidos (do Meta AI). O último é a resposta.
    response_selector = "div.message-in"
    reset_command = "/reset-all-ais"

    def open_new_chat(self, page) -> None:
        if "web.whatsapp.com" not in page.url:
            page.goto(self.new_chat_url, wait_until="domcontentloaded", timeout=90000)
        # Garante que há um chat ativo com composer (Meta AI aberto à mão).
        capture.first_visible(page, self.composer_selectors, timeout=30)

    def _send_raw(self, page, text: str) -> None:
        box = capture.first_visible(page, self.composer_selectors)
        box.click()
        page.keyboard.type(text, delay=8)
        page.keyboard.press("Enter")

    def reset(self, page) -> None:
        """Zera a memória do Meta AI antes do próximo prompt."""
        self._send_raw(page, self.reset_command)
        time.sleep(3.0)  # deixa a confirmação chegar

    def send(self, page, prompt: str) -> str:
        self.open_new_chat(page)
        self.reset(page)
        baseline = capture.count_responses(page, self.response_selector)
        self._send_raw(page, prompt)
        capture.wait_for_new_response(
            page, self.response_selector, baseline, timeout=60
        )
        text = capture.wait_stable_text(
            page, self.response_selector, timeout=self.response_timeout
        )
        return self._ts_re.sub("", text).strip()


# Registro: nome -> classe. A CLI usa essas chaves.
REGISTRY: dict[str, type[BaseDriver]] = {
    d.name: d
    for d in (ChatGPT, Gemini, Claude, MetaAI, WhatsAppMetaAI)
}

DEFAULT_TOOLS = ["chatgpt", "gemini", "claude", "metaai"]
