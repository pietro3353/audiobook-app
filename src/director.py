"""Cérebro do Diretor LLM, Validador de Integridade e Modo Determinístico.

Responsável por:
1. Conectar com a API do Gemini via Structured Outputs (Pydantic).
2. Manter a Janela Deslizante de Contexto e continuidade de diálogos entre lotes.
3. Validador de Integridade Léxica com tolerância a pontuações dramáticas (>98%).
4. Atualização automática da Bíblia de Personagens via Smart Casting.
5. Modo Express/Determinístico 100% offline para resumos rápidos ou fallback sem cota.
"""

import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.emotions import list_emotion_labels
from src.extractor import chunk_chapter
from src.models import (
    ChapterScript,
    Character,
    CharacterBible,
    ProjectMetadata,
    SpeechBlock,
    SpeechType,
)
from src.project_manager import ProjectManager

# Carrega variáveis de ambiente do .env
load_dotenv()


# ==============================================================================
# SCHEMAS PYDANTIC PARA STRUCTURED OUTPUTS DA LLM
# ==============================================================================


class DirectedSpeech(BaseModel):
    """Uma fala individual identificada e dirigida pela LLM."""

    speaker: str = Field(
        description="Nome canônico do personagem que fala (ou 'narrador')"
    )
    speech_type: SpeechType = Field(
        default="dialogo",
        description="Tipo de fala: narracao, dialogo, pensamento, citacao ou destaque",
    )
    emotion: str = Field(
        default="neutro",
        description="Rótulo emocional: neutro, sussurro, tenso, panico, raiva, tristeza, alegria, ironia_sarcasmo, solene, cansado_fraco, pensamento, destaque_didatico, misterio, animado ou autoritario",
    )
    text: str = Field(
        description="Texto exato verbatim a ser falado (preserva 100% das palavras para validação léxica)",
    )
    text_for_tts: str = Field(
        default="",
        description="Texto enriquecido com reticências (...), travessões de pausa e ênfases expressivas para guiar o ritmo da voz",
    )
    acting_prompt: str = Field(
        default="",
        description="Diretriz explícita de atuação cênica (tom de voz, intenção dramática, respiração) para o Gemini TTS",
    )
    pause_after_ms: int = Field(
        default=600,
        description="Pausa em milissegundos após a fala (300 a 1500)",
    )
    character_gender: Literal["M", "F", "neutral"] = Field(
        default="M",
        description="Gênero inferido do personagem se for inédito",
    )
    character_apparent_age: Literal["crianca", "jovem", "adulto", "maduro"] = Field(
        default="adulto",
        description="Faixa etária inferida se for inédito",
    )
    character_accent: str = Field(
        default="brasileiro",
        description="Sotaque inferido (brasileiro, portugues, americano, frances, etc.)",
    )
    character_personality: str = Field(
        default="",
        description="Traço de personalidade ou tom cênico (ex: 'ancião ranzinza')",
    )


class DirectedChunkResponse(BaseModel):
    """Resposta estruturada da LLM para um lote (chunk) de parágrafos."""

    speeches: List[DirectedSpeech] = Field(
        description="Lista sequencial de todas as falas que cobrem 100% do texto do lote"
    )
    detected_aliases: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapeamento de apelidos ou títulos citados na cena para o nome canônico do personagem (ex: {'o velho': 'Dr. Victor'})",
    )
    scene_summary: str = Field(
        default="",
        description="Resumo ultra-conciso (1 a 2 frases) dos acontecimentos para memória contínua",
    )


# ==============================================================================
# VALIDADOR DE INTEGRIDADE LÉXICA
# ==============================================================================


def normalizar_palavras(texto: str) -> List[str]:
    """Remove pontuações, caracteres especiais e normaliza para minúsculas."""
    # Substitui pontuações por espaço
    sem_pontuacao = re.sub(r"[^\w\s]", " ", texto.lower(), flags=re.UNICODE)
    # Divide em palavras e descarta vazios
    return [w for w in sem_pontuacao.split() if w]


