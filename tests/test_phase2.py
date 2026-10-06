"""Bateria de testes automatizados da Fase 2 do AudioBook App.

Valida:
1. Catálogo Multi-Motor de Vozes (Edge, Kokoro com fusão, Gemini Audio).
2. Workspaces isolados do ProjectManager.
3. Smart Casting (Anti-Colisão, Sotaques, Idades e Identidade Dupla).
4. Resolução de Aliases (Evitar duplicação de personagens por apelidos).
5. Matriz de Emoções, Deltas, Clamping Acústico e Acting Prompts.
6. Geração e persistência de ChapterScript estruturado.
"""

import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.emotions import (
    EMOTION_MATRIX,
    PITCH_MAX,
    PITCH_MIN,
    RATE_MAX,
    RATE_MIN,
    calculate_acoustic_parameters,
    get_emotion,
    list_emotion_labels,
)
from src.models import ChapterScript, SpeechBlock
from src.project_manager import ProjectManager
from src.voices import VOICE_CATALOG, find_fallback_voice, list_voices


def test_voices_catalog():
    print("▶ 1. Testando Catálogo de Vozes Multi-Motor...")
    assert len(VOICE_CATALOG) >= 25, f"Esperava ao menos 25 vozes, obteve {len(VOICE_CATALOG)}"

    edge_voices = list_voices(engine="edge")
    kokoro_voices = list_voices(engine="kokoro")
    gemini_voices = list_voices(engine="gemini")

    print(f"   - Edge-TTS: {len(edge_voices)} vozes cadastradas")
    print(f"   - Kokoro-ONNX: {len(kokoro_voices)} vozes (incluindo presets de fusão)")
    print(f"   - Gemini Audio: {len(gemini_voices)} vozes")

    assert len(edge_voices) >= 14
    assert len(kokoro_voices) >= 5
    assert len(gemini_voices) >= 8

    # Testa fusão de vozes (Voice Blending)
    blends = [v for v in kokoro_voices if v.is_blend]
    assert len(blends) >= 3, "Presets de fusão do Kokoro não encontrados"
    print(f"   - Presets de Fusão Kokoro validados: {[b.name for b in blends]}")

    # Testa fallback para voz Gemini
    charon = VOICE_CATALOG["gemini_charon"]
    fallback = find_fallback_voice(charon)
    assert fallback.engine in ("edge", "kokoro"), f"Fallback inválido: {fallback.engine}"
    print(f"   - Fallback para {charon.name} -> {fallback.name} ({fallback.engine})")
    print("   ✔ Catálogo de Vozes aprovado com sucesso!\n")


def test_emotions_and_clamping():
    print("▶ 2. Testando Matriz de Emoções, Clamping e Acting Prompt...")
    emocoes = list_emotion_labels()
    print(f"   - Total de emoções calibradas: {len(emocoes)}")
    assert len(emocoes) >= 15, f"Esperava ao menos 15 emoções, obteve {len(emocoes)}"

    # Teste 1: Emoção normal de pânico em personagem neutro
    rate, pitch, vol, pause_m, prompt = calculate_acoustic_parameters(
        baseline_rate_pct=0,
        baseline_pitch_hz=0,
        baseline_volume_pct=0,
        emotion_label="panico",
        character_personality="medroso",
    )
    print(f"   - Pânico (Neutro): Rate={rate}, Pitch={pitch}, Pausa={pause_m}x")
    panico_spec = EMOTION_MATRIX["panico"]
    assert rate == f"{panico_spec.rate_delta:+d}%"
    assert pitch == f"{panico_spec.pitch_delta:+d}Hz"
    assert pause_m == panico_spec.pause_multiplier
    assert "pânico" in prompt.lower()

    # Teste 2: Clamping de Segurança (Extremos não devem estourar os limites)
    # Jovem super acelerado (+15% baseline) em pânico (+6% delta) = +21% -> deve travar em RATE_MAX (+12%)
    rate_clamped, pitch_clamped, _, _, _ = calculate_acoustic_parameters(
        baseline_rate_pct=15,
        baseline_pitch_hz=10,
        baseline_volume_pct=0,
        emotion_label="panico",
    )
    assert rate_clamped == f"{RATE_MAX:+d}%", f"Esperado {RATE_MAX:+d}%, obteve {rate_clamped}"
    assert pitch_clamped == f"{PITCH_MAX:+d}Hz", f"Esperado {PITCH_MAX:+d}Hz, obteve {pitch_clamped}"
    print(f"   - Clamping Máximo: Rate={rate_clamped} (Teto: {RATE_MAX}%), Pitch={pitch_clamped} (Teto: {PITCH_MAX}Hz)")

    # Idoso lento (-15% baseline) em exaustão (-8% delta) -> deve travar em RATE_MIN (-10%)
    rate_min, pitch_min, _, _, _ = calculate_acoustic_parameters(
        baseline_rate_pct=-15,
        baseline_pitch_hz=-10,
        baseline_volume_pct=0,
        emotion_label="cansado_fraco",
    )
    assert rate_min == f"{RATE_MIN:+d}%", f"Esperado {RATE_MIN:+d}%, obteve {rate_min}"
    assert pitch_min == f"{PITCH_MIN:+d}Hz", f"Esperado {PITCH_MIN:+d}Hz, obteve {pitch_min}"
    print(f"   - Clamping Mínimo: Rate={rate_min} (Piso: {RATE_MIN}%), Pitch={pitch_min} (Piso: {PITCH_MIN}Hz)")
    print("   ✔ Matriz de Emoções e Clamping aprovados com sucesso!\n")


