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


def generate_room_tone(duration_ms: int, frame_rate: int = 24000) -> AudioSegment:
    """
    Gera um levíssimo ruído de ambiente de estúdio/cabine (-56 dBFS)
    para preencher as pausas e evitar o efeito de 'vácuo digital absoluto' (noise gating).
    """
    import numpy as np

    num_samples = int(frame_rate * (duration_ms / 1000.0))
    if num_samples <= 0:
        return AudioSegment.empty()

    # Ruído suave contínuo simulando ruído térmico/acústico de estúdio (-56 dBFS)
    amplitude = 42.0
    noise = np.random.normal(0, amplitude, num_samples).astype(np.int16)

    return AudioSegment(
        noise.tobytes(),
        frame_rate=frame_rate,
        sample_width=2,
        channels=1,
    )


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
        is_kokoro: bool = False,
        enable_kokoro_eq: bool = True,
        enable_room_tone: bool = True,
    ) -> Path:
        """
        Padroniza taxa de amostragem (24kHz), mono, equaliza volume de pico (headroom 1.0),
        aplica micro-fades (30ms) nas bordas da fala, equalização de brilho no Kokoro e anexa pausa.
        """
        if not raw_audio_path.exists() or raw_audio_path.stat().st_size == 0:
            raise FileNotFoundError(f"Arquivo de áudio bruto ausente ou vazio: {raw_audio_path}")

        # 1. Carrega o segmento bruto ou com equalização de presença nos agudos (+2.5dB) para Kokoro
        caminho_leitura = str(raw_audio_path)
        temp_eq_path = None
        if is_kokoro and enable_kokoro_eq:
            try:
                temp_eq_path = output_normalized_path.parent / f"_temp_eq_{raw_audio_path.stem}.mp3"
                cmd_eq = [
                    self.ffmpeg_path, "-y", "-i", str(raw_audio_path),
                    "-af", "treble=g=2.5:f=3500:w=0.7",
                    "-c:a", "libmp3lame", "-b:a", "192k",
                    str(temp_eq_path)
                ]
                res_eq = subprocess.run(cmd_eq, capture_output=True, text=True)
                if res_eq.returncode == 0 and temp_eq_path.exists():
                    caminho_leitura = str(temp_eq_path)
            except Exception:
                caminho_leitura = str(raw_audio_path)

        import io
        try:
            segmento = AudioSegment.from_file(caminho_leitura)
        except Exception:
            # Fallback resiliente: decodifica RIFF (WAV) ou PCM bruto (s16le, 24kHz, mono)
            try:
                with open(caminho_leitura, "rb") as f_raw:
                    raw_b = f_raw.read()
                if raw_b.startswith(b"RIFF"):
                    segmento = AudioSegment.from_file(io.BytesIO(raw_b), format="wav")
                else:
                    segmento = AudioSegment(raw_b, sample_width=2, frame_rate=24000, channels=1)
            except Exception as e_inner:
                raise RuntimeError(f"Falha ao decodificar áudio {caminho_leitura}: {e_inner}")

        if temp_eq_path and temp_eq_path.exists():
            try:
                temp_eq_path.unlink()
            except Exception:
                pass

        # 2. Padronização para 24.000 Hz, 1 canal (mono)
        segmento = segmento.set_frame_rate(24000).set_channels(1)

        # 3. Micro-fades (30ms) na entrada e na saída da fala para eliminar estalos e cortes abruptos
        if len(segmento) > 60:
            segmento = segmento.fade_in(30).fade_out(30)

        # 4. Nivelamento de Volume (Loudness / Peak Normalization com 1.0 dB de headroom)
        segmento_normalizado = effects.normalize(segmento, headroom=1.0)

        # 5. Geração do ambiente acústico orgânico nas pausas (ou silêncio limpo se desativado)
        duracao_pausa = max(100, pause_after_ms)
        if enable_room_tone:
            pausa_ambiente = generate_room_tone(duration_ms=duracao_pausa, frame_rate=24000)
        else:
            pausa_ambiente = AudioSegment.silent(duration=duracao_pausa, frame_rate=24000)

        # 6. União da fala com sua pausa
        bloco_final = segmento_normalizado + pausa_ambiente

        # 7. Exportação em MP3 padrão 192k
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
        enable_kokoro_eq: bool = True,
        enable_room_tone: bool = True,
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
            motor_efetivo = getattr(bloco, "actual_engine", None) or bloco.engine
            is_kokoro = (motor_efetivo == "kokoro")
            self.normalize_and_add_pause(
                raw_audio_path=raw_chunk,
                pause_after_ms=bloco.pause_after_ms,
                output_normalized_path=norm_path,
                is_kokoro=is_kokoro,
                enable_kokoro_eq=enable_kokoro_eq,
                enable_room_tone=enable_room_tone,
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
