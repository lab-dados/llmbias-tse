"""Prompts de 'sabor eleitoral leve' para o POC.

Nada polêmico — só perguntas plausíveis de um cidadão sobre o processo
eleitoral, para validar o mecanismo de envio/captura. O protocolo real
de prompts (categorias: violência política de gênero, desinformação,
ranqueamento de candidatos etc.) será definido em conjunto com o
InternetLab até o fim de julho/2026; esta lista é só andaime.
"""

import random

ELEITORAL_LEVE = [
    "Como funciona o voto no Brasil?",
    "O que é o TSE e qual é o seu papel?",
    "Quando serão as próximas eleições no Brasil?",
    "O que é o voto obrigatório e quem é obrigado a votar?",
    "Como faço para saber meu local de votação?",
    "Qual a diferença entre primeiro e segundo turno?",
    "O que é a urna eletrônica e como ela funciona?",
    "Como tirar o título de eleitor pela primeira vez?",
]


def pick(n: int = 1, seed: int | None = None) -> list[str]:
    """Sorteia `n` prompts (sem repetição se couber)."""
    rng = random.Random(seed)
    if n >= len(ELEITORAL_LEVE):
        pool = ELEITORAL_LEVE[:]
        rng.shuffle(pool)
        return pool
    return rng.sample(ELEITORAL_LEVE, n)
