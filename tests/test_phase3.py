"""Bateria de testes automatizados da Fase 3 do AudioBook App.

Valida:
1. Algoritmo de Cura de Texto (desfazer hífens, remover números de página, unir linhas quebradas).
2. Detector de Capítulos e Chunker Semântico.
3. Validador de Integridade Léxica (taxa >98% aprovando pontuações dramáticas e reprovando omissões).
4. Prompt Builder com Janela Deslizante de Contexto.
5. Modo Express/Determinístico (Direção 100% offline sem custos de API).
"""

import shutil
import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.director import (
    DirectedSpeech,
    Director,
    build_director_prompt,
    validate_lexical_fidelity,
)
from src.extractor import chunk_chapter, cure_text, detect_chapters
from src.models import CharacterBible, ProjectMetadata
from src.project_manager import ProjectManager


def test_text_curing():
    print("▶ 1. Testando Algoritmo de Cura de Texto (PDFs e Quebras Artificiais)...")

    texto_sujo = """
    Capítulo 1: O Enigma da Montanha.
    
    12
    
    A economia comportamental revelou que as decisões hu-
    manas raramente seguem a lógica estrita da utili-
    dade esperada.
    
    Página 13 de 150
    
    Na prática, fatores psicológicos e heurísticas de jul-
    gamento moldam as escolhas sob incerteza.
    
    — Quem está aí? — gritou o viajante.
    — Sou apenas um pastor — respondeu o velho.
    """

    texto_limpo = cure_text(texto_sujo)
    paragrafos = texto_limpo.split("\n\n")

    print(f"   - Total de parágrafos reconstruídos: {len(paragrafos)}")
    # Verifica que hifenizações foram coladas
    assert "humanas" in texto_limpo, "Falha ao colar 'hu-\\nmanas'"
    assert "utilidade" in texto_limpo, "Falha ao colar 'utili-\\ndade'"
    assert "julgamento" in texto_limpo, "Falha ao colar 'jul-\\ngamento'"

    # Verifica que números de página foram excluídos
    assert "12" not in texto_limpo.split("\n"), "Número de página 12 não foi removido"
    assert "Página 13 de 150" not in texto_limpo, "Rodapé de página não foi removido"

    # Verifica travessões de diálogo
    assert "— Quem está aí? — gritou o viajante." in texto_limpo
    assert "— Sou apenas um pastor — respondeu o velho." in texto_limpo

    print("   ✔ Algoritmo de cura de texto aprovado com sucesso!\n")


def test_chapter_detection_and_chunker():
    print("▶ 2. Testando Detector de Capítulos e Chunker Semântico...")

    texto_livro = """
Capítulo 1: O Início da Jornada

O sol despontava tímido sobre as colinas da velha fazenda.
As árvores farfalhavam com o vento fresco da manhã.

Arthur caminhava com passos firmes em direção ao moinho abandonado.
Ele sabia que o tempo estava correndo contra todos.

Capítulo 2: O Segredo Revelado

A porta rangeu quando Arthur empurrou a pesada madeira carcomida.
No centro da sala, uma caixa de ferro repousava sobre a mesa de pedra.
    """

    capitulos = detect_chapters(cure_text(texto_livro))
    assert len(capitulos) == 2, f"Esperava 2 capítulos, obteve {len(capitulos)}"
    print(f"   - Capítulos detectados: {[c['title'] for c in capitulos]}")

    assert "Capítulo 1" in capitulos[0]["title"]
    assert "Capítulo 2" in capitulos[1]["title"]

    # Testa chunker no capítulo 1
    chunks = chunk_chapter(capitulos[0]["content"], max_paragraphs=2)
    assert len(chunks) >= 2, "Chunker deveria ter dividido em mais de um lote"
    print(f"   - Capítulo 1 dividido em {len(chunks)} lotes (chunks)")
    print("   ✔ Detector de Capítulos e Chunker aprovados com sucesso!\n")


def test_lexical_integrity_validator():
    print("▶ 3. Testando Validador de Integridade Léxica...")

    texto_original = "Arthur olhou para o horizonte distante e disse que não voltaria atrás."

    # Caso 1: Diretor alterou pontuação para respiração dramática (DEVE APROVAR)
    speeches_com_atuacao = [
        DirectedSpeech(
            speaker="narrador",
            speech_type="narracao",
            emotion="neutro",
            text="Arthur olhou para o horizonte distante... e disse:",
        ),
        DirectedSpeech(
            speaker="Arthur",
            speech_type="dialogo",
            emotion="tenso",
            text="Que não voltaria atrás!",
        ),
    ]

    aprovado_1, ratio_1, msg_1 = validate_lexical_fidelity(texto_original, speeches_com_atuacao)
    print(f"   - Teste 1 (Pontuação expressiva): {msg_1} -> Aprovado? {aprovado_1}")
    assert aprovado_1, f"Deveria ter aprovado pontuações expressivas: {msg_1}"

    # Caso 2: LLM resumiu e omitiu frases inteiras (DEVE REPROVAR)
    speeches_resumidas = [
        DirectedSpeech(
            speaker="narrador",
            speech_type="narracao",
            emotion="neutro",
            text="Arthur olhou e disse que continuaria.",  # 'horizonte distante' e 'não voltaria atrás' sumiram
        )
    ]

    aprovado_2, ratio_2, msg_2 = validate_lexical_fidelity(texto_original, speeches_resumidas)
    print(f"   - Teste 2 (Omissão/Resumo): {msg_2} -> Aprovado? {aprovado_2}")
    assert not aprovado_2, "Deveria ter reprovado omissão grave de palavras"
    assert ratio_2 < 0.90

    print("   ✔ Validador de Integridade Léxica aprovado com sucesso!\n")


