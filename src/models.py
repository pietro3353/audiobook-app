"""Contratos de Dados e Modelos Pydantic para o AudioBook App.

Define os schemas estritos para Bíblia de Personagens, Roteiros Estruturados
e Metadados de Projetos, incluindo Identidade Dupla e Fallback Anti-Cota.
"""

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# ==============================================================================
# TIPOS LITERAIS
# ==============================================================================
EngineType = Literal["edge", "kokoro", "gemini"]
FallbackEngineType = Literal["edge", "kokoro"]
GenderType = Literal["M", "F", "neutral"]
AgeGroup = Literal["crianca", "jovem", "adulto", "maduro"]
AccentType = Literal[
    "brasileiro",
    "portugues",
    "americano",
    "frances",
    "italiano",
    "alemao",
    "espanhol",
    "britanico",
    "asiatico",
]
ProjectMode = Literal["fiction", "non_fiction", "summary"]
EngineStrategy = Literal["unlimited", "hybrid"]
SpeechType = Literal["narracao", "dialogo", "pensamento", "citacao", "destaque"]


# ==============================================================================
# BÍBLIA DE PERSONAGENS & DNA VOCAL
# ==============================================================================


class CharacterBaseline(BaseModel):
    """Assinatura acústica fixa do personagem (idade e porte físico)."""

    pitch_offset_hz: int = Field(
        default=0,
        description="Deslocamento base de tom em Hz (ex: -5Hz para idoso, +6Hz para criança)",
    )
    rate_offset_pct: int = Field(
        default=0,
        description="Deslocamento base de velocidade em % (ex: -6% para idoso lento, +4% para jovem elétrico)",
    )
    volume_offset_pct: int = Field(
        default=0, description="Deslocamento base de volume em %"
    )


class Character(BaseModel):
    """Ficha completa do personagem na Bíblia do livro."""

    id: str = Field(
        description="Identificador único em slug (ex: 'dr_victor', 'narrador')"
    )
    name: str = Field(description="Nome canônico (ex: 'Dr. Victor Frank')")
    aliases: List[str] = Field(
        default_factory=list,
        description="Sinônimos e apelidos no texto (ex: ['Victor', 'o médico', 'o velho cientista'])",
    )
    gender: GenderType = Field(default="M")
    apparent_age: AgeGroup = Field(default="adulto")
    personality: str = Field(
        default="neutro",
        description="Traços de comportamento (ex: 'ranzinza, cético e apressado')",
    )
    accent: AccentType = Field(default="brasileiro")

    # Identidade Principal
    voice_id: str = Field(
        description="ID da voz no catálogo (ex: 'gemini_charon' ou 'edge_antonio')"
    )
    engine: EngineType = Field(
        default="edge", description="Motor de síntese primário"
    )

    # Identidade Dupla / Fallback Anti-Cota (Garante execução se Gemini estourar cota)
    fallback_voice_id: str = Field(
        default="edge_antonio",
        description="Voz reserva garantida no Edge ou Kokoro",
    )
    fallback_engine: FallbackEngineType = Field(
        default="edge", description="Motor ilimitado de contingência"
    )

    # Assinaturas Acústica e Cênica
    baseline: CharacterBaseline = Field(default_factory=CharacterBaseline)
    acting_style: str = Field(
        default="",
        description="Diretriz de atuação geral para motores multimodais (Gemini)",
    )
    blend_recipe: Optional[Dict[str, float]] = Field(
        default=None,
        description="Receita de fusão caso utilize Kokoro Blending (ex: {'pm_santa': 0.7, 'pm_alex': 0.3})",
    )


class CharacterBible(BaseModel):
    """Bíblia de Personagens persistente de um projeto."""

    project_slug: str
    characters: Dict[str, Character] = Field(default_factory=dict)

    def resolve_alias(self, name_query: str) -> Optional[Character]:
        """Verifica se um nome consultado corresponde a um personagem ou alias existente."""
        termo = name_query.strip().lower()
        if not termo:
            return None

        for char in self.characters.values():
            if char.name.lower() == termo or char.id.lower() == termo:
                return char
            for alias in char.aliases:
                if alias.strip().lower() == termo:
                    return char

        return None

    def add_character(self, character: Character):
        """Registra ou atualiza um personagem na Bíblia."""
        self.characters[character.id] = character

    def get(self, character_id: str) -> Optional[Character]:
        """Obtém um personagem pelo ID."""
        return self.characters.get(character_id)


# ==============================================================================
# ROTEIRO ESTRUTURADO DE CAPÍTULO
# ==============================================================================


class SpeechBlock(BaseModel):
    """Bloco atômico de fala estruturado pronto para a síntese."""

    index: int
    character_id: str
    speech_type: SpeechType = "dialogo"
    text: str = Field(description="Texto exato a ser sintetizado")
    emotion: str = Field(default="neutro")
    pause_after_ms: int = Field(
        default=600,
        description="Silêncio em milissegundos após a fala para respiração dramática",
    )

    # Configurações do Motor Principal
    engine: str = "edge"
    voice_id: str = "edge_antonio"

    # Configurações de Contingência Anti-Cota
    fallback_engine: str = "edge"
    fallback_voice_id: str = "edge_antonio"

    # Parâmetros Acústicos (Edge / Kokoro / Pydub)
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"

    # Instrução Cênica em Linguagem Natural (Gemini Audio)
    acting_prompt: Optional[str] = None

    # Receita de Voice Blending (Kokoro)
    blend_recipe: Optional[Dict[str, float]] = None


class ChapterScript(BaseModel):
    """Roteiro completo de um capítulo estruturado em falas sequenciais."""

    chapter_number: int
    title: str = ""
    blocks: List[SpeechBlock] = Field(default_factory=list)
    total_chars: int = 0
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ==============================================================================
# METADADOS DO PROJETO (WORKSPACE)
# ==============================================================================


class ProjectMetadata(BaseModel):
    """Metadados e configurações globais de um workspace de livro ou documento."""

    slug: str
    title: str
    mode: ProjectMode = "fiction"
    engine_strategy: EngineStrategy = Field(
        default="unlimited",
        description="'unlimited' para Edge+Kokoro sem cota, 'hybrid' permitindo Gemini TTS para diálogos principais",
    )
    context_summary: str = Field(
        default="",
        description="Resumo cumulativo dos eventos até o capítulo atual",
    )
    default_narrator_voice: str = "edge_antonio"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