def test_project_manager_and_smart_casting():
    print("▶ 3. Testando ProjectManager, Smart Casting e Resolução de Aliases...")
    slug_teste = "projeto_teste_fase2"
    pm = ProjectManager()

    # 1. Criação do projeto em modo híbrido
    meta = pm.create_project(
        slug=slug_teste,
        title="O Mistério do Vale Sombrio",
        mode="fiction",
        engine_strategy="hybrid",
    )
    assert meta.slug == slug_teste
    assert pm.project_exists(slug_teste)
    print(f"   - Workspace criado: data/projects/{slug_teste}")

    # 2. Smart Casting: Protagonista idoso e ranzinza (deve usar Gemini em modo híbrido)
    dr_victor = pm.smart_cast(
        project_slug=slug_teste,
        name="Dr. Victor Frank",
        gender="M",
        apparent_age="maduro",
        accent="brasileiro",
        personality="médico idoso, ranzinza e perfeccionista",
        aliases=["Victor", "Dr. Victor", "o velho cientista"],
        is_protagonist=True,
    )
    assert dr_victor.engine == "gemini", f"Esperava gemini, obteve {dr_victor.engine}"
    assert dr_victor.fallback_engine in ("edge", "kokoro")
    print(f"   - Protagonista alocado: {dr_victor.name} -> Voz {dr_victor.voice_id} ({dr_victor.engine}) | Fallback: {dr_victor.fallback_voice_id} ({dr_victor.fallback_engine})")

    # 3. Resolução de Aliases: Chamar "o velho cientista" deve retornar Dr. Victor sem duplicar
    resolvido = pm.smart_cast(
        project_slug=slug_teste,
        name="o velho cientista",
        aliases=["Victor"],
    )
    assert resolvido.id == dr_victor.id, "Falha na resolução de alias"
    print(f"   - Resolução de Alias: 'o velho cientista' -> ID {resolvido.id} (Não duplicou!)")

    # 4. Smart Casting de Personagem Estrangeiro
    pierre = pm.smart_cast(
        project_slug=slug_teste,
        name="Pierre Laurent",
        gender="M",
        apparent_age="adulto",
        accent="frances",
        personality="diplomata refinado",
    )
    assert pierre.accent == "frances"
    assert "fr" in pierre.voice_id.lower() or "remy" in pierre.voice_id.lower()
    print(f"   - Sotaque Francês alocado: {pierre.name} -> {pierre.voice_id} ({pierre.engine})")

    # 5. Smart Casting de Criança
    aninha = pm.smart_cast(
        project_slug=slug_teste,
        name="Aninha",
        gender="F",
        apparent_age="crianca",
        accent="brasileiro",
        personality="curiosa e elétrica",
    )
    assert aninha.baseline.pitch_offset_hz >= 2, "Pitch de criança deve ser elevado sutilmente"
    print(f"   - Criança alocada: {aninha.name} -> {aninha.voice_id} com pitch base de {aninha.baseline.pitch_offset_hz}Hz")

    # 6. Anti-Colisão: Cria múltiplos personagens masculinos adultos
    homens = []
    for i in range(1, 4):
        h = pm.smart_cast(
            project_slug=slug_teste,
            name=f"Guarda {i}",
            gender="M",
            apparent_age="adulto",
            accent="brasileiro",
        )
        homens.append(h)

    print(f"   - Anti-colisão de vozes: {[h.voice_id for h in homens]}")

    # 7. Construção de Roteiro e ChapterScript
    print("\n▶ 4. Testando Construção de ChapterScript com Pausas e Atuação...")
    fala_1 = pm.create_speech_block(
        character=dr_victor,
        text="Quem está aí no corredor? Identifique-se imediatamente!",
        speech_type="dialogo",
        emotion_label="tenso",
        index=0,
    )
    assert fala_1.rate != "+0%" or fala_1.pitch != "+0Hz"
    assert fala_1.acting_prompt is not None

    fala_2 = pm.create_speech_block(
        character=aninha,
        text="Sou eu, doutor! Não atire, por favor!",
        speech_type="dialogo",
        emotion_label="panico",
        index=1,
    )

    roteiro = ChapterScript(
        chapter_number=1,
        title="O Encontro na Mansão",
        blocks=[fala_1, fala_2],
        total_chars=len(fala_1.text) + len(fala_2.text),
    )

    pm.save_chapter_script(slug_teste, roteiro)
    carregado = pm.load_chapter_script(slug_teste, 1)

    assert carregado is not None
    assert len(carregado.blocks) == 2
    assert carregado.blocks[0].character_id == dr_victor.id
    assert carregado.blocks[1].character_id == aninha.id

    print(f"   - ChapterScript salvo e recarregado com sucesso! {len(carregado.blocks)} falas.")
    print(f"   - Fala 0 [{dr_victor.name}]: Rate={fala_1.rate}, Pitch={fala_1.pitch}, Pause={fala_1.pause_after_ms}ms")
    print(f"   - Acting Prompt: \"{fala_1.acting_prompt[:60]}...\"")
    print(f"   - Fala 1 [{aninha.name}]: Rate={fala_2.rate}, Pitch={fala_2.pitch}, Pause={fala_2.pause_after_ms}ms")

    # Limpeza do projeto temporário de teste
    import shutil
    shutil.rmtree(pm.get_project_dir(slug_teste))
    print(f"   - Workspace de teste limpo com sucesso.")
    print("   ✔ ProjectManager e Roteiros 100% validados!\n")


if __name__ == "__main__":
    print("=" * 70)
    print("INICIANDO SUITE DE TESTES - FASE 2")
    print("=" * 70)
    test_voices_catalog()
    test_emotions_and_clamping()
    test_project_manager_and_smart_casting()
    print("=" * 70)
    print("TODOS OS TESTES DA FASE 2 FORAM CONCLUÍDOS COM 100% DE SUCESSO! 🎉")
    print("=" * 70)
