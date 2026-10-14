"""Sintetizador Multi-Motor com Concorrência Assíncrona, Smart Resume e Fallback Transparente.

Responsável por:
1. Síntese assíncrona de falas com controle de concorrência (asyncio.Semaphore).
2. Adaptadores para Edge-TTS, Kokoro-ONNX e Gemini Audio.
3. Fallback Transparente Anti-Cota (Gemini -> Kokoro local -> Edge-TTS).
4. Smart Resume (reaproveitamento de blocos já sintetizados para retomar gravações interrompidas),
   sem nunca confundir um áudio de contingência com o áudio da voz primária.
5. Higienização do texto (clean_tts_text) para que nenhum motor leia rubricas ou instruções em voz alta.
"""

import asyncio
import io
import os
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from dotenv import load_dotenv

import edge_tts
from src.emotions import get_tts_style_prefix
from src.models import ChapterScript, SpeechBlock
from src.voices import (
    VOICE_CATALOG,
    VoiceProfile,
    find_edge_voice,
    find_fallback_voice,
    get_voice_by_id,
)

load_dotenv()

# Limite seguro de requisições simultâneas para não estourar websockets
MAX_CONCURRENT_REQUESTS = 4

# Modelo TTS padrão do Gemini (existente na Gemini Developer API)
DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"

GEMINI_PREBUILT_VOICES = ("Puck", "Charon", "Kore", "Fenrir", "Aoede", "Zephyr", "Leda", "Orus")


# ==============================================================================
# HIGIENIZAÇÃO DE TEXTO PARA TTS
# ==============================================================================

# Palavras que denunciam uma rubrica/instrução cênica dentro de parênteses
_RUBRICA_KEYWORDS = (
    "tom", "pausa", "voz", "sussurr", "risos", "ri ", "rindo", "suspir", "respir",
    "emoç", "emoc", "didátic", "didatic", "enfátic", "enfatic", "lento", "lenta",
    "rápido", "rapido", "tenso", "irônic", "ironic", "grit", "chor", "baixinho",
    "animad", "solene", "misterios", "narrador", "fala ", "interpret", "entonação",
    "entonacao", "ênfase", "enfase", "calm", "sério", "serio", "pause", "whisper",
    "say ", "tone",
)

_LINHA_INSTRUCAO = re.compile(
    r"^\s*(dire[cç][aã]o c[eê]nica|instru[cç][aã]o|acting|tom de voz|interprete|"
    r"voc[eê] [eé] um ator|mantenha a personalidade)\b.*$",
    flags=re.IGNORECASE | re.MULTILINE,
)


def _is_rubrica(conteudo: str) -> bool:
    c = conteudo.strip().lower()
    if not c:
        return True
    return any(k in f"{c} " for k in _RUBRICA_KEYWORDS)


def clean_tts_text(text: str) -> str:
    """
    Remove rubricas e instruções acidentais antes de enviar o texto a qualquer motor TTS.
    - Remove qualquer conteúdo entre colchetes: [pausa], [tom didático]...
    - Remove parênteses que contenham rubricas: (tom didático), (sussurrando)...
      (parênteses de conteúdo real, como siglas "(SGBD)", são preservados)
    - Remove linhas de instrução ("Direção cênica: ...", "Você é um ator...").
    - Normaliza reticências duplicadas ("... ..." -> "...", "…" -> "...").
    """
    if not text:
        return ""

    t = text
    t = _LINHA_INSTRUCAO.sub("", t)
    t = re.sub(r"\[[^\[\]]*\]", " ", t)
    t = re.sub(r"\(([^()]{0,80})\)", lambda m: " " if _is_rubrica(m.group(1)) else m.group(0), t)

    # Normalização de reticências
    t = t.replace("…", "...")
    t = re.sub(r"\.{4,}", "...", t)
    t = re.sub(r"\.\.\.(\s*\.\.\.)+", "...", t)

    # Espaços e pontuação órfã
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([,;:!?])", r"\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def parse_rate_to_speed(rate: Optional[str]) -> float:
    """Converte '+5%' -> 1.05, '-4%' -> 0.96 (com trava de segurança 0.5 a 2.0)."""
    if not rate:
        return 1.0
    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*%?\s*$", str(rate))
    if not m:
        return 1.0
    speed = 1.0 + float(m.group(1)) / 100.0
    return max(0.5, min(2.0, speed))


