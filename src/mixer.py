"""Mixador de Áudio de Estúdio, Nivelamento Acústico e Montagem FFmpeg.

Responsável por:
1. Padronização Acústica: Unifica taxa de amostragem (24kHz), canais (mono) e ganho de volume (Loudness Normalization).
2. Inserção precisa das Pausas Dramáticas de respiração (pause_after_ms).
3. Concatenação de Alta Performance via FFmpeg Demuxer (zero sobrecarga de memória RAM).
4. Exportação do áudio final por capítulo e do audiolivro completo unificado.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from pydub import AudioSegment, effects
from src.models import ChapterScript

# Procura o executável do FFmpeg de forma resiliente no Windows
def get_ffmpeg_path() -> str:
    """Retorna o caminho seguro do executável do FFmpeg."""
    # 1. Verifica no PATH padrão
    ff_cmd = shutil.which("ffmpeg")
    if ff_cmd:
        return ff_cmd

    # 2. Verifica caminhos comuns do WinGet no Windows
    winget_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_dir.exists():
        for p in winget_dir.glob("**/ffmpeg.exe"):
            if p.is_file():
                return str(p)

    return "ffmpeg"


FFMPEG_EXE = get_ffmpeg_path()
ffmpeg_parent = str(Path(FFMPEG_EXE).parent)
if ffmpeg_parent not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{ffmpeg_parent};{os.environ.get('PATH', '')}"
AudioSegment.converter = FFMPEG_EXE


class AudioMixer:
    """Controlador de masterização e concatenação de áudio."""

    def __init__(self, ffmpeg_path: str = FFMPEG_EXE):
        self.ffmpeg_path = ffmpeg_path
        # Assegura que o pydub conheça o FFmpeg
        AudioSegment.converter = self.ffmpeg_path

    def normalize_and_add_pause(
        self,
        raw_audio_path: Path,
        pause_after_ms: int,
        output_normalized_path: Path,
    ) -> Path:
        """
        Padroniza taxa de amostragem (24kHz), mono, equaliza volume de pico (headroom 1.0)
        e anexa os milissegundos exatos de silêncio de respiração cênica.
        """
        if not raw_audio_path.exists() or raw_audio_path.stat().st_size == 0:
            raise FileNotFoundError(f"Arquivo de áudio bruto ausente ou vazio: {raw_audio_path}")

        # 1. Carrega o segmento
        segmento = AudioSegment.from_file(str(raw_audio_path))

        # 2. Padronização para 24.000 Hz, 1 canal (mono)
        segmento = segmento.set_frame_rate(24000).set_channels(1)

        # 3. Nivelamento de Volume (Loudness / Peak Normalization com 1.0 dB de headroom)
        segmento_normalizado = effects.normalize(segmento, headroom=1.0)

        # 4. Geração do silêncio preciso de respiração
        silencio_dramatico = AudioSegment.silent(duration=max(100, pause_after_ms), frame_rate=24000)

        # 5. União da fala com sua pausa
        bloco_final = segmento_normalizado + silencio_dramatico

        # 6. Exportação em MP3 padrão 192k
        output_normalized_path.parent.mkdir(parents=True, exist_ok=True)
        bloco_final.export(str(output_normalized_path), format="mp3", bitrate="192k")

        return output_normalized_path

    def concat_audio_files(
        self,
        audio_files: List[Path],
        output_path: Path,
    ) -> Path:
        """
        Une múltiplos arquivos de áudio via FFmpeg Concat Demuxer.
        Extremamente rápido e não consome memória RAM mesmo para livros inteiros.
        """
        if not audio_files:
            raise ValueError("Nenhum arquivo de áudio fornecido para concatenação.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path = output_path.parent / f"_concat_{output_path.stem}.txt"

        # 1. Cria o manifesto do demuxer FFmpeg
        with open(manifest_path, "w", encoding="utf-8") as f:
            for arq in audio_files:
                caminho_safe = str(arq.resolve()).replace("\\", "/")
                f.write(f"file '{caminho_safe}'\n")

        # 2. Executa FFmpeg com modo cópia rápida ou recodificação
        comando_copy = [
            self.ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(manifest_path),
            "-c", "copy",
            str(output_path),
        ]

        resultado = subprocess.run(comando_copy, capture_output=True, text=True)

        if resultado.returncode != 0:
            # Fallback seguro: recodifica em MP3 192k se copy falhar
            comando_encode = [
                self.ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(manifest_path),
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                str(output_path),
            ]
            resultado_encode = subprocess.run(comando_encode, capture_output=True, text=True)
            if resultado_encode.returncode != 0:
                # Fallback em Python Puro (Pydub) se FFmpeg acusar erro crítico
                print(f"[AudioMixer] Aviso FFmpeg: {resultado_encode.stderr[:100]}. Unindo via Pydub...")
                audio_unificado = AudioSegment.empty()
                for arq in audio_files:
                    audio_unificado += AudioSegment.from_file(str(arq))
                audio_unificado.export(str(output_path), format="mp3", bitrate="192k")

        # Limpa o arquivo de manifesto temporário
        if manifest_path.exists():
            manifest_path.unlink()

        return output_path

    def mix_chapter(
        self,
        script: ChapterScript,
        raw_chunks: List[Path],
        output_chapter_mp3: Path,
        temp_dir: Optional[Path] = None,
    ) -> Path:
        """
        Masteriza todas as falas de um capítulo com suas pausas e gera o MP3 final do capítulo.
        """
        if len(raw_chunks) != len(script.blocks):
            raise ValueError(
                f"Quantidade divergente de blocos ({len(script.blocks)}) e áudios brutos ({len(raw_chunks)})."
            )

        base_temp = temp_dir or (output_chapter_mp3.parent / "temp_norm" / f"cap_{script.chapter_number:02d}")
        base_temp.mkdir(parents=True, exist_ok=True)

        blocos_normalizados: List[Path] = []

        for i, (bloco, raw_chunk) in enumerate(zip(script.blocks, raw_chunks)):
            norm_path = base_temp / f"norm_{i:04d}.mp3"
            self.normalize_and_add_pause(
                raw_audio_path=raw_chunk,
                pause_after_ms=bloco.pause_after_ms,
                output_normalized_path=norm_path,
            )
            blocos_normalizados.append(norm_path)

        # Montagem final do capítulo
        self.concat_audio_files(blocos_normalizados, output_chapter_mp3)

        return output_chapter_mp3

    def merge_all_chapters(
        self,
        chapter_mp3_files: List[Path],
        output_full_mp3: Path,
    ) -> Path:
        """Une os MP3s de todos os capítulos no audiolivro completo final."""
        return self.concat_audio_files(chapter_mp3_files, output_full_mp3)
