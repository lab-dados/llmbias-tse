"""Permite `python -m llmbias_tse ...` (útil quando o console-script .exe
está travado por um processo aberto — ex.: o `launch` segurando o Chrome)."""

from . import main

if __name__ == "__main__":
    main()