def _resolve_profile(voice_id: Optional[str]) -> Optional[VoiceProfile]:
    """Resolve um ID de catálogo ou um código bruto legado (ex: 'pt-BR-AntonioNeural', 'Zephyr')."""
    if not voice_id:
        return None
    prof = get_voice_by_id(voice_id)
    if prof:
        return prof
    for v in VOICE_CATALOG.values():
        if v.engine_voice_id == voice_id or v.engine_voice_id.lower() == voice_id.lower():
            return v
    return None


def _safe_file_token(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", s or "voz")


class GeminiQuotaExceeded(Exception):
    """Sinaliza cota diária do Gemini esgotada (429 RESOURCE_EXHAUSTED)."""


class Synthesizer:
    """Motor de síntese de voz multi-motor com contingência automática."""

    def __init__(
        self,
        models_dir: Path = Path("data") / "models",
        gemini_api_key: Optional[str] = None,
    ):
        self.models_dir = Path(models_dir)
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.gemini_semaphore = asyncio.Semaphore(1)  # Gemini sequencial para evitar 503 Spikes e limite por minuto
        self.kokoro_semaphore = asyncio.Semaphore(1)  # Inferência ONNX local serializada
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self._kokoro_instance = None
        self._kokoro_attempted = False
        # Se a cota diária do Gemini estourar, os blocos seguintes pulam direto para o fallback
        self._gemini_quota_exhausted = False

    def _get_kokoro_model(self):
        """Tenta instanciar o modelo Kokoro local se os pesos existirem."""
        if self._kokoro_attempted:
            return self._kokoro_instance

        self._kokoro_attempted = True
        onnx_candidates = [
            self.models_dir / "kokoro-v1.0.onnx",
            self.models_dir / "kokoro-v0_19.onnx",
        ]
        voices_candidates = [
            self.models_dir / "voices-v1.0.bin",
            self.models_dir / "voices.json",
        ]
        onnx_path = next((p for p in onnx_candidates if p.exists()), None)
        voices_path = next((p for p in voices_candidates if p.exists()), None)

        if onnx_path and voices_path:
            try:
                import kokoro_onnx

                self._kokoro_instance = kokoro_onnx.Kokoro(
                    str(onnx_path), str(voices_path)
                )
            except Exception as e:
                print(f"[Synthesizer] Aviso: Falha ao carregar modelo Kokoro: {e}")
                self._kokoro_instance = None
        else:
            print("[Synthesizer] Aviso: Pesos do Kokoro não encontrados em data/models/")

        return self._kokoro_instance

    # ==========================================================================
    # ADAPTADORES DE MOTOR
    # ==========================================================================

    async def synthesize_with_edge(
        self,
        text: str,
        voice_id: str,
        rate: str = "+0%",
        pitch: str = "+0Hz",
        volume: str = "+0%",
        output_path: Optional[Path] = None,
    ):
        """Gera áudio usando a API gratuita do Edge-TTS."""
        # Se voice_id for um ID do catálogo (ex: 'edge_antonio'), resolve para o código do motor
        voice_profile = get_voice_by_id(voice_id)
        raw_voice = voice_profile.engine_voice_id if voice_profile else voice_id

        communicate = edge_tts.Communicate(
            text=clean_tts_text(text),
            voice=raw_voice,
            rate=rate,
            pitch=pitch,
            volume=volume,
        )
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await communicate.save(str(output_path))

    @staticmethod
    def _is_quota_error(err: str) -> bool:
        e = err.lower()
        return "resource_exhausted" in e or "quota" in e or ("429" in e and "rate" not in e)

    @staticmethod
    def _is_not_found_error(err: str) -> bool:
        e = err.lower()
        return "404" in e or "not_found" in e or "not found" in e

    async def synthesize_with_gemini(
        self,
        text: str,
        voice_name: str,
        acting_prompt: Optional[str] = None,
        output_path: Optional[Path] = None,
        emotion: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Gera áudio com o Gemini TTS.

        IMPORTANTE: o campo `contents` recebe SOMENTE o texto limpo. Para emoções dramáticas,
        recebe no máximo um prefixo curto de estilo ("Say sadly: <texto>"). Instruções longas
        (como `acting_prompt`) nunca são enviadas, pois o modelo as lê em voz alta e o timbre oscila.
        O parâmetro `acting_prompt` é mantido apenas por compatibilidade de assinatura.
        """
        if not self.gemini_api_key or self.gemini_api_key == "sua_chave_api_aqui":
            return False, "Chave da API do Gemini não configurada."

        if self._gemini_quota_exhausted:
            return False, "Cota diária da API do Gemini excedida (Free Tier)."

        texto_limpo = clean_tts_text(text)
        if not texto_limpo:
            return False, "Texto vazio após higienização."

        prefixo = get_tts_style_prefix(emotion)
        conteudo = f"{prefixo}: {texto_limpo}" if prefixo else texto_limpo

        # Resolve o nome da voz pré-construída do Gemini
        prof = _resolve_profile(voice_name)
        if prof and prof.engine == "gemini":
            nome_voz = prof.engine_voice_id
        else:
            nome_voz = (voice_name or "").replace("gemini_", "").capitalize()
        if nome_voz not in GEMINI_PREBUILT_VOICES:
            nome_voz = "Puck"

        modelo_cfg = os.getenv("GEMINI_TTS_MODEL", DEFAULT_GEMINI_TTS_MODEL).strip() or DEFAULT_GEMINI_TTS_MODEL
        modelos = [modelo_cfg] + ([DEFAULT_GEMINI_TTS_MODEL] if modelo_cfg != DEFAULT_GEMINI_TTS_MODEL else [])

        async with self.gemini_semaphore:
            if self._gemini_quota_exhausted:
                return False, "Cota diária da API do Gemini excedida (Free Tier)."

            # Pausa suave de 1s para respeitar limites de taxa por minuto da Google Developer API
            await asyncio.sleep(1.0)
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.gemini_api_key)
                config = types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=nome_voz)
                        )
                    ),
                )

                response = None
                ultimo_erro = ""
                for modelo in modelos:
                    try:
                        response = await asyncio.to_thread(
                            client.models.generate_content,
                            model=modelo,
                            contents=conteudo,
                            config=config,
                        )
                        break
                    except Exception as e_tts:
                        ultimo_erro = str(e_tts)
                        if self._is_quota_error(ultimo_erro):
                            self._gemini_quota_exhausted = True
                            print("[Synthesizer] Cota diária do Gemini esgotada. Próximos blocos irão direto ao fallback.")
                            return False, "Cota diária da API do Gemini excedida (Free Tier)."
                        print(f"[Synthesizer] Modelo {modelo} falhou ({ultimo_erro[:160]}).")
                        continue

                if response is None:
                    return False, f"Gemini indisponível: {ultimo_erro}"

                # Extrai os bytes de áudio e converte para MP3 real
                if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data and part.inline_data.data:
                            raw_data = part.inline_data.data
                            from pydub import AudioSegment

                            # Gemini pode retornar WAV (RIFF) ou PCM bruto (s16le, 24kHz, mono)
                            if raw_data.startswith(b"RIFF"):
                                seg = AudioSegment.from_file(io.BytesIO(raw_data), format="wav")
                            elif raw_data.startswith(b"ID3") or raw_data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
                                seg = AudioSegment.from_file(io.BytesIO(raw_data), format="mp3")
                            else:
                                seg = AudioSegment(raw_data, sample_width=2, frame_rate=24000, channels=1)

                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            seg.export(str(output_path), format="mp3", bitrate="192k")
                            return True, None

                return False, "Nenhum dado de áudio retornado pelo Gemini."
            except Exception as e:
                err_main = str(e)
                print(f"[Synthesizer] Aviso: Gemini TTS indisponível ({err_main[:160]}). Acionando Fallback...")
                if self._is_quota_error(err_main):
                    self._gemini_quota_exhausted = True
                    return False, "Cota diária da API do Gemini excedida (Free Tier)."
                return False, f"Erro Gemini: {err_main}"

    def _resolve_kokoro_style(self, kokoro, voice_style: str, blend_recipe: Optional[dict]):
        """Resolve o estilo Kokoro (voz direta, preset do catálogo ou fusão de vetores)."""
        from src.voices import validate_same_gender_blend

        prof = _resolve_profile(voice_style)
        if not blend_recipe and prof and prof.engine == "kokoro" and prof.blend_recipe:
            blend_recipe = prof.blend_recipe

        if blend_recipe and isinstance(blend_recipe, dict):
            # Trava de segurança: Garante que fusões sejam apenas entre vozes do mesmo gênero
            if not validate_same_gender_blend(blend_recipe):
                print("[Synthesizer] Alerta: Mistura de gêneros opostos bloqueada no Kokoro. Usando voz base.")
            else:
                estilos = []
                for v_name, peso in blend_recipe.items():
                    try:
                        estilos.append(kokoro.get_voice_style(v_name) * peso)
                    except Exception as e_style:
                        print(f"[Synthesizer] Erro ao obter estilo {v_name}: {e_style}")
                if estilos:
                    return sum(estilos)

        disponiveis = set(kokoro.get_voices())
        if prof and prof.engine == "kokoro" and prof.engine_voice_id in disponiveis:
            return prof.engine_voice_id
        v_clean = (voice_style or "").replace("kokoro_", "")
        if v_clean in disponiveis:
            return v_clean
        if "dora" in v_clean:
            return "pf_dora"
        if "santa" in v_clean:
            return "pm_santa"
        if prof and prof.gender == "F":
            return "pf_dora"
        return "pm_alex"

    async def synthesize_with_kokoro(
        self,
        text: str,
        voice_style: str,
        blend_recipe: Optional[dict] = None,
        output_path: Path = None,
        rate: Optional[str] = None,
    ) -> bool:
        """Gera áudio usando Kokoro-ONNX local (velocidade do bloco + exportação MP3 real)."""
        kokoro = self._get_kokoro_model()
        if not kokoro:
            return False

        try:
            import numpy as np
            from pydub import AudioSegment

            texto_limpo = clean_tts_text(text)
            if not texto_limpo:
                return False

            estilo_final = self._resolve_kokoro_style(kokoro, voice_style, blend_recipe)
            speed = parse_rate_to_speed(rate)

            async with self.kokoro_semaphore:
                samples, sample_rate = await asyncio.to_thread(
                    kokoro.create,
                    texto_limpo,
                    voice=estilo_final,
                    speed=speed,
                    lang="pt-br",
                )

            pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype(np.int16)
            seg = AudioSegment(pcm.tobytes(), frame_rate=int(sample_rate), sample_width=2, channels=1)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            seg.export(str(output_path), format="mp3", bitrate="192k")
            return True
        except Exception as e:
            print(f"[Synthesizer] Aviso: Kokoro local falhou ({e}). Acionando Fallback...")
            return False

    # ==========================================================================
    # ORQUESTRAÇÃO POR BLOCO (SMART RESUME + FALLBACK)
    # ==========================================================================

    @staticmethod
    def primary_block_path(base_temp: Path, index: int, block: SpeechBlock) -> Path:
        """Arquivo da voz primária. Jamais recebe áudio de contingência."""
        return base_temp / f"block_{index:04d}_{_safe_file_token(block.voice_id)}.mp3"

    @staticmethod
    def fallback_block_path(base_temp: Path, index: int, block: SpeechBlock, actual_voice_id: str) -> Path:
        """Arquivo de contingência, sempre com sufixo explícito _fallback_<voz real>."""
        return base_temp / (
            f"block_{index:04d}_{_safe_file_token(block.voice_id)}_fallback_{_safe_file_token(actual_voice_id)}.mp3"
        )

    def _fallback_chain(self, block: SpeechBlock) -> List[Tuple[str, str]]:
        """Monta a cadeia de contingência [(engine, catalog_voice_id)] após o motor primário."""
        cadeia: List[Tuple[str, str]] = []
        prim_prof = _resolve_profile(block.voice_id)
        fb_prof = _resolve_profile(block.fallback_voice_id)

        # Contingência registrada no bloco (Kokoro é preferido quando disponível)
        if fb_prof and fb_prof.engine != block.engine:
            cadeia.append((fb_prof.engine, fb_prof.id))
        elif prim_prof and block.engine == "gemini":
            calc = find_fallback_voice(prim_prof)
            cadeia.append((calc.engine, calc.id))

        # Último recurso garantido: Edge-TTS
        if not any(e == "edge" for e, _ in cadeia):
            base = fb_prof or prim_prof
            edge_prof = find_edge_voice(base) if base else VOICE_CATALOG["edge_antonio"]
            cadeia.append(("edge", edge_prof.id))
        return cadeia

    async def _run_engine(
        self,
        engine: str,
        voice_id: str,
        block: SpeechBlock,
        text: str,
        output_path: Path,
    ) -> Tuple[bool, Optional[str]]:
        if engine == "gemini":
            return await self.synthesize_with_gemini(
                text=text,
                voice_name=voice_id,
                acting_prompt=block.acting_prompt,
                output_path=output_path,
                emotion=block.emotion,
            )
        if engine == "kokoro":
            prim = voice_id == block.voice_id
            ok = await self.synthesize_with_kokoro(
                text=text,
                voice_style=voice_id,
                blend_recipe=block.blend_recipe if prim else None,
                output_path=output_path,
                rate=block.rate,
            )
            return ok, (None if ok else "Kokoro local indisponível")
        # Edge-TTS
        prof = _resolve_profile(voice_id)
        raw = prof.engine_voice_id if (prof and prof.engine == "edge") else (
            voice_id if voice_id.startswith(("pt-", "en-", "fr-", "de-", "it-", "es-")) else "pt-BR-AntonioNeural"
        )
        try:
            await self.synthesize_with_edge(
                text=text,
                voice_id=raw,
                rate=block.rate,
                pitch=block.pitch,
                volume=block.volume,
                output_path=output_path,
            )
            return output_path.exists() and output_path.stat().st_size > 0, None
        except Exception as e:
            return False, f"Edge-TTS falhou: {e}"

    async def synthesize_block(
        self,
        block: SpeechBlock,
        output_path: Path,
    ) -> Path:
        """
        Sintetiza um bloco com transparência total de motores.
        `output_path` é o arquivo da VOZ PRIMÁRIA. Se houver contingência, o áudio é salvo em um
        arquivo `_fallback_<voz>.mp3` separado, e esse caminho real é retornado.
        """
        texto_a_sintetizar = clean_tts_text(block.text_for_tts or block.text)
        base_temp = output_path.parent
        idx_match = re.match(r"block_(\d+)_", output_path.name)
        idx = int(idx_match.group(1)) if idx_match else block.index

        # Smart Resume 1: o arquivo primário só existe se a voz primária realmente o gerou
        if output_path.exists() and output_path.stat().st_size > 500:
            block.actual_engine = block.engine
            block.actual_voice_id = block.voice_id
            block.fallback_triggered = False
            block.fallback_reason = None
            return output_path

        async with self.semaphore:
            # 1. Motor primário
            sucesso, motivo = await self._run_engine(
                block.engine, block.voice_id, block, texto_a_sintetizar, output_path
            )
            if sucesso:
                block.actual_engine = block.engine
                block.actual_voice_id = block.voice_id
                block.fallback_triggered = False
                block.fallback_reason = None
                # Remove contingências antigas deste bloco
                for velho in base_temp.glob(f"{output_path.stem}_fallback_*.mp3"):
                    try:
                        velho.unlink()
                    except Exception:
                        pass
                return output_path

            # Arquivo primário incompleto nunca deve ficar no disco
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass

            motivo_primario = motivo or f"{block.engine} indisponível"

            # 2. Cadeia de contingência (Kokoro local -> Edge-TTS)
            for engine_fb, voz_fb in self._fallback_chain(block):
                fb_path = self.fallback_block_path(base_temp, idx, block, voz_fb)

                # Smart Resume 2: a voz primária já foi re-tentada e falhou; reaproveita a contingência existente
                if fb_path.exists() and fb_path.stat().st_size > 500:
                    ok = True
                else:
                    ok, _ = await self._run_engine(engine_fb, voz_fb, block, texto_a_sintetizar, fb_path)

                if ok:
                    block.actual_engine = engine_fb
                    block.actual_voice_id = voz_fb
                    block.fallback_triggered = True
                    block.fallback_reason = motivo_primario
                    return fb_path

            raise RuntimeError(f"Nenhum motor conseguiu sintetizar o bloco {idx}: {motivo_primario}")

    async def synthesize_chapter(
        self,
        script: ChapterScript,
        project_slug: str,
        temp_dir: Optional[Path] = None,
        on_progress: Optional[Callable] = None,
    ) -> List[Path]:
        """Sintetiza todas as falas do capítulo de forma concorrente e retorna os arquivos reais, em ordem."""
        base_temp = temp_dir or (Path("data") / "projects" / project_slug / "temp" / f"cap_{script.chapter_number:02d}")
        base_temp.mkdir(parents=True, exist_ok=True)

        total_blocos = len(script.blocks)
        arquivos_reais: List[Optional[Path]] = [None] * total_blocos
        concluidos = 0

        async def _executar(idx: int, b: SpeechBlock):
            nonlocal concluidos
            p = self.primary_block_path(base_temp, idx, b)
            arquivos_reais[idx] = await self.synthesize_block(b, p)
            concluidos += 1
            if on_progress:
                try:
                    on_progress(concluidos, total_blocos, b.text)
                except TypeError:
                    on_progress(concluidos, total_blocos)

        await asyncio.gather(*[_executar(i, b) for i, b in enumerate(script.blocks)])
        return [p for p in arquivos_reais if p is not None]

    async def generate_voice_sample(
        self,
        voice_id: str,
        sample_text: Optional[str] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Gera uma amostra rápida de voz de ~2 segundos para audição prévia no Studio.
        """
        texto = sample_text or "Olá! Esta é uma demonstração da minha voz para o seu audiolivro."
        if not output_path:
            samples_dir = Path("data") / "temp" / "samples"
            samples_dir.mkdir(parents=True, exist_ok=True)
            output_path = samples_dir / f"sample_{voice_id}.mp3"
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.exists() and output_path.stat().st_size > 1000:
            return output_path

        prof = get_voice_by_id(voice_id) or get_voice_by_id("edge_antonio")

        if prof.engine == "kokoro":
            sucesso = await self.synthesize_with_kokoro(
                text=texto,
                voice_style=prof.id,
                blend_recipe=prof.blend_recipe,
                output_path=output_path,
            )
            if not sucesso:
                await self.synthesize_with_edge(
                    text=texto,
                    voice_id=find_edge_voice(prof).engine_voice_id,
                    output_path=output_path,
                )
        elif prof.engine == "gemini":
            sucesso, _ = await self.synthesize_with_gemini(
                text=texto,
                voice_name=prof.id,
                output_path=output_path,
            )
            if not sucesso:
                fb = find_fallback_voice(prof)
                ok_fb = False
                if fb.engine == "kokoro":
                    ok_fb = await self.synthesize_with_kokoro(
                        text=texto, voice_style=fb.id, blend_recipe=fb.blend_recipe, output_path=output_path
                    )
                if not ok_fb:
                    await self.synthesize_with_edge(
                        text=texto,
                        voice_id=find_edge_voice(prof).engine_voice_id,
                        output_path=output_path,
                    )
        else:
            await self.synthesize_with_edge(
                text=texto,
                voice_id=prof.engine_voice_id,
                output_path=output_path,
            )

        return output_path