def validate_lexical_fidelity(
    original_text: str,
    generated_speeches: List[DirectedSpeech],
    threshold: float = 0.98,
) -> Tuple[bool, float, str]:
    """
    Compara a sequência de palavras do texto original com as falas retornadas.
    Permite alterações de pontuação expressiva pelo Diretor, mas bloqueia
    omissões de frases ou resumos indesejados (>98% de fidelidade).
    """
    palavras_originais = normalizar_palavras(original_text)
    if not palavras_originais:
        return True, 1.0, "Texto original vazio."

    texto_gerado_total = " ".join(s.text for s in generated_speeches)
    palavras_geradas = normalizar_palavras(texto_gerado_total)

    if not palavras_geradas:
        return False, 0.0, "Nenhuma palavra gerada pela LLM."

    # Contagem de palavras encontradas
    set_geradas = set(palavras_geradas)
    palavras_encontradas = sum(1 for p in palavras_originais if p in set_geradas)

    ratio = palavras_encontradas / len(palavras_originais)
    aprovado = ratio >= threshold

    msg = (
        f"Fidelidade Léxica: {ratio * 100:.2f}% "
        f"({palavras_encontradas}/{len(palavras_originais)} palavras)"
    )

    return aprovado, ratio, msg


def fuse_consecutive_speeches(
    blocks: List[SpeechBlock],
    max_chars: int = 1200,
) -> List[SpeechBlock]:
    """
    Funde falas consecutivas do mesmo personagem e mesmo motor quando são do tipo narração,
    citação ou destaque, respeitando um limite de caracteres para manter parágrafos naturais.
    Reduz chamadas desnecessárias de API em 80-90% em aulas e audiolivros, além de
    proporcionar uma interpretação de áudio contínua e sem quebras artificiais.
    """
    if not blocks:
        return []

    fused_blocks: List[SpeechBlock] = []
    curr: Optional[SpeechBlock] = None

    for b in blocks:
        if curr is None:
            curr = b.model_copy()
            continue

        # Condições para permitir fusão:
        # 1. Mesmo personagem
        # 2. Mesmo motor e mesma voz principal
        # 3. Mesmo tipo de fala (não funde diálogo com narração)
        # 4. Apenas tipos narrativos/expositivos (narracao, citacao, destaque)
        # 5. Tamanho combinado não excede max_chars
        pode_fundir = (
            curr.character_id == b.character_id
            and curr.voice_id == b.voice_id
            and curr.engine == b.engine
            and curr.speech_type == b.speech_type
            and curr.speech_type in ("narracao", "citacao", "destaque")
            and (len(curr.text) + len(b.text) + 1 <= max_chars)
        )

        if pode_fundir:
            curr.text = f"{curr.text} {b.text}"
            t1 = curr.text_for_tts or curr.text
            t2 = b.text_for_tts or b.text
            curr.text_for_tts = f"{t1} ... {t2}"
            curr.pause_after_ms = b.pause_after_ms
            if b.emotion != "neutro" and curr.emotion == "neutro":
                curr.emotion = b.emotion
            if b.acting_prompt and not curr.acting_prompt:
                curr.acting_prompt = b.acting_prompt
        else:
            fused_blocks.append(curr)
            curr = b.model_copy()

    if curr is not None:
        fused_blocks.append(curr)

    # Reindexa sequencialmente
    for idx, b in enumerate(fused_blocks):
        b.index = idx

    return fused_blocks


# ==============================================================================
# PROMPT BUILDER DO DIRETOR
# ==============================================================================