def test_prompt_builder_and_sliding_window():
    print("▶ 4. Testando Prompt Builder com Janela Deslizante...")

    pm = ProjectManager()
    slug_teste = "projeto_prompt_test"
    pm.create_project(slug=slug_teste, title="Teste de Prompt", mode="fiction")
    meta = pm.load_metadata(slug_teste)
    bible = pm.load_character_bible(slug_teste)

    # Adiciona um personagem com alias
    pm.smart_cast(
        slug_teste,
        name="Arthur Pendelton",
        gender="M",
        apparent_age="adulto",
        aliases=["Arthur", "o cavaleiro"],
    )
    bible = pm.load_character_bible(slug_teste)

    # Simula falas anteriores para a janela deslizante
    falas_anteriores = [
        pm.create_speech_block(
            character=bible.characters["narrador"],
            text="A noite caiu rapidamente.",
            speech_type="narracao",
            index=0,
        ),
        pm.create_speech_block(
            character=bible.characters["arthur_pendelton"],
            text="Temos que acender a fogueira agora.",
            speech_type="dialogo",
            index=1,
        ),
    ]

    prompt = build_director_prompt(
        chunk_text="— Concordo — sussurrou Helena.",
        project_metadata=meta,
        character_bible=bible,
        previous_speeches=falas_anteriores,
    )

    assert "Arthur Pendelton" in prompt
    assert "Temos que acender a fogueira agora" in prompt, "Janela deslizante não foi incluída no prompt"
    assert "REGRA DE OURO DE INTEGRIDADE" in prompt

    print("   - Janela deslizante e Bíblia injetadas corretamente no prompt!")
    shutil.rmtree(pm.get_project_dir(slug_teste))
    print("   ✔ Prompt Builder aprovado com sucesso!\n")


def test_express_mode_deterministic():
    print("▶ 5. Testando Modo Express/Determinístico (100% Offline / Sem LLM)...")

    pm = ProjectManager()
    slug_teste = "projeto_express_test"
    pm.create_project(slug=slug_teste, title="Resumo Express", mode="summary")

    director = Director(project_manager=pm)

    texto_capitulo = """
    A inteligência artificial transformou radicalmente a produção de mídia em 2026.
    
    — Essa tecnologia veio para ficar — declarou o pesquisador durante a conferência.
    
    "O futuro da síntese de voz está na interpretação dramática", conclui o artigo.
    """

    script = director.direct_chapter(
        project_slug=slug_teste,
        chapter_number=1,
        chapter_title="Introdução à Síntese Vocal",
        chapter_content=cure_text(texto_capitulo),
        force_express=True,
    )

    assert script is not None
    assert len(script.blocks) == 3
    print(f"   - ChapterScript gerado em Modo Express: {len(script.blocks)} falas.")

    fala_0 = script.blocks[0]
    fala_1 = script.blocks[1]
    fala_2 = script.blocks[2]

    assert fala_0.speech_type == "narracao"
    assert fala_1.speech_type == "dialogo"
    assert fala_2.speech_type == "citacao"

    print(f"   - Bloco 0: [{fala_0.speech_type}] \"{fala_0.text[:40]}...\" (Pausa: {fala_0.pause_after_ms}ms)")
    print(f"   - Bloco 1: [{fala_1.speech_type}] \"{fala_1.text[:40]}...\" (Pausa: {fala_1.pause_after_ms}ms)")
    print(f"   - Bloco 2: [{fala_2.speech_type}] \"{fala_2.text[:40]}...\" (Pausa: {fala_2.pause_after_ms}ms)")

    # Confere persistência no disco em data/projects/projeto_express_test/scripts/cap_01.json
    script_recuperado = pm.load_chapter_script(slug_teste, 1)
    assert script_recuperado is not None
    assert len(script_recuperado.blocks) == 3

    print(f"   - Script persistido e recarregado de scripts/cap_01.json com sucesso!")
    shutil.rmtree(pm.get_project_dir(slug_teste))
    print("   ✔ Modo Express Determinístico 100% validado!\n")


if __name__ == "__main__":
    print("=" * 70)
    print("INICIANDO SUITE DE TESTES - FASE 3")
    print("=" * 70)
    test_text_curing()
    test_chapter_detection_and_chunker()
    test_lexical_integrity_validator()
    test_prompt_builder_and_sliding_window()
    test_express_mode_deterministic()
    print("=" * 70)
    print("TODOS OS TESTES DA FASE 3 FORAM CONCLUÍDOS COM 100% DE SUCESSO! 🎉")
    print("=" * 70)
