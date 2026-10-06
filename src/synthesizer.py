"""Sintetizador Multi-Motor com Concorrência Assíncrona, Smart Resume e Fallback Transparente.

Responsável por:
1. Síntese assíncrona de falas com controle de concorrência (asyncio.Semaphore).
2. Adaptadores para Edge-TTS, Kokoro-ONNX e Gemini Audio.
3. Fallback Transparente Anti-Cota (chaveia para Edge-TTS se Kokoro ou Gemini falharem).
4. Smart Resume (reaproveitamento de blocos já sintetizados para retomar gravações interrompidas).
"""

import asyncio
import os
from pathlib import Path
from typing import Callable, List, Optional
from dotenv import load_dotenv

import edge_tts
from src.models import ChapterScript, SpeechBlock
from src.voices import get_voice_by_id

load_dotenv()

# Limite seguro de requisições simultâneas para não estourar websockets
MAX_CONCURRENT_REQUESTS = 4


class Synthesizer:
    """Motor de síntese de voz multi-motor com contingência automática."""

    def __init__(
        self,
        models_dir: Path = Path("data") / "models",
        gemini_api_key: Optional[str] = None,
    ):
        self.models_dir = Path(models_dir)
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self._kokoro_instance = None
        self._kokoro_attempted = False

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
            text=text,
            voice=raw_voice,
            rate=rate,
            pitch=pitch,
            volume=volume,
        )
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await communicate.save(str(output_path))

    async def synthesize_with_gemini(
        self,
        text: str,
        voice_name: str,
        acting_prompt: Optional[str],
        output_path: Path,
    ) -> bool:
        """Gera áudio utilizando a API do Gemini com prompt de interpretação."""
        if not self.gemini_api_key or self.gemini_api_key == "sua_chave_api_aqui":
            return False

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_api_key)

            # Prepara a instrução cênica com ênfase em atuação humana e contexto emocional
            if acting_prompt:
                prompt_completo = (
                    f"Você é um ator interpretando uma fala para um audiolivro profissional em português do Brasil.\n"
                    f"Direção cênica, tom de voz e respiração: {acting_prompt}\n"
                    f"Interprete com máxima naturalidade humana a seguinte fala: \"{text}\""
                )
            else:
                prompt_completo = f"Leia com voz expressiva e natural de audiolivro: \"{text}\""

            # Voz padrão caso venha com prefixo
            nome_limpo = voice_name.replace("gemini_", "").capitalize()
            if nome_limpo not in ("Puck", "Charon", "Kore", "Fenrir", "Aoede", "Zephyr", "Leda", "Orus"):
                nome_limpo = "Puck"

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt_completo,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=nome_limpo
                            )
                        )
                    ),
                ),
            )

            # Extrai os bytes de áudio retornados pelo modelo
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    with open(output_path, "wb") as f:
                        f.write(part.inline_data.data)
                    return True

            return False
        except Exception as e:
            print(f"[Synthesizer] Aviso: Gemini TTS indisponível ({e}). Acionando Fallback...")
            return False

    async def synthesize_with_kokoro(
        self,
        text: str,
        voice_style: str,
        blend_recipe: Optional[dict] = None,
        output_path: Path = None,
    ) -> bool:
        """Gera áudio usando Kokoro-ONNX local com suporte a Voice Blending homogêneo."""
        kokoro = self._get_kokoro_model()
        if not kokoro:
            return False

        try:
            import soundfile as sf
            from src.voices import validate_same_gender_blend

            # 1. Trata Voice Blending (fusão de vetores) se especificado
            if blend_recipe and isinstance(blend_recipe, dict):
                # Trava de segurança: Garante que fusões sejam apenas entre vozes do mesmo gênero
                if not validate_same_gender_blend(blend_recipe):
                    print("[Synthesizer] Alerta: Mistura de gêneros opostos bloqueada no Kokoro. Usando voz base.")

                estilos = []
                for v_name, peso in blend_recipe.items():
                    try:
                        s = kokoro.get_voice_style(v_name)
                        estilos.append(s * peso)
                    except Exception as e_style:
                        print(f"[Synthesizer] Erro ao obter estilo {v_name}: {e_style}")
                estilo_final = sum(estilos) if estilos else "pm_alex"
            else:
                # Trata voz direta ou busca estilo
                v_clean = voice_style.replace("kokoro_", "")
                if v_clean in kokoro.get_voices():
                    estilo_final = v_clean
                elif "dora" in v_clean:
                    estilo_final = "pf_dora"
                elif "santa" in v_clean:
                    estilo_final = "pm_santa"
                else:
                    estilo_final = "pm_alex"

            samples, sample_rate = kokoro.create(
                text=text,
                voice=estilo_final,
                speed=1.0,
                lang="pt-br",
            )
            # Salva temporariamente em WAV
            sf.write(str(output_path), samples, sample_rate)
            return True
        except Exception as e:
            print(f"[Synthesizer] Aviso: Kokoro local falhou ({e}). Acionando Fallback...")
            return False

    async def synthesize_block(
        self,
        block: SpeechBlock,
        output_path: Path,
    ):
        """Sintetiza um bloco atômico de fala aplicando concorrência e transparência total de motores."""
        texto_a_sintetizar = block.text_for_tts or block.text

        # Smart Resume: Se o bloco já existe com tamanho válido (> 0 bytes), apenas atualiza auditoria
        if output_path.exists() and output_path.stat().st_size > 500:
            if not block.actual_engine:
                block.actual_engine = block.engine
                block.actual_voice_id = block.voice_id
            return

        async with self.semaphore:
            sucesso = False

            # 1. Tenta sintetizar pelo motor primário
            if block.engine == "gemini":
                sucesso = await self.synthesize_with_gemini(
                    text=texto_a_sintetizar,
                    voice_name=block.voice_id,
                    acting_prompt=block.acting_prompt,
                    output_path=output_path,
                )
                if sucesso:
                    block.actual_engine = "gemini"
                    block.actual_voice_id = block.voice_id
                    block.fallback_triggered = False
                else:
                    block.fallback_triggered = True
                    block.fallback_reason = "Gemini indisponível ou limite de cota"
            elif block.engine == "kokoro":
                sucesso = await self.synthesize_with_kokoro(
                    text=texto_a_sintetizar,
                    voice_style=block.voice_id,
                    blend_recipe=block.blend_recipe,
                    output_path=output_path,
                )
                if sucesso:
                    block.actual_engine = "kokoro"
                    block.actual_voice_id = block.voice_id
                    block.fallback_triggered = False
                else:
                    block.fallback_triggered = True
                    block.fallback_reason = "Kokoro local indisponível"

            # 2. Se o primário for Edge-TTS ou se o motor avançado falhou, executa no Edge-TTS
            if not sucesso:
                voz_cand = block.voice_id if block.engine == "edge" else block.fallback_voice_id
                
                # Resolve com certeza para uma voz válida do Edge-TTS
                prof = get_voice_by_id(voz_cand)
                if prof and prof.engine == "edge":
                    voz_final = prof.engine_voice_id
                elif voz_cand.startswith(("pt-", "en-", "fr-", "de-", "it-", "es-")):
                    voz_final = voz_cand
                else:
                    # Busca fallback no catálogo
                    fb_prof = get_voice_by_id(block.fallback_voice_id)
                    voz_final = fb_prof.engine_voice_id if (fb_prof and fb_prof.engine == "edge") else "pt-BR-AntonioNeural"

                await self.synthesize_with_edge(
                    text=texto_a_sintetizar,
                    voice_id=voz_final,
                    rate=block.rate,
                    pitch=block.pitch,
                    volume=block.volume,
                    output_path=output_path,
                )
                block.actual_engine = "edge"
                block.actual_voice_id = voz_cand
                if block.engine != "edge":
                    block.fallback_triggered = True
                    if not block.fallback_reason:
                        block.fallback_reason = f"Fallback ativado de {block.engine} para edge"

    async def synthesize_chapter(
        self,
        script: ChapterScript,
        project_slug: str,
        temp_dir: Optional[Path] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[Path]:
        """Sintetiza todas as falas do capítulo de forma concorrente e ordenada."""
        base_temp = temp_dir or (Path("data") / "projects" / project_slug / "temp" / f"cap_{script.chapter_number:02d}")
        base_temp.mkdir(parents=True, exist_ok=True)

        tasks = []
        arquivos_esperados: List[Path] = []

        total_blocos = len(script.blocks)

        for i, block in enumerate(script.blocks):
            bloco_path = base_temp / f"block_{i:04d}.mp3"
            arquivos_esperados.append(bloco_path)

            async def _executar_com_progresso(b=block, p=bloco_path, idx=i):
                await self.synthesize_block(b, p)
                if on_progress:
                    on_progress(idx + 1, total_blocos)

            tasks.append(_executar_com_progresso())

        # Executa concorrentemente respeitando o semáforo
        await asyncio.gather(*tasks)

        return arquivos_esperados

    async def generate_voice_sample(
        self,
        voice_id: str,
        sample_text: Optional[str] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Gera uma amostra rápida de voz de ~2 segundos para audição prévia no Streamlit Studio.
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

        from src.voices import find_fallback_voice
        prof = get_voice_by_id(voice_id)
        if not prof:
            prof = get_voice_by_id("edge_antonio")

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
                    voice_id="pt-BR-AntonioNeural",
                    output_path=output_path,
                )
        elif prof.engine == "gemini":
            sucesso = await self.synthesize_with_gemini(
                text=texto,
                voice_name=prof.id,
                acting_prompt="Tom simpático, claro e caloroso de apresentação.",
                output_path=output_path,
            )
            if not sucesso:
                fb = find_fallback_voice(prof)
                await self.synthesize_with_edge(
                    text=texto,
                    voice_id=fb.engine_voice_id,
                    output_path=output_path,
                )
        else:
            await self.synthesize_with_edge(
                text=texto,
                voice_id=prof.engine_voice_id,
                output_path=output_path,
            )

        return output_path
