"""Gerenciador de Workspaces e Memória Persistente de Projetos.

Responsável por:
1. Isolar cada livro/documento em data/projects/<slug>/ (metadados, bíblia, scripts, áudios).
2. Resolução inteligente de Apelidos (Aliases) para continuidade de personagens.
3. Smart Casting (Anti-Colisão Vocal): Alocação de vozes baseada em afinidade de idade/sotaque,
   priorizando vozes não usadas e diferenciando vozes reutilizadas via baseline acústico.
4. Identidade Dupla e Alocação de Fallback Anti-Cota automática.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from src.emotions import calculate_acoustic_parameters
from src.models import (
    AgeGroup,
    AccentType,
    ChapterScript,
    Character,
    CharacterBaseline,
    CharacterBible,
    EngineStrategy,
    GenderType,
    ProjectMetadata,
    ProjectMode,
    SpeechBlock,
    SpeechType,
)
from src.voices import (
    VOICE_CATALOG,
    VoiceProfile,
    find_fallback_voice,
    get_voice_by_id,
    list_voices,
)

# Diretório padrão para os workspaces de projetos
DEFAULT_PROJECTS_DIR = Path("data") / "projects"


def slugify(text: str) -> str:
    """Converte um nome para formato slug seguro para pastas e identificadores."""
    text = text.strip().lower()
    text = re.sub(r"[àáâãäå]", "a", text)
    text = re.sub(r"[èéêë]", "e", text)
    text = re.sub(r"[ìíîï]", "i", text)
    text = re.sub(r"[òóôõö]", "o", text)
    text = re.sub(r"[ùúûü]", "u", text)
    text = re.sub(r"[ç]", "c", text)
    text = re.sub(r"[^a-z0-9_-]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


class ProjectManager:
    """Controlador de arquivos e memória persistente para um projeto."""

    def __init__(self, base_dir: Path = DEFAULT_PROJECTS_DIR):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_project_dir(self, slug: str) -> Path:
        """Retorna o caminho do diretório do projeto."""
        return self.base_dir / slug

    def project_exists(self, slug: str) -> bool:
        """Verifica se o projeto já foi criado."""
        return (self.get_project_dir(slug) / "metadata.json").exists()

    def create_project(
        self,
        slug: str,
        title: str,
        mode: ProjectMode = "fiction",
        engine_strategy: EngineStrategy = "unlimited",
        default_narrator_voice: str = "edge_antonio",
    ) -> ProjectMetadata:
        """Cria um novo workspace isolado para um livro ou documento."""
        clean_slug = slugify(slug)
        project_dir = self.get_project_dir(clean_slug)
        project_dir.mkdir(parents=True, exist_ok=True)

        # Cria subpastas essenciais
        (project_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (project_dir / "output").mkdir(parents=True, exist_ok=True)

        metadata = ProjectMetadata(
            slug=clean_slug,
            title=title,
            mode=mode,
            engine_strategy=engine_strategy,
            default_narrator_voice=default_narrator_voice,
        )

        self.save_metadata(metadata)

        # Inicializa a Bíblia de Personagens com o Narrador padrão
        bible = CharacterBible(project_slug=clean_slug)
        narrador_voice = get_voice_by_id(default_narrator_voice) or VOICE_CATALOG["edge_antonio"]

        narrador = Character(
            id="narrador",
            name="Narrador",
            aliases=["narracao", "voz principal", "narrador principal"],
            gender=narrador_voice.gender,
            apparent_age=narrador_voice.apparent_age,
            personality="sóbrio, claro e envolvente",
            accent=narrador_voice.accent,
            voice_id=narrador_voice.id,
            engine=narrador_voice.engine,
            fallback_voice_id=narrador_voice.id,
            fallback_engine=narrador_voice.engine if narrador_voice.engine in ("edge", "kokoro") else "edge",
            baseline=CharacterBaseline(pitch_offset_hz=0, rate_offset_pct=-4, volume_offset_pct=0),
            acting_style="Narração clássica de audiolivro, com ritmo contido e excelente dicção.",
        )
        bible.add_character(narrador)
        self.save_character_bible(bible)

        return metadata

    def load_metadata(self, slug: str) -> Optional[ProjectMetadata]:
        """Carrega os metadados do projeto."""
        meta_file = self.get_project_dir(slug) / "metadata.json"
        if not meta_file.exists():
            return None
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ProjectMetadata(**data)

    def save_metadata(self, metadata: ProjectMetadata):
        """Salva os metadados do projeto em metadata.json."""
        meta_file = self.get_project_dir(metadata.slug) / "metadata.json"
        metadata.updated_at = datetime.now(timezone.utc).isoformat()
        with open(meta_file, "w", encoding="utf-8") as f:
            f.write(metadata.model_dump_json(indent=2))

    def load_character_bible(self, slug: str) -> CharacterBible:
        """Carrega a Bíblia de Personagens do projeto."""
        bible_file = self.get_project_dir(slug) / "characters.json"
        if not bible_file.exists():
            return CharacterBible(project_slug=slug)
        with open(bible_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return CharacterBible(**data)

    def save_character_bible(self, bible: CharacterBible):
        """Persiste a Bíblia de Personagens no disco."""
        bible_file = self.get_project_dir(bible.project_slug) / "characters.json"
        with open(bible_file, "w", encoding="utf-8") as f:
            f.write(bible.model_dump_json(indent=2))

    def load_chapter_script(self, slug: str, chapter_number: int) -> Optional[ChapterScript]:
        """Carrega o roteiro de um capítulo em scripts/cap_XX.json."""
        script_file = self.get_project_dir(slug) / "scripts" / f"cap_{chapter_number:02d}.json"
        if not script_file.exists():
            return None
        with open(script_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ChapterScript(**data)

    def save_chapter_script(self, slug: str, script: ChapterScript):
        """Salva o roteiro estruturado do capítulo no cache persistente."""
        scripts_dir = self.get_project_dir(slug) / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_file = scripts_dir / f"cap_{script.chapter_number:02d}.json"
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(script.model_dump_json(indent=2))

    def list_projects(self) -> List[str]:
        """Lista os slugs de todos os projetos cadastrados."""
        if not self.base_dir.exists():
            return []
        return [
            d.name
            for d in self.base_dir.iterdir()
            if d.is_dir() and (d / "metadata.json").exists()
        ]

    # ==========================================================================
    # SMART CASTING & RESOLUÇÃO DE ALIASES
    # ==========================================================================

    def smart_cast(
        self,
        project_slug: str,
        name: str,
        gender: GenderType = "M",
        apparent_age: AgeGroup = "adulto",
        accent: AccentType = "brasileiro",
        personality: str = "neutro",
        aliases: Optional[List[str]] = None,
        is_protagonist: bool = False,
    ) -> Character:
        """
        Escala uma voz para o personagem de forma inteligente e anti-colisão.
        1. Se já existir por nome ou alias, retorna o personagem existente.
        2. Se for inédito, escolhe a melhor voz considerando sotaque, idade e estratégia do motor.
        3. Configura a Identidade Dupla (Fallback Anti-Cota).
        4. Diferencia vozes reutilizadas através de baseline acústico.
        """
        bible = self.load_character_bible(project_slug)
        metadata = self.load_metadata(project_slug) or ProjectMetadata(
            slug=project_slug, title=project_slug
        )

        aliases = aliases or []

        # 1. Resolução de Aliases: Verifica se o personagem já existe
        char_existente = bible.resolve_alias(name)
        if not char_existente:
            for alias in aliases:
                char_existente = bible.resolve_alias(alias)
                if char_existente:
                    break

        if char_existente:
            # Atualiza lista de aliases se houver novos sinônimos
            novos_aliases = set(char_existente.aliases + aliases)
            if name.lower() != char_existente.name.lower() and name not in novos_aliases:
                novos_aliases.add(name)
            char_existente.aliases = sorted(list(novos_aliases))
            self.save_character_bible(bible)
            return char_existente

        # 2. Personagem novo: Definir ID único
        base_id = slugify(name)
        char_id = base_id
        contador = 2
        while char_id in bible.characters:
            char_id = f"{base_id}_{contador}"
            contador += 1

        # 3. Conjunto de vozes já em uso neste projeto
        vozes_em_uso = {c.voice_id for c in bible.characters.values()}

        # 4. Seleção da Voz Principal baseada na Estratégia de Motores
        vozes_candidatas: List[VoiceProfile] = []

        if metadata.engine_strategy == "hybrid" and is_protagonist:
            # Em modo híbrido, protagonistas podem usar Gemini Audio com atuação dramática
            vozes_candidatas = list_voices(
                engine="gemini", gender=gender, apparent_age=apparent_age, accent=accent
            )
            if not vozes_candidatas:
                vozes_candidatas = list_voices(engine="gemini", gender=gender)

        # Se não for híbrido ou não encontrou no Gemini, busca em Edge e Kokoro
        if not vozes_candidatas:
            vozes_candidatas = [
                v
                for v in list_voices(gender=gender, apparent_age=apparent_age, accent=accent)
                if v.engine in ("edge", "kokoro")
            ]

        # Se ainda vazio, relaxa o sotaque
        if not vozes_candidatas:
            vozes_candidatas = [
                v
                for v in list_voices(gender=gender, apparent_age=apparent_age)
                if v.engine in ("edge", "kokoro")
            ]

        # Se ainda vazio, busca apenas pelo gênero em motores ilimitados
        if not vozes_candidatas:
            vozes_candidatas = [
                v for v in list_voices(gender=gender) if v.engine in ("edge", "kokoro")
            ]

        # Fallback de segurança se a lista ainda estiver vazia
        if not vozes_candidatas:
            vozes_candidatas = [VOICE_CATALOG["edge_antonio"]]

        # 5. Anti-Colisão: Prioriza vozes ainda NÃO utilizadas no projeto
        vozes_livres = [v for v in vozes_candidatas if v.id not in vozes_em_uso]
        voz_escolhida = vozes_livres[0] if vozes_livres else vozes_candidatas[0]

        # 6. Baseline Acústico com Diferenciação se a voz estiver sendo reutilizada
        baseline_pitch = 0
        baseline_rate = 0

        # Se a idade for criança e a voz for Thalita, ajusta tom para infantil
        if apparent_age == "crianca":
            baseline_pitch = 6
            baseline_rate = 3
        elif apparent_age == "maduro":
            baseline_pitch = -4
            baseline_rate = -5
        elif apparent_age == "jovem":
            baseline_pitch = 2
            baseline_rate = 2

        # Se a voz foi reutilizada (colisão inevitável pelo número de personagens),
        # aplica uma assinatura sonora diferente para não soar idêntico
        if voz_escolhida.id in vozes_em_uso:
            vezes_usada = sum(1 for c in bible.characters.values() if c.voice_id == voz_escolhida.id)
            deslocamento = (vezes_usada % 2 * 2 - 1) * 3  # Alterna +3Hz / -3Hz
            baseline_pitch += deslocamento
            baseline_rate += 2 if vezes_usada % 2 == 0 else -2

        # 7. Identidade Dupla: Voz de Contingência Anti-Cota
        fallback_voice = find_fallback_voice(voz_escolhida)

        # 8. Cria e persiste o novo personagem
        novo_personagem = Character(
            id=char_id,
            name=name,
            aliases=aliases,
            gender=gender,
            apparent_age=apparent_age,
            personality=personality,
            accent=accent,
            voice_id=voz_escolhida.id,
            engine=voz_escolhida.engine,
            fallback_voice_id=fallback_voice.id,
            fallback_engine=fallback_voice.engine if fallback_voice.engine in ("edge", "kokoro") else "edge",
            baseline=CharacterBaseline(
                pitch_offset_hz=baseline_pitch,
                rate_offset_pct=baseline_rate,
                volume_offset_pct=0,
            ),
            acting_style=f"Personagem {apparent_age}, gênero {gender}, personalidade {personality}.",
            blend_recipe=voz_escolhida.blend_recipe,
        )

        bible.add_character(novo_personagem)
        self.save_character_bible(bible)
        return novo_personagem

    # ==========================================================================
    # CONSTRUTOR DE BLOCOS DE FALA (SPEECH BLOCKS)
    # ==========================================================================

    def create_speech_block(
        self,
        character: Character,
        text: str,
        speech_type: SpeechType = "dialogo",
        emotion_label: str = "neutro",
        index: int = 0,
        pause_base_ms: int = 600,
    ) -> SpeechBlock:
        """Constrói um bloco atômico de fala calculando os parâmetros acústicos e de atuação."""
        rate_str, pitch_str, vol_str, pause_mult, acting_prompt = calculate_acoustic_parameters(
            baseline_rate_pct=character.baseline.rate_offset_pct,
            baseline_pitch_hz=character.baseline.pitch_offset_hz,
            baseline_volume_pct=character.baseline.volume_offset_pct,
            emotion_label=emotion_label,
            character_personality=character.personality,
        )

        pause_final_ms = int(pause_base_ms * pause_mult)

        # Resgata o código de voz bruto do motor para Edge-TTS
        voz_info = get_voice_by_id(character.voice_id)
        raw_voice_id = voz_info.engine_voice_id if voz_info else character.voice_id

        fallback_info = get_voice_by_id(character.fallback_voice_id)
        raw_fallback_id = fallback_info.engine_voice_id if fallback_info else character.fallback_voice_id

        return SpeechBlock(
            index=index,
            character_id=character.id,
            speech_type=speech_type,
            text=text.strip(),
            emotion=emotion_label,
            pause_after_ms=pause_final_ms,
            engine=character.engine,
            voice_id=raw_voice_id,
            fallback_engine=character.fallback_engine,
            fallback_voice_id=raw_fallback_id,
            rate=rate_str,
            pitch=pitch_str,
            volume=vol_str,
            acting_prompt=acting_prompt,
        )
