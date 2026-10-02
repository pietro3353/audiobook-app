"""AudioBook App - Ponto de Entrada Principal."""

import sys
from src.cli import main

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
