"""AudioBook App - Engine Universal de Producao de Audiobooks e Resumos Interpretados."""

import os
import shutil
from pathlib import Path

__version__ = "0.1.0"

# Garante que o FFmpeg esteja sempre visivel para o pydub sem warnings
_winget_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
if _winget_dir.exists():
    for _p in _winget_dir.glob("**/ffmpeg.exe"):
        if _p.is_file():
            _dir = str(_p.parent)
            if _dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{_dir};{os.environ.get('PATH', '')}"
            break
