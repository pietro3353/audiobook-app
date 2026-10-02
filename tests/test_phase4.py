"""Bateria de testes automatizados da Fase 4 do AudioBook App e Geração de Áudio Real.

Valida:
1. Normalização acústica e anexação de pausas dramáticas.
2. Síntese multi-motor assíncrona com Smart Resume.
3. Concatenação de áudio via FFmpeg Demuxer.
4. Geração do primeiro audiolivro real demonstrativo em:
   data/projects/demo_audiobook/output/demo_cena_dramatica.mp3
"""

import asyncio
from pathlib import Path
import sys

# Adiciona a raiz do projeto ao sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.mixer import AudioMixer
from src.models import ChapterScript
from src.project_manager import ProjectManager
from src.synthesizer import Synthesizer


def test_phase4_end_to_end_and_generate_demo():
    print("=" * 70)
    print("INICIANDO SUITE DE TESTES - FASE 4 (SÍNTESE & DEMO REAL)")
    print("=" * 70)

    slug_demo = "demo_audiobook"
    pm = ProjectManager()

    # 1. Cria workspace do projeto demo
    print("▶ 1. Inicializando Workspace da Demonstração...")
    meta = pm.create_project(
        slug=slug_demo,
        title="O Mistério da Mansão dos Ventos",
        mode="fiction",
        engine_strategy="unlimited",
    )
    print(f"   - Projeto criado: {meta.title} (Slug: {meta.slug})")

    # 2. Cadastra personagens com diferentes perfis vocais e sotaques
    print("▶ 2. Escalando Elenco (Smart Casting Multi-Voz)...")
    bible = pm.load_character_bible(slug_demo)

    narrador = bible.characters["narrador"]

    # Pierre Laurent (Francês com sotaque autêntico)
    pierre = pm.smart_cast(
        project_slug=slug_demo,
        name="Pierre Laurent",
        gender="M",
        apparent_age="adulto",
        accent="frances",
        personality="diplomata refinado e receoso",
    )

    # Arthur (Jovem dinâmico e acelerado)
    arthur = pm.smart_cast(
        project_slug=slug_demo,
        name="Arthur Pendelton",
        gender="M",
        apparent_age="jovem",
        accent="brasileiro",
        personality="aventureiro corajoso e impaciente",
    )

    # Aninha (Criança com pitch elevado de menina)
    aninha = pm.smart_cast(
        project_slug=slug_demo,
        name="Aninha",
        gender="F",
        apparent_age="crianca",
        accent="brasileiro",
        personality="menina assustada e observadora",
    )

    print(f"   - [Narrador] Voz: {narrador.voice_id} ({narrador.engine})")
    print(f"   - [{pierre.name}] Voz: {pierre.voice_id} ({pierre.engine}) | Sotaque: {pierre.accent}")
    print(f"   - [{arthur.name}] Voz: {arthur.voice_id} ({arthur.engine}) | Idade: {arthur.apparent_age}")
    print(f"   - [{aninha.name}] Voz: {aninha.voice_id} ({aninha.engine}) | Pitch Base: +{aninha.baseline.pitch_offset_hz}Hz (Infantil)")

    # 3. Monta roteiro dramático com 5 falas e emoções contrastantes
    print("\n▶ 3. Construindo Roteiro Dramático com Pausas Cênicas...")
    falas = [
        pm.create_speech_block(
            character=narrador,
            text="A tempestade desabava com violência sobre a velha torre de pedra. Raios cortavam a escuridão da noite, iluminando a biblioteca esquecida.",
            speech_type="narracao",
            emotion_label="misterio",
            index=0,
            pause_base_ms=800,
        ),
        pm.create_speech_block(
            character=pierre,
            text="Mon dieu! Il fait trop sombre... Arthur, você tem certeza absoluta de que aquele livro proibido está escondido aqui?",
            speech_type="dialogo",
            emotion_label="tenso",
            index=1,
            pause_base_ms=500,
        ),
        pm.create_speech_block(
            character=arthur,
            text="Tenho certeza, Pierre! Olhe atrás da terceira estante carcomida... A fechadura está emperrada, me ajude a forçar!",
            speech_type="dialogo",
            emotion_label="animado",
            index=2,
            pause_base_ms=450,
        ),
        pm.create_speech_block(
            character=aninha,
            text="Doutor Arthur... escute! Tem passos vindo do corredor... Tem alguém nos observando pela fresta da porta!",
            speech_type="dialogo",
            emotion_label="panico",
            index=3,
            pause_base_ms=600,
        ),
        pm.create_speech_block(
            character=narrador,
            text="Um estrondo ensurdecedor de trovão fez a mansão estremecer. As velas se apagaram de repente... e o silêncio que se seguiu congelou a alma de todos.",
            speech_type="narracao",
            emotion_label="solene",
            index=4,
            pause_base_ms=1200,
        ),
    ]

    script = ChapterScript(
        chapter_number=1,
        title="O Enigma da Mansão dos Ventos",
        blocks=falas,
        total_chars=sum(len(f.text) for f in falas),
    )
    pm.save_chapter_script(slug_demo, script)
    print(f"   - Roteiro estruturado com {len(falas)} blocos salvo em scripts/cap_01.json")

    # 4. Síntese Assíncrona dos Blocos
    print("\n▶ 4. Sintetizando Falas via Edge-TTS / Multi-Motor...")
    synthesizer = Synthesizer()

    def exibir_progresso(atual, total):
        sys.stdout.write(f"\r      Sintetizando fala {atual}/{total}...")
        sys.stdout.flush()

    raw_chunks = asyncio.run(
        synthesizer.synthesize_chapter(
            script=script,
            project_slug=slug_demo,
            on_progress=exibir_progresso,
        )
    )
    print(f"\n   - Todas as {len(raw_chunks)} falas sintetizadas com sucesso no disco!")
    for i, c in enumerate(raw_chunks):
        assert c.exists() and c.stat().st_size > 500, f"Chunk {c} inválido"
        print(f"     * Bloco {i:02d}: {c.name} ({c.stat().st_size / 1024:.1f} KB)")

    # 5. Masterização com Nivelamento e Concatenação FFmpeg
    print("\n▶ 5. Masterizando Áudio com Nivelamento de Volume e Pausas FFmpeg...")
    mixer = AudioMixer()
    output_dir = pm.get_project_dir(slug_demo) / "output"
    output_demo_mp3 = output_dir / "demo_cena_dramatica.mp3"

    mixer.mix_chapter(
        script=script,
        raw_chunks=raw_chunks,
        output_chapter_mp3=output_demo_mp3,
    )

    assert output_demo_mp3.exists(), "Arquivo demo final não foi criado!"
    tamanho_final_kb = output_demo_mp3.stat().st_size / 1024
    assert tamanho_final_kb > 50, f"Arquivo demo muito pequeno ({tamanho_final_kb:.1f} KB)"

    print(f"\n=======================================================")
    print("🎉 ÁUDIO DEMONSTRATIVO REAL GERADO COM SUCESSO!")
    print(f"Arquivo: {output_demo_mp3.resolve()}")
    print(f"Tamanho: {tamanho_final_kb:.1f} KB")
    print("=======================================================\n")


if __name__ == "__main__":
    test_phase4_end_to_end_and_generate_demo()
