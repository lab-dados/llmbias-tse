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

import os
import re
import time

from . import capture


def _has_leaf_text(page, needles: list[str]) -> bool:
    """True se algum nó-folha visível contém (case-insensitive) uma das
    substrings. Usado para confirmar indicadores de modo (ex.: banner de
    conversa temporária/privada). Robusto a ocultação: varre o texto do DOM,
    não a tela."""
    lowered = [n.lower() for n in needles]
    try:
        return bool(page.evaluate(
            r"""(needles) => {
              const els = document.querySelectorAll('*');
              for (const el of els) {
                if (el.children.length === 0) {
                  const t = (el.textContent || '').trim().toLowerCase();
                  if (t && needles.some(n => t.includes(n))) return true;
                }
              }
              return false;
            }""",
            lowered,
        ))
    except Exception:
        return False


class BaseDriver:
    name: str = "base"
    new_chat_url: str = ""
    # Seletores do composer (tentados em ordem; textarea ou contenteditable).
    composer_selectors: list[str] = []
    # Se setado, CLICA este botão pra enviar (em vez de apertar Enter). Útil
    # em UIs onde Enter não submete (ex.: Grok).
    submit_selector: str = ""
    # Seletor que casa com TODOS os balões de resposta do assistente
    # (usado pra CONTAR balões e detectar um novo).
    response_selector: str = ""
    # Seletor do NÓ DE CONTEÚDO de onde extrair o texto (mais limpo que o
    # balão inteiro, sem rótulos de botões). Se vazio, usa response_selector.
    content_selector: str = ""
    # Seletor das mensagens DO USUÁRIO (pra evitar reenviar prompt já postado
    # numa re-tentativa após rate limit). Vazio = não checa.
    user_selector: str = ""
    # Seletores visíveis ENQUANTO a resposta é gerada (ex.: botão de parar).
    # Quando somem, a geração terminou. Se vazio, cai no fallback de
    # estabilidade-por-texto (menos robusto).
    busy_selectors: list[str] = []
    # Marcadores de texto de FASE INTERMEDIÁRIA (thinking/pesquisa) que NÃO são
    # a resposta final. Enquanto o texto lido contiver algum deles, a detecção
    # de fim NÃO retorna (evita capturar "Searching the web"/status e truncar).
    pending_markers: list[str] = []
    # Tempo extra após carregar a página antes de digitar.
    settle_s: float = 1.5
    # Teto de espera pela resposta (ferramentas com busca na web são lentas).
    response_timeout: float = 240.0
    # Teto de espera pela resposta COMEÇAR a aparecer (novo balão / texto novo).
    # Mensagens longas demoram mais pra disparar; sobrescreva se precisar.
    start_timeout: float = 90.0
    # Quantas vezes re-tentar um turno que falhou por timeout (resposta não
    # começou/terminou). O guard `user_selector` evita repostar a mensagem se
    # ela já foi parar no chat; sem `user_selector`, mantenha 0.
    submit_retries: int = 0

    def open_new_chat(self, page) -> None:
        page.goto(self.new_chat_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(self.settle_s)

    def submit(self, page, prompt: str, max_limit_waits: int | None = None) -> str:
        """Envia UM prompt no chat ATUAL (sem abrir chat novo) e captura a
        resposta. É o tijolo das conversas multi-turno.

        Resiliente a rate limit ("Too many requests"): quando detecta o modal,
        ESPERA **passivamente** (fecha o modal e dorme, com backoff
        exponencial) e só então re-tenta enviar. NÃO recarrega a página pra
        testar: recarregar refaz requisições (lista de conversas etc.) e
        **mantém o limite vivo** — o jeito de sair é ficar quieto e esperar.
        """
        # Paciência de rate-limit configurável por env (para runs autônomos que
        # ciclam plataformas: falhar rápido numa bloqueada e ir para a próxima).
        if max_limit_waits is None:
            max_limit_waits = int(os.environ.get("LLMBIAS_MAX_LIMIT_WAITS", "6"))
        backoff = float(os.environ.get("LLMBIAS_RL_BACKOFF", "90"))
        attempt = 0
        retries_left = self.submit_retries
        # Nº de balões do usuário ANTES deste turno. Numa re-tentativa, se a
        # contagem subiu, a mensagem já entrou — não reposta (count é imune a
        # colapso de texto e a prefixos repetidos entre turnos).
        user_baseline = (capture.count_responses(page, self.user_selector)
                         if self.user_selector else 0)
        while True:
            if capture.is_rate_limited(page):
                attempt += 1
                if attempt > max_limit_waits:
                    raise capture.RateLimited(
                        f"rate limit não liberou após {attempt-1} esperas"
                    )
                capture.dismiss_rate_limit(page)
                time.sleep(2.0)  # deixa o modal fechar
                print(f"[driver:{self.name}] rate limit — aguardando "
                      f"{int(backoff)}s sem requisições (espera "
                      f"{attempt}/{max_limit_waits})")
                time.sleep(backoff)
                backoff = min(backoff * 2, 600.0)
                continue
            try:
                return self._submit_once(page, prompt, user_baseline)
            except Exception as e:
                if capture.is_rate_limited(page):
                    continue  # virou rate limit: volta pro topo e espera
                if retries_left > 0:
                    n = self.submit_retries - retries_left  # 0,1,2,...
                    retries_left -= 1
                    # Backoff exponencial: bloqueios transitórios do Gemini
                    # ("Algo deu errado") são cumulativos — esperar passivamente
                    # deixa resetar. NÃO recarrega a página (manteria o limite).
                    wait = min(15.0 * (2 ** n), 120.0)
                    print(f"[driver:{self.name}] turno falhou ({e!r}); "
                          f"aguardando {int(wait)}s antes de re-tentar "
                          f"({retries_left} restantes)")
                    time.sleep(wait)
                    continue  # _submit_once re-checa already_sent p/ não repostar
                raise

    def _perform_send(self, page, prompt: str) -> None:
        """Foca o composer, LIMPA (Ctrl+A/Delete) e digita o prompt, e envia.
        Limpar antes evita texto duplicado caso um envio anterior não tenha
        submetido (o texto fica no composer e um novo type() concatenaria)."""
        box = capture.first_visible(page, self.composer_selectors)
        box.click()
        try:
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
        except Exception:
            pass
        page.keyboard.type(prompt, delay=8)
        if self.submit_selector:
            page.locator(self.submit_selector).first.click()
        else:
            page.keyboard.press("Enter")

    def _submit_once(self, page, prompt: str, user_baseline: int = 0) -> str:
        read = self.content_selector or None
        read_list = [read, self.response_selector] if read else [self.response_selector]
        # Texto do último balão ANTES de enviar (resposta do turno anterior,
        # ou "" num chat novo) — usado pra detectar a resposta NOVA e não
        # capturar a antiga por engano.
        prev_text = capture.last_text(page, read_list)
        baseline = capture.count_responses(page, self.response_selector)
        # Numa re-tentativa, se o nº de balões do usuário subiu acima do
        # baseline (medido em submit() antes do 1º envio), a mensagem já entrou
        # — não reenvia, só espera a resposta. Evita prompt duplicado.
        already_sent = bool(
            self.user_selector
            and capture.count_responses(page, self.user_selector) > user_baseline
        )
        if not already_sent:
            self._perform_send(page, prompt)
            # Confirma que a mensagem POSTOU (balão do usuário novo). O envio
            # pode não registrar quando há bloqueio transitório (toast "Algo deu
            # errado" do Gemini, cumulativo/rate-limit). Reenviar algumas vezes
            # resolve hiccups; se mesmo assim não postar, FALHA RÁPIDO
            # (SendFailed) — muito melhor que esperar o start_timeout estourar:
            # o submit() então espera com backoff e re-tenta.
            if self.user_selector:
                def _registered() -> bool:
                    # A mensagem POSTOU se: (a) subiu a contagem de balões do
                    # usuário, OU (b) a geração começou (botão parar/busy visível
                    # — ex.: ChatGPT "pensando" antes de escrever), OU (c) o texto
                    # da resposta mudou. Vários sinais evitam o falso SendFailed
                    # quando o modelo demora a renderizar o balão do usuário.
                    try:
                        if (capture.count_responses(page, self.user_selector)
                                > user_baseline):
                            return True
                    except Exception:
                        pass
                    for bs in self.busy_selectors:
                        try:
                            if page.locator(bs).count() > 0:
                                return True
                        except Exception:
                            pass
                    try:
                        t = capture.last_text(page, read_list)
                        if t and t != prev_text:
                            return True
                    except Exception:
                        pass
                    return False

                posted = _registered()
                tries = 0
                while not posted and tries < 3:
                    time.sleep(3.0)
                    posted = _registered()
                    if posted:
                        break
                    self._perform_send(page, prompt)  # limpa e reenvia
                    tries += 1
                if not posted:
                    raise capture.SendFailed(
                        "mensagem não postou após reenvios (possível bloqueio "
                        "transitório / rate limit)"
                    )
        capture.wait_response_started(
            page, self.response_selector, baseline, self.busy_selectors,
            read_list, prev_text, timeout=self.start_timeout,
        )
        if self.busy_selectors:
            return capture.wait_until_idle(
                page, self.response_selector, self.busy_selectors,
                read_selector=read, ignore_text=prev_text,
                timeout=self.response_timeout,
                pending_markers=self.pending_markers,
            )
        return capture.wait_stable_text(
            page, self.response_selector, read_selector=read,
            timeout=self.response_timeout,
        )

    def send(self, page, prompt: str) -> str:
        """Conversa de um turno só: abre chat novo e envia um prompt."""
        self.open_new_chat(page)
        return self.submit(page, prompt)

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
    # Texto limpo do markdown da resposta (sem rótulos de botões da toolbar).
    content_selector = "[data-message-author-role='assistant'] .markdown"
    user_selector = "[data-message-author-role='user']"
    # Confirmado por instrumentação: stop-button visível durante a geração;
    # some em ~7s mesmo em respostas longas. Teto menor que o default p/ um
    # turno travado não queimar 4 min (cai no fallback que devolve o parcial).
    busy_selectors = [
        "button[data-testid='stop-button']",
        "button[aria-label*='Stop']",
        "button[aria-label*='Parar']",
    ]
    response_timeout = 150.0


class ChatGPTMomentary(ChatGPT):
    """ChatGPT em **conversa temporária** (não salva no histórico, não usa nem
    atualiza a memória). Ativada pela query `?temporary-chat=true`: cada
    `open_new_chat` navega para essa URL, o que abre uma conversa temporária
    LIMPA. Confirmado ao vivo (jul/2026): aparece o botão aria-label "Turn off
    temporary chat" e o banner "Temporary Chat".

    Se a confirmação falhar, LEVANTA erro (melhor abortar a conversa do que
    rodá-la em modo normal, o que salvaria no histórico e usaria a memória —
    contaminando o experimento)."""

    name = "chatgpt_momentary"
    new_chat_url = "https://chatgpt.com/?temporary-chat=true"
    _confirm_needles = ["temporary chat", "conversa temporária"]

    def _momentary_active(self, page) -> bool:
        try:
            off = page.locator(
                "button[aria-label*='Turn off temporary' i], "
                "button[aria-label*='Desativar conversa temporária' i]"
            )
            if off.count() > 0:
                return True
        except Exception:
            pass
        return _has_leaf_text(page, self._confirm_needles)

    def open_new_chat(self, page) -> None:
        page.goto(self.new_chat_url, wait_until="domcontentloaded",
                  timeout=60000)
        time.sleep(self.settle_s)
        deadline = time.time() + 12
        while time.time() < deadline:
            if self._momentary_active(page):
                return
            time.sleep(0.4)
        raise RuntimeError(
            "ChatGPT: conversa temporária não confirmada (?temporary-chat=true) "
            "— abortando para não salvar no histórico/memória"
        )


class Gemini(BaseDriver):
    name = "gemini"
    new_chat_url = "https://gemini.google.com/app"
    composer_selectors = [
        "div.ql-editor[contenteditable='true']",
        "rich-textarea div[contenteditable='true']",
        "textarea",
    ]
    response_selector = "message-content, .model-response-text"
    # Mensagem do usuário (balão à direita). Usado pra não repostar numa
    # re-tentativa (comparação por CONTAGEM em _submit_once).
    user_selector = ".query-text"
    # Enviar pelo BOTÃO, não por Enter: confirmado por instrumentação (jun/2026)
    # que o Enter cru NÃO submete a partir do 2º turno (composer perde o atalho
    # após a resposta anterior), o que truncava as conversas. O botão tem
    # aria-label "Enviar mensagem" (vira "Parar" durante a geração).
    submit_selector = "button[aria-label='Enviar mensagem']"
    busy_selectors = [
        "button[aria-label*='Stop']",
        "button[aria-label*='Parar']",
        "button.send-button.stop",
    ]
    settle_s = 2.0


class GeminiMomentary(Gemini):
    """Gemini web em **conversa momentânea** (chat anônimo, sem memória entre
    conversas). É o modo usado no experimento de conjoint para que o Gemini
    não acumule contexto de uma conversa para a outra.

    `open_new_chat` navega para /app (chat limpo) e GARANTE que o modo
    momentâneo esteja ativo (idempotente: detecta o banner "conversas
    momentâneas"; se não estiver, clica o botão). Confirmado por inspeção
    (jun/2026): o botão tem aria-label "Conversa momentânea" e, ao ativar,
    aparece um banner com o texto "conversas momentâneas".
    """

    name = "gemini_momentary"
    _toggle_selector = "button[aria-label='Conversa momentânea']"
    # Mensagens longas/indiretas às vezes demoram pra disparar e a resposta do
    # Gemini pode ser longa; folgas maiores que o default evitam o timeout
    # observado no lote preliminar ("resposta não começou em 90s" / "não
    # terminou em 240s").
    # Flash-Lite começa a responder em poucos segundos; se não começou em 45s,
    # é bloqueio transitório — falha rápido e re-tenta (com backoff) em vez de
    # queimar 150s por turno.
    start_timeout = 45.0
    response_timeout = 120.0
    # Mais re-tentativas com backoff: as falhas são bloqueios transitórios
    # ("Algo deu errado", cumulativo) que liberam com a espera. O guard de
    # contagem em _submit_once evita repostar quando a mensagem já entrou.
    submit_retries = 4

    def _momentary_active(self, page) -> bool:
        try:
            return bool(page.evaluate(
                r"""() => {
                  const els = document.querySelectorAll('*');
                  for (const el of els) {
                    if (el.children.length === 0) {
                      const t = (el.textContent || '').trim().toLowerCase();
                      if (t.includes('conversas momentâneas')) return true;
                    }
                  }
                  return false;
                }"""
            ))
        except Exception:
            return False

    def open_new_chat(self, page) -> None:
        """Navega para /app e ATIVA o modo momentâneo, CONFIRMANDO o banner.

        O modo momentâneo NÃO persiste entre navegações (cada goto /app volta
        ao modo normal, que salva no histórico), então é preciso clicar o
        toggle a cada conversa. O botão demora a aparecer no /app recém-carregado
        — esperamos por ele e só então clicamos; depois confirmamos o banner
        "conversas momentâneas". Se não confirmar após várias tentativas,
        LEVANTAMOS erro (melhor abortar a conversa do que vazá-la ao histórico
        e contaminar o experimento com memória entre conversas)."""
        page.goto(self.new_chat_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(self.settle_s)
        last_err = None
        for _ in range(4):
            if self._momentary_active(page):
                return
            try:
                btn = capture.first_visible(page, [self._toggle_selector],
                                            timeout=20)
                btn.click(timeout=5000)
            except Exception as e:  # botão não apareceu / clique falhou
                last_err = e
            # confirma o banner (pode levar 1–2 s pra renderizar)
            deadline = time.time() + 6
            while time.time() < deadline:
                if self._momentary_active(page):
                    return
                time.sleep(0.3)
        raise RuntimeError(
            "não consegui ativar a conversa momentânea após 4 tentativas "
            f"(último erro: {last_err!r}) — abortando para não vazar ao "
            "histórico"
        )


class Claude(BaseDriver):
    name = "claude"
    new_chat_url = "https://claude.ai/new"
    composer_selectors = [
        "div[contenteditable='true'].ProseMirror",
        "div[contenteditable='true']",
    ]
    # DOM atual (jun/2026): cada resposta do assistente vem num wrapper
    # `div[data-is-streaming]` cujo atributo é "true" durante a geração e vira
    # "false" ao terminar — sinal de "ocupado" muito mais confiável que o
    # antigo botão de parar. O texto limpo fica em `div.font-claude-response`.
    response_selector = "div[data-is-streaming]"
    content_selector = "div.font-claude-response"
    user_selector = "[data-testid='user-message']"
    busy_selectors = [
        "div[data-is-streaming='true']",
        "button[aria-label*='Stop']",
        "button[aria-label*='Parar']",
    ]
    # Fase de thinking/pesquisa do Claude: enquanto o texto lido for isto, não é
    # a resposta final (evita truncar em "Searching the web"). / são
    # os ícones de status (Pondering/Searching) do Claude.
    pending_markers = ["Searching the web", "", ""]
    settle_s = 2.0


class ClaudeMomentary(Claude):
    """Claude em **conversa incognito** (não salva no histórico nem usa/atualiza
    a memória). Ativada pelo botão aria-label "Use incognito" (ícone fantasma no
    topo direito); ao ativar, a URL vira `.../new?incognito=`, o botão passa a
    "Exit incognito" e aparecem os textos "You're incognito" / "Incognito chat".
    Confirmado ao vivo (jul/2026). Não persiste entre navegações: reativa a cada
    conversa. Se não confirmar, LEVANTA erro (não roda em modo normal)."""

    name = "claude_momentary"
    _incognito_needles = ["incognito", "incógnito"]

    def _momentary_active(self, page) -> bool:
        # Sinal INEQUÍVOCO: a URL vira .../new?incognito= ao ativar. Checar
        # texto da página dava falso-positivo (o botão/tooltip "Use incognito"
        # contém "incognito" mesmo no modo normal), fazendo o driver PULAR a
        # ativação e rodar em modo normal (salvando no histórico).
        try:
            if "incognito=" in (page.url or "").lower():
                return True
        except Exception:
            pass
        # Reforço: só considera ativo se houver banner explícito de estado.
        return _has_leaf_text(page, ["you're incognito", "incognito chat",
                                     "conversa incógnita", "chat incógnito"])

    def _dismiss_modal(self, page) -> None:
        """Fecha nudges/modais do Claude (ex.: 'claude-code-nudge') cujo backdrop
        sobrepõe o composer e intercepta o clique/digitação."""
        try:
            page.keyboard.press("Escape")
            time.sleep(0.2)
        except Exception:
            pass
        # Fallback: remove o backdrop fixo que intercepta os eventos de ponteiro.
        try:
            page.evaluate(
                r"""() => {
                  const kill = [];
                  document.querySelectorAll('[role=presentation],[data-base-ui-backdrop],[data-open]').forEach(el => {
                    const c = (el.className || '') + '';
                    if (/backdrop|inset-0/.test(c) && getComputedStyle(el).position === 'fixed') kill.push(el);
                  });
                  kill.forEach(el => el.remove());
                }"""
            )
        except Exception:
            pass

    def submit(self, page, prompt: str, max_limit_waits: int | None = None) -> str:
        self._dismiss_modal(page)
        return super().submit(page, prompt, max_limit_waits)

    def open_new_chat(self, page) -> None:
        page.goto(self.new_chat_url, wait_until="domcontentloaded",
                  timeout=60000)
        time.sleep(self.settle_s)
        last_err = None
        for _ in range(4):
            if self._momentary_active(page):
                return
            self._dismiss_modal(page)  # nudge/modal pode interceptar o clique
            try:
                page.get_by_role("button", name="Use incognito").first.click(
                    timeout=5000)
            except Exception as e:
                last_err = e
            deadline = time.time() + 6
            while time.time() < deadline:
                if self._momentary_active(page):
                    return
                time.sleep(0.3)
        raise RuntimeError(
            "Claude: conversa incognito não confirmada (URL sem ?incognito=) "
            f"(último erro: {last_err!r}) — abortando para não salvar no "
            "histórico/memória"
        )


class Grok(BaseDriver):
    name = "grok"
    new_chat_url = "https://grok.com/"
    # Composer é um contenteditable dentro de [data-testid=chat-input] (a
    # <textarea> é oculta, só pra a11y). Enter NÃO submete → usa o botão.
    composer_selectors = [
        "[data-testid='chat-input'] [contenteditable='true']",
        "[data-testid='chat-input']",
        "div[role='textbox']",
    ]
    submit_selector = "[data-testid='chat-submit']"
    response_selector = "[data-testid='assistant-message']"
    # Texto limpo da resposta (exclui o prefixo "Thought for Xs").
    content_selector = "[data-testid='assistant-message'] .response-content-markdown"
    user_selector = "[data-testid='user-message']"
    # Botão de parar durante a geração (candidatos); se não casar, cai no
    # backstop de estabilidade de texto do wait_until_idle.
    busy_selectors = [
        "[data-testid='chat-stop']",
        "button[aria-label*='Stop']",
        "button[aria-label*='Parar']",
    ]
    settle_s = 2.0
    response_timeout = 180.0

    def open_new_chat(self, page) -> None:
        page.goto(self.new_chat_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(self.settle_s)
        self._dismiss_age_gate(page)
        capture.first_visible(page, self.composer_selectors, timeout=30)

    def _dismiss_age_gate(self, page) -> None:
        """Grok pede confirmação de idade (Confirm your age -> Continue ->
        Birth Year -> Save). Fluxo de 2 passos; fecha se aparecer. Detecta por
        texto RENDERIZADO (get_by_text), não pelo body inteiro (evita falso
        positivo com strings ocultas do bundle)."""
        for _ in range(4):
            try:
                gate = (page.get_by_text("Birth Year", exact=False).count() > 0
                        or page.get_by_text("confirm your age", exact=False).count() > 0)
            except Exception:
                gate = False
            if not gate:
                return
            clicked = False
            for sel in ("button:has-text('Continue')", "button:has-text('Save')"):
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        loc.click(timeout=2000)
                        time.sleep(1.3)
                        clicked = True
                        break
                except Exception:
                    pass
            if not clicked:
                return


class GrokMomentary(Grok):
    """Grok em **conversa privada** (não aparece no histórico nem é usada para
    treinar). O toggle é o link `a[aria-label='Switch to Private Chat']` (texto
    "Private"); ao ativar, aparece o badge "Private" (aria-label passa a
    "Switch to Default Chat") e o banner "This chat won't appear in your
    history and will not be used to train models." Confirmado ao vivo
    (jul/2026). O modo NÃO persiste entre carregamentos: reativa a cada
    conversa. Se não confirmar, LEVANTA erro (não roda em modo normal)."""

    name = "grok_momentary"
    _switch_to_private = "a[aria-label='Switch to Private Chat']"
    _private_needles = [
        "won't appear in your history",
        "will not be used to train",
        "não aparecerá no seu histórico",
        "não será usada para treinar",
    ]

    def _momentary_active(self, page) -> bool:
        # Indicador positivo: badge "Switch to Default Chat" OU banner privado.
        try:
            if page.locator("[aria-label='Switch to Default Chat']").count() > 0:
                return True
        except Exception:
            pass
        return _has_leaf_text(page, self._private_needles)

    def open_new_chat(self, page) -> None:
        page.goto(self.new_chat_url, wait_until="domcontentloaded",
                  timeout=60000)
        time.sleep(self.settle_s)
        self._dismiss_age_gate(page)
        capture.first_visible(page, self.composer_selectors, timeout=30)
        last_err = None
        for _ in range(4):
            if self._momentary_active(page):
                return
            try:
                page.locator(self._switch_to_private).first.click(timeout=5000)
            except Exception as e:
                last_err = e
            deadline = time.time() + 6
            while time.time() < deadline:
                if self._momentary_active(page):
                    return
                time.sleep(0.3)
        raise RuntimeError(
            "Grok: conversa privada não confirmada "
            f"(último erro: {last_err!r}) — abortando para não salvar no "
            "histórico"
        )


class DeepSeek(BaseDriver):
    name = "deepseek"
    new_chat_url = "https://chat.deepseek.com/"
    # Composer: uma <textarea> única (Enter envia; Shift+Enter quebra linha).
    # NB: o id "chat-input" saiu do DOM (jun/2026) — usar a textarea direto.
    composer_selectors = [
        "textarea",
        "textarea#chat-input",
    ]
    # Balão do assistente: o corpo em markdown é `.ds-markdown` (confirmado por
    # inspeção jun/2026 — captura o texto limpo da resposta). Conta um por turno.
    response_selector = ".ds-markdown"
    content_selector = ".ds-markdown"
    # DeepSeek não expõe botão de "parar" com seletor estável; cai no backstop
    # de estabilidade de texto (wait_stable_text) com busy vazio.
    busy_selectors: list[str] = []
    settle_s = 2.5
    response_timeout = 180.0


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
    # Balões RECEBIDOS (do Meta AI). DOM ago/2026: as ENVIADAS (usuário) têm
    # `.copyable-text[data-pre-plain-text]` ("[hora] Nome:"); as RECEBIDAS (Meta
    # AI) têm `.copyable-text.selectable-text` SEM data-pre-plain-text. VOLÁTIL:
    # se quebrar, reinspecione (scratchpad wa_dom2.py) qual marca só as recebidas.
    response_selector = ".copyable-text.selectable-text"
    busy_selectors: list[str] = []  # WhatsApp não tem botão de "parar"
    reset_command = "/reset-all-ais"

    def open_new_chat(self, page) -> None:
        """No WhatsApp não há "chat novo": garante o chat ativo (Meta AI aberto
        à mão) e ZERA a memória do Meta AI UMA vez por conversa (`/reset-all-
        ais`). Assim cada conversa começa limpa, mas os turnos de uma conversa
        longa mantêm o contexto entre si."""
        if "web.whatsapp.com" not in page.url:
            page.goto(self.new_chat_url, wait_until="domcontentloaded", timeout=90000)
        capture.first_visible(page, self.composer_selectors, timeout=30)
        self.reset(page)

    def _send_raw(self, page, text: str) -> None:
        box = capture.first_visible(page, self.composer_selectors)
        box.click()
        page.keyboard.type(text, delay=8)
        page.keyboard.press("Enter")

    def reset(self, page) -> None:
        """Zera a memória do Meta AI e espera a confirmação chegar."""
        baseline = capture.count_responses(page, self.response_selector)
        self._send_raw(page, self.reset_command)
        try:
            capture.wait_response_started(
                page, self.response_selector, baseline, [],
                [self.response_selector], "", timeout=30,
            )
        except Exception:
            pass
        time.sleep(2.0)

    def _incoming_texts(self, page) -> list[str]:
        """Lista dos textos dos balões RECEBIDOS (do Meta AI), em ordem. Uma
        linha é ENVIADA (usuário) se tem `.copyable-text[data-pre-plain-text]`
        ("[hora] Nome:"); as recebidas não têm. Robusto a respostas idênticas
        (a contagem sobe mesmo que o texto se repita)."""
        try:
            return page.evaluate(
                r"""() => {
                  const main = document.querySelector('#main');
                  if (!main) return [];
                  const out = [];
                  for (const r of main.querySelectorAll('div[role=row]')) {
                    if (r.querySelector('.copyable-text[data-pre-plain-text]'))
                      continue; // enviada (usuário)
                    const cop = r.querySelector('.copyable-text.selectable-text')
                             || r.querySelector('span.selectable-text');
                    const t = cop ? (cop.innerText || '').trim() : '';
                    if (t) out.push(t);
                  }
                  return out;
                }"""
            ) or []
        except Exception:
            return []

    def _last_incoming(self, page) -> str:
        xs = self._incoming_texts(page)
        return xs[-1] if xs else ""

    def submit(self, page, prompt: str) -> str:
        """Envia um prompt no chat do Meta AI e captura a resposta. Detecta a
        resposta NOVA pela CONTAGEM de balões recebidos (não por mudança de
        texto): o Meta AI repete respostas idênticas (ex.: redirect ao TSE), o
        que quebraria a detecção por texto. Sem reset aqui (é por conversa)."""
        base = len(self._incoming_texts(page))
        self._send_raw(page, prompt)
        # espera um NOVO balão recebido (contagem sobe)
        deadline = time.time() + 90
        while time.time() < deadline:
            if len(self._incoming_texts(page)) > base:
                break
            time.sleep(0.4)
        text = self._wait_stable_incoming(page, base)
        return self._ts_re.sub("", text).strip()

    def _wait_stable_incoming(self, page, base_count: int,
                              stable_for: float = 3.0, poll: float = 0.5) -> str:
        """Espera o texto do NOVO balão recebido (índice > base_count)
        estabilizar. Sem botão de 'parar' no WhatsApp → estabilidade de texto."""
        deadline = time.time() + self.response_timeout
        last = None
        since = None
        while time.time() < deadline:
            xs = self._incoming_texts(page)
            t = xs[-1] if len(xs) > base_count else ""
            if t and t == last:
                if since is None:
                    since = time.time()
                elif time.time() - since >= stable_for:
                    return t
            else:
                since = None
                last = t
            time.sleep(poll)
        return last or ""


# Registro: nome -> classe. A CLI usa essas chaves.
REGISTRY: dict[str, type[BaseDriver]] = {
    d.name: d
    for d in (ChatGPT, ChatGPTMomentary, Gemini, GeminiMomentary, Claude,
              ClaudeMomentary, Grok, GrokMomentary, DeepSeek, MetaAI,
              WhatsAppMetaAI)
}

DEFAULT_TOOLS = ["chatgpt", "gemini", "claude", "metaai"]
