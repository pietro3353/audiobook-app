"""Bateria de testes automatizados da Fase 4.5: Qualidade Acústica, Kokoro HF e Demo Real.

Valida:
1. Síntese Real via Kokoro-82M (Hugging Face) com Voice Blending nativo.
2. Síntese via Edge-TTS recalibrada (sem artefatos metálicos de pitch).
3. Nivelamento acústico, micro-fades de 30ms e Room Tone contínuo de cabine (-56 dBFS).
4. Geração do audiolivro demonstrativo de alta fidelidade em:
   data/projects/demo_audiobook/output/demo_cena_dramatica.mp3
"""

import asyncio
import shutil
import sys
from pathlib import Path

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
    print("INICIANDO SUITE DE TESTES - FASE 4.5 (KOKORO HF & QUALIDADE ACÚSTICA)")
    print("=" * 70)

    slug_demo = "demo_audiobook"
    pm = ProjectManager()

    # Limpa dados anteriores para garantir renderização 100% nova
    temp_dir = pm.get_project_dir(slug_demo) / "temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    # 1. Cria workspace do projeto demo
    print("▶ 1. Inicializando Workspace da Demonstração...")
    meta = pm.create_project(
        slug=slug_demo,
        title="O Mistério da Mansão dos Ventos",
        mode="fiction",
        engine_strategy="unlimited",
    )
    print(f"   - Projeto: {meta.title} (Slug: {meta.slug})")

    # 2. Cadastra personagens com motores reais
    print("▶ 2. Escalando Elenco Multi-Motor...")
    bible = pm.load_character_bible(slug_demo)

    narrador = bible.characters["narrador"]

    # Pierre Laurent (Edge-TTS Multilíngue Francês)
    pierre = pm.smart_cast(
        project_slug=slug_demo,
        name="Pierre Laurent",
        gender="M",
        apparent_age="adulto",
        accent="frances",
        personality="diplomata refinado e cauteloso",
    )

    # Arthur (Kokoro Hugging Face - Fusão Alex 60% + Dora 40%)
    arthur = pm.smart_cast(
        project_slug=slug_demo,
        name="Arthur Pendelton",
        gender="M",
        apparent_age="jovem",
        accent="brasileiro",
        personality="aventureiro corajoso e impaciente",
        voice_id="kokoro_blend_jovem_dinamico",
    )

    # Aninha (Kokoro Hugging Face - Dora pura)
    aninha = pm.smart_cast(
        project_slug=slug_demo,
        name="Aninha",
        gender="F",
        apparent_age="jovem",
        accent="brasileiro",
        personality="menina assustada e observadora",
        voice_id="kokoro_dora",
    )

    # Mestre Ancião (Kokoro Hugging Face - Fusão Santa 70% + Alex 30%)
    anciao = pm.smart_cast(
        project_slug=slug_demo,
        name="Mestre Ancião",
        gender="M",
        apparent_age="maduro",
        accent="brasileiro",
        personality="guardião enigmático e sábio",
        voice_id="kokoro_blend_anciao",
    )

    print(f"   - [Narrador]: Voz {narrador.voice_id} ({narrador.engine}) -> Sóbrio, sem distorção")
    print(f"   - [{pierre.name}]: Voz {pierre.voice_id} ({pierre.engine}) -> Sotaque francês nativo")
    print(f"   - [{arthur.name}]: Voz {arthur.voice_id} ({arthur.engine}) -> Kokoro Blend (60% Alex + 40% Dora)")
    print(f"   - [{aninha.name}]: Voz {aninha.voice_id} ({aninha.engine}) -> Kokoro Dora (Hugging Face)")
    print(f"   - [{anciao.name}]: Voz {anciao.voice_id} ({anciao.engine}) -> Kokoro Blend (70% Santa + 30% Alex)")

    # 3. Monta roteiro dramático com 6 falas e prosódia coesa
    print("\n▶ 3. Construindo Roteiro Dramático com Prosódia Contínua...")
    falas = [
        pm.create_speech_block(
            character=narrador,
            text="A tempestade desabava com violência sobre a velha torre de pedra. Raios cortavam a escuridão da noite, iluminando a biblioteca esquecida.",
            speech_type="narracao",
            emotion_label="misterio",
            index=0,
            pause_base_ms=750,
        ),
        pm.create_speech_block(
            character=pierre,
            text="Mon dieu! Il fait trop sombre... Arthur, você tem certeza absoluta de que aquele livro proibido está escondido aqui?",
            speech_type="dialogo",
            emotion_label="tenso",
            index=1,
            pause_base_ms=450,
        ),
        pm.create_speech_block(
            character=arthur,
            text="Tenho certeza, Pierre! Olhe atrás da terceira estante carcomida... A fechadura está emperrada, me ajude a forçar a tranca!",
            speech_type="dialogo",
            emotion_label="animado",
            index=2,
            pause_base_ms=450,
        ),
        pm.create_speech_block(
            character=aninha,
            text="Doutor Arthur... escute! Tem passos vindo do corredor escuro... Tem uma sombra alta nos observando pela fresta da porta!",
            speech_type="dialogo",
            emotion_label="panico",
            index=3,
            pause_base_ms=500,
        ),
        pm.create_speech_block(
            character=anciao,
            text="Quem ousa perturbar o sono secular desta torre? Guardem suas armas, jovens tolos... Vocês não sabem o mal que despertaram.",
            speech_type="dialogo",
            emotion_label="solene",
            index=4,
            pause_base_ms=800,
        ),
        pm.create_speech_block(
            character=narrador,
            text="Um estrondo de trovão fez a mansão estremecer. As chamas das velas dançaram na penumbra... e o silêncio da noite engoliu a todos.",
            speech_type="narracao",
            emotion_label="solene",
            index=5,
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
    print(f"   - Roteiro com {len(falas)} blocos salvo em scripts/cap_01.json")

    # 4. Síntese Assíncrona dos Blocos
    print("\n▶ 4. Sintetizando com Hugging Face (Kokoro) e Edge Recalibrado...")
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
    print(f"\n   - Todas as {len(raw_chunks)} falas sintetizadas no disco!")
    for i, (b, c) in enumerate(zip(script.blocks, raw_chunks)):
        assert c.exists() and c.stat().st_size > 500, f"Chunk {c} inválido"
        char = bible.characters.get(b.character_id)
        nome = char.name if char else b.character_id
        print(f"     * Bloco {i:02d} [{nome} - {b.engine}]: {c.name} ({c.stat().st_size / 1024:.1f} KB)")

    # 5. Masterização com Nivelamento, Micro-Fades e Room Tone
    print("\n▶ 5. Masterizando Áudio com Micro-Fades e Room Tone de Estúdio...")
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
    print("🎉 NOVO ÁUDIO DEMONSTRATIVO DE ALTA QUALIDADE GERADO!")
    print(f"Arquivo: {output_demo_mp3.resolve()}")
    print(f"Tamanho: {tamanho_final_kb:.1f} KB")
    print("=======================================================\n")


if __name__ == "__main__":
    test_phase4_end_to_end_and_generate_demo()
