"""Persistência das trocas — o coração do e2e.

Cada troca (prompt -> resposta) vira um registro estruturado, pronto para
ser consumido por um LLM-juiz na etapa de avaliação de viés. Guardamos:

  - JSONL append-only (`exchanges.jsonl`) — uma linha por troca, com todos
    os metadados (ferramenta, modelo, prompt, resposta, timestamps, status).
  - Artefatos brutos por troca (HTML + screenshot) numa pasta da rodada,
    referenciados no registro — para auditoria e reprodutibilidade.

Tudo fica sob `data/<run_id>/`, fora do versionamento (pode conter dados
de conta pessoal).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DATA_ROOT = Path("data")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    # ex.: 20260604_143015 — ordenável, legível.
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass
class Exchange:
    """Um par prompt->resposta com uma ferramenta, mais metadados."""

    run_id: str
    tool: str                      # "chatgpt", "gemini", ...
    session: str                   # "logged_in" | "anon"
    prompt_id: int                 # índice do prompt na rodada
    prompt: str
    response: str = ""
    model: str | None = None       # se a UI expuser (ex.: "GPT-4o")
    conversation_url: str | None = None
    started_at: str = field(default_factory=_now_iso)
    finished_at: str | None = None
    response_chars: int = 0
    ok: bool = False
    error: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)


class RunStore:
    """Escreve registros e artefatos de uma rodada de coleta."""

    def __init__(self, run_id: str | None = None, root: Path = DATA_ROOT):
        self.run_id = run_id or new_run_id()
        self.dir = root / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.dir / "exchanges.jsonl"

    def artifacts_dir(self, session: str, tool: str, prompt_id: int) -> Path:
        return self.dir / "artifacts" / session / tool / f"{prompt_id:02d}"

    def append(self, ex: Exchange) -> None:
        ex.response_chars = len(ex.response or "")
        if ex.finished_at is None:
            ex.finished_at = _now_iso()
        with self.jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(ex), ensure_ascii=False) + "\n")

    def summary(self) -> str:
        return f"{self.run_id}: registros em {self.jsonl}"
