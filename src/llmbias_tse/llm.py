"""Cliente fino da API do Gemini (google-genai) usado nas duas pontas do
experimento: o **LLM as a user** (agente usuário que conversa com a
plataforma sob teste) e o **LLM as a judge** (que anota as conversas).

A chave vem de `GEMINI_API_KEY` no `.env`. O modelo padrão é
`gemini-3.5-flash` (sobrescrevível via `LLMBIAS_GEMINI_MODEL` ou parâmetro).
"""

from __future__ import annotations

import os
import time
from functools import lru_cache

from dotenv import load_dotenv
from google import genai
from google.genai import types

DEFAULT_MODEL = os.environ.get("LLMBIAS_GEMINI_MODEL", "gemini-3.5-flash")


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY não encontrada (defina no .env). "
            "Necessária para o LLM as a user e o LLM as a judge."
        )
    return genai.Client(api_key=key)


def _with_retry(fn, *, tries: int = 4, base_delay: float = 4.0):
    """Reexecuta `fn` em erros transitórios (429/503/timeout) com backoff."""
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — queremos capturar tudo da API
            last = e
            msg = str(e).lower()
            transient = any(
                t in msg
                for t in ("429", "503", "500", "unavailable", "resource",
                          "deadline", "timeout", "overloaded")
            )
            if attempt == tries - 1 or not transient:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"[llm] erro transitório ({e!r}); retry em {delay:.0f}s "
                  f"({attempt + 1}/{tries - 1})")
            time.sleep(delay)
    raise last  # pragma: no cover


def generate_text(prompt: str, *, system: str | None = None,
                  temperature: float = 1.0, model: str | None = None) -> str:
    """Geração de texto simples (uma chamada)."""
    client = get_client()
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature,
    )
    resp = _with_retry(lambda: client.models.generate_content(
        model=model or DEFAULT_MODEL, contents=prompt, config=cfg,
    ))
    return (resp.text or "").strip()


def generate_structured(prompt: str, schema, *, system: str | None = None,
                        temperature: float = 0.2, model: str | None = None):
    """Geração com saída estruturada (JSON validado por um schema pydantic).

    Retorna a instância pydantic (`resp.parsed`).
    """
    client = get_client()
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
    )
    resp = _with_retry(lambda: client.models.generate_content(
        model=model or DEFAULT_MODEL, contents=prompt, config=cfg,
    ))
    if resp.parsed is None:
        raise RuntimeError(f"Saída estruturada vazia. Texto: {resp.text!r}")
    return resp.parsed


def new_chat(system: str, *, temperature: float = 1.0,
             model: str | None = None):
    """Cria uma sessão de chat multi-turno (usada pelo agente usuário)."""
    client = get_client()
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature,
    )
    return client.chats.create(model=model or DEFAULT_MODEL, config=cfg)


def chat_send(chat, text: str) -> str:
    """Envia uma mensagem numa sessão de chat e devolve o texto da resposta."""
    resp = _with_retry(lambda: chat.send_message(text))
    return (resp.text or "").strip()