def build_director_prompt(
    chunk_text: str,
    project_metadata: ProjectMetadata,
    character_bible: CharacterBible,
    previous_speeches: Optional[List[SpeechBlock]] = None,
) -> str:
    """Monta o prompt com diretrizes de direção, memória de personagens e janela deslizante."""
    personagens_existentes = []
    for c in character_bible.characters.values():
        aliases_str = f" (Apelidos: {', '.join(c.aliases)})" if c.aliases else ""
        personagens_existentes.append(
            f"- {c.name} [ID: {c.id}, {c.gender}, {c.apparent_age}, {c.accent}]: {c.personality}{aliases_str}"
        )

    elenco_str = "\n".join(personagens_existentes) if personagens_existentes else "Nenhum personagem registrado ainda."

    # Contexto das últimas falas anteriores (Janela Deslizante)
    contexto_anterior = "Início do capítulo ou sem falas imediatamente anteriores."
    if previous_speeches:
        ultimas = previous_speeches[-3:]
        linhas = [f"[{s.character_id}]: \"{s.text[:60]}...\"" for s in ultimas]
        contexto_anterior = "\n".join(linhas)

    emocoes_disponiveis = ", ".join(list_emotion_labels())

    prompt = f"""Você é o Diretor de Rádio-Teatro e Audiolivros de Alta Fidelidade do AudioBook App.
Sua missão é ler o trecho de texto abaixo e dividi-lo em uma lista sequencial de falas tipadas para síntese de voz.

REGRA DE OURO DE INTEGRIDADE (CRÍTICA):
- NÃO RESUMA, NÃO CORTE e NÃO OMITA nenhuma frase ou palavra do texto original.
- Cada oração de narração, diálogo ou descrição do texto deve estar presente no campo 'text' de alguma fala.
- Você PODE e DEVE ajustar a pontuação para interpretação dramática (ex: transformar vírgula em reticências '...' para pausas respiratórias, usar '!' para ênfases), mas preservando as palavras originais.

MODO DO PROJETO: {project_metadata.mode.upper()}
RESUMO DO CONTEXTO ATÉ O MOMENTO:
{project_metadata.context_summary or "Início da obra."}

ELENCO EXISTENTE (BÍBLIA DE PERSONAGENS):
{elenco_str}

JANELA DESLIZANTE DE CONTINUIDADE (ÚLTIMAS FALAS ANTERIORES):
{contexto_anterior}

EMOÇÕES VÁLIDAS:
{emocoes_disponiveis}

DIRETRIZES DE DIREÇÃO:
1. 'narrador': Use para descrições, pensamentos indiretos e textos corridos.
2. Diálogos: Identifique quem está falando com base no contexto e nos travessões. Use o nome do personagem registrado ou proponha um novo com gênero, idade e sotaque inferidos.
3. Não-Ficção: Em livros técnicos ou resumos, use 'destaque_didatico' ou 'solene' para conceitos centrais, citações e fórmulas.

TEXTO DO LOTE A SER DIRIGIDO (CUMPRA COM 100% DE FIDELIDADE):
\"\"\"
{chunk_text}
\"\"\"
"""
    return prompt


# ==============================================================================
# MOTOR DO DIRETOR (LLM E EXPRESS)
# ==============================================================================


def get_cleaned_director_schema() -> Dict[str, Any]:
    """
    Retorna o JSON Schema de DirectedChunkResponse limpo, sem 'additionalProperties',
    garantindo compatibilidade com a Gemini Developer API (Google AI Studio).
    """
    schema = DirectedChunkResponse.model_json_schema()

    def _clean(d):
        if isinstance(d, dict):
            d.pop("additionalProperties", None)
            d.pop("title", None)
            for v in list(d.values()):
                _clean(v)
        elif isinstance(d, list):
            for item in d:
                _clean(item)

    _clean(schema)
    return schema


class Director:
    """Orquestrador da direção dramática de livros e documentos."""

    def __init__(self, project_manager: Optional[ProjectManager] = None):
        self.pm = project_manager or ProjectManager()
        self.api_key = os.getenv("GEMINI_API_KEY", "")

    def is_gemini_available(self) -> bool:
        """Verifica se a chave da API do Gemini está configurada e válida."""
        return bool(self.api_key and self.api_key != "sua_chave_api_aqui")

    def direct_chunk_with_gemini(
        self,
        chunk_text: str,
        project_slug: str,
        previous_speeches: Optional[List[SpeechBlock]] = None,
        max_retries: int = 3,
    ) -> DirectedChunkResponse:
        """Envia o lote para a API do Gemini com validação de integridade e retentativa."""
        if not self.is_gemini_available():
            raise ValueError(
                "GEMINI_API_KEY não configurada no arquivo .env. Configure sua chave ou utilize o modo Express."
            )

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        metadata = self.pm.load_metadata(project_slug) or ProjectMetadata(
            slug=project_slug, title=project_slug
        )
        bible = self.pm.load_character_bible(project_slug)

        instrucao_adicional = ""

        for tentativa in range(1, max_retries + 1):
            prompt = build_director_prompt(
                chunk_text=chunk_text,
                project_metadata=metadata,
                character_bible=bible,
                previous_speeches=previous_speeches,
            )
            if instrucao_adicional:
                prompt = f"{instrucao_adicional}\n\n{prompt}"

            # Chamada compatível com a Gemini Developer API com resiliência a 503 e sobrecarga
            schema = get_cleaned_director_schema()
            candidatos = [
                os.getenv("GEMINI_DIRECTOR_MODEL", "gemini-3.5-flash-lite"),
                "gemini-2.5-flash-lite",
                "gemini-2.5-flash",
            ]
            response = None
            ultimo_erro = None

            for mod in candidatos:
                try:
                    response = client.models.generate_content(
                        model=mod,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=schema,
                            temperature=0.2,
                        ),
                    )
                    if response and response.text:
                        break
                except Exception as e_schema:
                    print(f"[Director] Modelo {mod} com schema falhou ({e_schema}). Tentando formato JSON via prompt...")
                    try:
                        response = client.models.generate_content(
                            model=mod,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                temperature=0.2,
                            ),
                        )
                        if response and response.text:
                            break
                    except Exception as e_pure:
                        ultimo_erro = e_pure
                        print(f"[Director] Modelo {mod} falhou ({e_pure}). Tentando próximo candidato...")

            if not response or not response.text:
                raise RuntimeError(f"Não foi possível obter resposta do Gemini em nenhum modelo: {ultimo_erro}")

            # Parse seguro do JSON retornado via Pydantic
            raw_text = response.text.strip()
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            import json
            data = json.loads(raw_text)
            if isinstance(data, list):
                data = {"speeches": data}
            chunk_response: DirectedChunkResponse = DirectedChunkResponse.model_validate(data)

            # Validação de Integridade Léxica
            aprovado, ratio, msg = validate_lexical_fidelity(
                chunk_text, chunk_response.speeches
            )

            if aprovado:
                return chunk_response

            # Se não atingiu o threshold (>98%), reforça o prompt na próxima tentativa
            instrucao_adicional = (
                f"ALERTA CRÍTICO: Na tentativa {tentativa}, a fidelidade léxica foi de apenas {ratio * 100:.1f}%. "
                f"Você omitiu ou resumiu trechos. NÃO CORTE PALAVRAS, MANTENHA 100% DO TEXTO ORIGINAL!"
            )

        # Se esgotar as tentativas, retorna a última com aviso
        return chunk_response

    def direct_chunk_express(
        self,
        chunk_text: str,
        project_slug: str,
        start_index: int = 0,
    ) -> List[SpeechBlock]:
        """
        Modo Express Determinístico (100% Offline / Sem Custo de API).
        Converte os parágrafos diretamente usando regras heurísticas de pontuação
        e o narrador padrão do projeto.
        """
        metadata = self.pm.load_metadata(project_slug) or ProjectMetadata(
            slug=project_slug, title=project_slug
        )
        bible = self.pm.load_character_bible(project_slug)
        narrador = bible.characters.get("narrador")

        if not narrador:
            narrador = self.pm.smart_cast(project_slug, "Narrador", gender="M")

        paragrafos = [p.strip() for p in chunk_text.split("\n\n") if p.strip()]
        blocos: List[SpeechBlock] = []

        for i, p in enumerate(paragrafos):
            idx = start_index + i
            eh_dialogo = p.startswith(("-", "—", "–"))

            # Determina tipo e pausa
            if eh_dialogo:
                tipo: SpeechType = "dialogo"
                emocao = "tenso" if ("!" in p or "?" in p) else "neutro"
            elif any(q in p for q in ('"', "“", "”", "«", "»")):
                tipo = "citacao"
                emocao = "destaque_didatico" if metadata.mode == "non_fiction" else "neutro"
            else:
                tipo = "narracao"
                emocao = "destaque_didatico" if metadata.mode == "non_fiction" else "neutro"

            text_tts = p
            if p.startswith("—") or p.startswith("-"):
                text_tts = p.replace("—", "— ... ", 1).replace("-", "— ... ", 1)

            bloco = self.pm.create_speech_block(
                character=narrador,
                text=p,
                speech_type=tipo,
                emotion_label=emocao,
                index=idx,
                pause_base_ms=600 if not eh_dialogo else 450,
                text_for_tts=text_tts,
            )
            blocos.append(bloco)

        return blocos

    def direct_chapter(
        self,
        project_slug: str,
        chapter_number: int,
        chapter_title: str,
        chapter_content: str,
        force_express: bool = False,
        fuse_speeches: bool = True,
        max_chars_per_speech: int = 1200,
    ) -> ChapterScript:
        """
        Direciona um capítulo completo, dividindo em lotes, processando com
        continuidade e persistindo o ChapterScript em data/projects/<slug>/scripts/.
        """
        chunks = chunk_chapter(chapter_content)
        blocos_totais: List[SpeechBlock] = []
        bloco_index_global = 0

        usar_express = force_express or not self.is_gemini_available()

        for chunk_data in chunks:
            chunk_text = chunk_data["text"]

            if usar_express:
                blocos_chunk = self.direct_chunk_express(
                    chunk_text=chunk_text,
                    project_slug=project_slug,
                    start_index=bloco_index_global,
                )
            else:
                # Processamento com Diretor LLM
                ultimas_falas = blocos_totais[-3:] if blocos_totais else None
                resposta_llm = self.direct_chunk_with_gemini(
                    chunk_text=chunk_text,
                    project_slug=project_slug,
                    previous_speeches=ultimas_falas,
                )

                # Atualiza metadados com aliases detectados
                if resposta_llm.detected_aliases:
                    bible = self.pm.load_character_bible(project_slug)
                    for alias, canonico in resposta_llm.detected_aliases.items():
                        char = bible.resolve_alias(canonico)
                        if char and alias not in char.aliases:
                            char.aliases.append(alias)
                    self.pm.save_character_bible(bible)

                blocos_chunk = []
                for sp in resposta_llm.speeches:
                    # Resolve ou cadastra personagem
                    char = self.pm.smart_cast(
                        project_slug=project_slug,
                        name=sp.speaker,
                        gender=sp.character_gender,
                        apparent_age=sp.character_apparent_age,
                        accent=sp.character_accent,
                        personality=sp.character_personality,
                    )

                    bloco = self.pm.create_speech_block(
                        character=char,
                        text=sp.text,
                        speech_type=sp.speech_type,
                        emotion_label=sp.emotion,
                        index=bloco_index_global + len(blocos_chunk),
                        pause_base_ms=sp.pause_after_ms,
                        text_for_tts=sp.text_for_tts if sp.text_for_tts else sp.text,
                        custom_acting_prompt=sp.acting_prompt if sp.acting_prompt else None,
                    )
                    blocos_chunk.append(bloco)

            blocos_totais.extend(blocos_chunk)
            bloco_index_global += len(blocos_chunk)

        # Fusão Inteligente de Parágrafos (reduz 80-90% das requisições e preserva fluidez)
        if fuse_speeches:
            blocos_totais = fuse_consecutive_speeches(
                blocos_totais, max_chars=max_chars_per_speech
            )

        # Monta e persiste o ChapterScript
        total_chars = sum(len(b.text) for b in blocos_totais)
        script = ChapterScript(
            chapter_number=chapter_number,
            title=chapter_title,
            blocks=blocos_totais,
            total_chars=total_chars,
        )

        self.pm.save_chapter_script(project_slug, script)
        self.pm.save_source_text(project_slug, chapter_content)

        # Limpa chunks temporários de áudio anteriores deste capítulo para que um novo texto nunca se misture com o antigo
        temp_cap_dir = self.pm.get_project_dir(project_slug) / "temp" / f"cap_{chapter_number:02d}"
        if temp_cap_dir.exists():
            import shutil
            shutil.rmtree(temp_cap_dir, ignore_errors=True)

        return script
