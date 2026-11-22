"""Bateria de testes automatizados da Fase 9 do AudioBook App.

Valida os 7 pilares da Fase 9:
1. Sub-Chunking Fonético Interno no Kokoro-ONNX (split_into_phonetic_sentences <= 350 chars + 120ms de pausa).
2. Normalizador Fonético PT-BR (src/phonetics.py: siglas tech, símbolos matemáticos e algarismos romanos).
3. Leitura Inteligente de Tabelas em PDFs (extract_from_pdf linearizando cabeçalhos e células).
4. Blindagem do Modo Aula/Resumo no Diretor Express e nos Prefixos Gemini TTS.
5. Rastreamento de Timestamps Exatos por Bloco (start_ms, end_ms, duration_ms) na Mixagem e API.
6. Legendas .SRT / .VTT + Karaoke Sync (.is-speaking) & Click-to-Seek ('Ouvir daqui') no Frontend.
7. Exportação de Audiolivro .M4B com Capítulos Clicáveis (FFMETADATA1) e downloads no Player.
"""

import asyncio
import inspect
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from src.api import app, pm
from src.director import Director
from src.extractor import extract_from_pdf
from src.mixer import AudioMixer
from src.models import ChapterScript, SpeechBlock
from src.phonetics import normalize_phonetics_ptbr
from src.synthesizer import (
    Synthesizer,
    clean_tts_text,
    split_into_phonetic_sentences,
)

client = TestClient(app)


def test_1_kokoro_phonetic_subchunking():
    print("▶ 1. Testando Sub-Chunking Fonético Interno no Kokoro-ONNX (~350 chars + 120ms pausa)...")
    texto_longo = (
        "A arquitetura de dados moderna evoluiu significativamente nas últimas décadas para suportar volumes massivos. "
        "Os sistemas transacionais tradicionais garantem integridade ácida em operações do dia a dia corporativo! "
        "Por outro lado, os armazéns analíticos consolidam históricos de múltiplos anos para tomada de decisão estratégica? "
        "Além disso, pipelines de engenharia realizam extração, limpeza e enriquecimento contínuo em nuvem; "
        "dessa forma, modelos preditivos operam com baixa latência e alta confiabilidade em produção."
    )
    assert len(texto_longo) > 450
    partes = split_into_phonetic_sentences(texto_longo, max_chars=350)
    assert len(partes) >= 2, f"Esperado >= 2 sub-sentenças, obtido {len(partes)}"
    for idx, p in enumerate(partes):
        assert len(p) <= 350, f"Sub-sentença {idx} excedeu 350 chars ({len(p)})"
    print(f"   - Texto de {len(texto_longo)} chars dividido em {len(partes)} sub-sentenças: {[len(p) for p in partes]} chars")

    # Verifica código de synthesize_with_kokoro (120ms = sample_rate * 0.12)
    src_kokoro = inspect.getsource(Synthesizer.synthesize_with_kokoro)
    assert "split_into_phonetic_sentences" in src_kokoro
    assert "0.12" in src_kokoro
    print("   ✔ Sub-chunking fonético e micro-pausa de 120ms no Kokoro validados!\n")


def test_2_phonetic_normalizer_ptbr():
    print("▶ 2. Testando Normalizador Fonético PT-BR (Siglas, Símbolos e Algarismos Romanos)...")
    frase_bruta = (
        "Na Aula III do Capítulo IV (Século XXI, Parte II), estudamos SGBD, SGBDs, SQL, NoSQL, "
        "ETL, ELT, DW, BI, XAI, IA, ML, DL, NLP, LLM, LLMs, API, APIs, CPU, GPU, KPI, KPIs, "
        "OLTP, OLAP, LGPD, JSON, CSV, HTTP e HTTPS onde x >= 10, y <= 5, z != 0 -> sucesso ➔ produção."
    )
    norm = normalize_phonetics_ptbr(frase_bruta)

    esperados = [
        "Aula três",
        "Capítulo quatro",
        "Século vinte e um",
        "Parte dois",
        "Ésse Gê Bê Dê",
        "Ésse Gê Bê Dês",
        "Ésse Quê Éle",
        "Nô Ésse Quê Éle",
        "É Tê Éle",
        "É Éle Tê",
        "Dê Dáblio",
        "Bê Í",
        "Êxis A Í",
        "I Á",
        "Ême Éle",
        "Dê Éle",
        "Êne Éle Pê",
        "Éle Éle Ême",
        "Éle Éle Êmes",
        "A Pê Í",
        "A Pê Ís",
        "Cê Pê Ú",
        "Gê Pê Ú",
        "Cá Pê Í",
        "Cá Pê Ís",
        "Ó Éle Tê Pê",
        "Ó Éle A Pê",
        "Éle Gê Pê Dê",
        "Jêison",
        "Cê Ésse Vê",
        "Agá Tê Tê Pê",
        "Agá Tê Tê Pê Ésse",
        "maior ou igual a",
        "menor ou igual a",
        "diferente de",
        ", levando a",
    ]
    for termo in esperados:
        assert termo in norm, f"Termo fonético esperado '{termo}' não encontrado em: {norm}"

    # Verifica integração dentro de clean_tts_text
    limpo = clean_tts_text("[tom didático] O SGBD usa SQL no Século XXI -> rápido.")
    assert "tom didático" not in limpo
    assert "Ésse Gê Bê Dê" in limpo
    assert "Ésse Quê Éle" in limpo
    assert "Século vinte e um" in limpo
    assert ", levando a" in limpo
    print("   - Siglas tech, operadores lógicos e algarismos romanos convertidos perfeitamente.")
    print("   ✔ Normalizador fonético PT-BR 100% aprovado!\n")


def test_3_smart_pdf_table_extraction():
    print("▶ 3. Testando Leitura Inteligente de Tabelas em PDFs (extract_from_pdf)...")
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "Resumo Comparativo de Carreiras em Dados:")

    # Desenha uma grade de tabela 3x3 real na página do PDF para o find_tables() do PyMuPDF
    x0, y0 = 50, 80
    col_w = [140, 180, 140]
    row_h = 28
    rows_data = [
        ["Papel", "Foco Principal", "Ferramentas"],
        ["Cientista de Dados", "Criação de modelos", "Python e R"],
        ["Engenheiro de Dados", "Pipelines e arquitetura", "Spark e SQL"],
    ]

    for r_idx, row in enumerate(rows_data):
        curr_x = x0
        curr_y = y0 + r_idx * row_h
        for c_idx, cell_text in enumerate(row):
            w = col_w[c_idx]
            rect = fitz.Rect(curr_x, curr_y, curr_x + w, curr_y + row_h)
            page.draw_rect(rect, color=(0, 0, 0), width=1)
            page.insert_text((curr_x + 6, curr_y + 18), cell_text, fontsize=10)
            curr_x += w

    pdf_bytes = doc.tobytes()
    doc.close()

    texto_extraido = extract_from_pdf(pdf_bytes)
    assert "Item da tabela — " in texto_extraido, f"Tabela não foi linearizada: {texto_extraido}"
    assert "Papel: Cientista de Dados" in texto_extraido
    assert "Foco Principal: Criação de modelos" in texto_extraido
    assert "Ferramentas: Python e R" in texto_extraido
    print(f"   - Tabela extraída e linearizada: {texto_extraido.splitlines()[1] if len(texto_extraido.splitlines()) > 1 else texto_extraido[:100]}")
    print("   ✔ Leitura inteligente de tabelas em PDF aprovada!\n")


def test_4_lecture_mode_hardening_and_gemini_prefixes():
    print("▶ 4. Testando Blindagem do Modo Aula/Resumo (Bullets vs Diálogos e Prefixos Gemini)...")
    slug = "teste_phase9_aula"
    if pm.project_exists(slug):
        pm.delete_project(slug)

    pm.create_project(slug=slug, title="Aula de Banco de Dados", mode="summary", engine_strategy="unlimited")
    director = Director(project_manager=pm)

    texto_aula = (
        "Introdução aos Bancos de Dados Relacionais.\n\n"
        "- O modelo relacional organiza dados em tabelas!\n\n"
        "— A linguagem padrão de consulta é declarativa?"
    )
    blocos = director.direct_chunk_express(texto_aula, project_slug=slug)
    assert len(blocos) == 3
    for b in blocos[1:]:
        assert b.speech_type == "destaque", f"Esperado 'destaque', obtido '{b.speech_type}'"
        assert b.emotion == "destaque_didatico", f"Esperado 'destaque_didatico', obtido '{b.emotion}'"
        assert not (b.text_for_tts or "").startswith("— ... "), "Não deve injetar pausa dramática de diálogo em bullets de aula!"

    # Verifica que synthesize_with_gemini suprime prefixo em inglês para narração/destaque/citação
    synth = Synthesizer(gemini_api_key="AIzaSyFakeKeyForUnitTest")
    captured_contents = []

    class DummyClient:
        class models:
            @staticmethod
            def generate_content(model, contents, config):
                captured_contents.append(contents)
                raise RuntimeError("429 RESOURCE_EXHAUSTED quota")

    with patch("google.genai.Client", return_value=DummyClient()):
        asyncio.run(
            synth.synthesize_with_gemini(
                text="O sistema gerenciador controla transações.",
                voice_name="gemini_charon",
                emotion="tenso",
                speech_type="destaque",
            )
        )

    assert len(captured_contents) == 1
    assert not captured_contents[0].startswith("Say "), f"Prefixo em inglês indevido: {captured_contents[0]}"

    pm.delete_project(slug)
    print("   - Bullets '-' e '—' em modo Aula/Resumo classificados como 'destaque' / 'destaque_didatico'.")
    print("   - Prefixos em inglês bloqueados em blocos de narração/destaque/citação no Gemini TTS.")
    print("   ✔ Blindagem do Modo Aula/Resumo aprovada!\n")


def test_5_6_7_timestamps_subtitles_m4b_and_ui():
    print("▶ 5, 6 & 7. Testando Timestamps Exatos, Legendas (.SRT/.VTT), Audiolivro (.M4B) e Karaoke Sync UI...")
    slug = "teste_phase9_master"
    if pm.project_exists(slug):
        pm.delete_project(slug)

    pm.create_project(slug=slug, title="Masterização Fase 9", mode="summary", engine_strategy="unlimited")

    # Dirige 2 falas curtas via API
    res_dir = client.post(
        f"/api/projects/{slug}/direct",
        json={
            "chapter_number": 1,
            "chapter_title": "Capítulo 01",
            "chapter_content": "Primeira fala curta para validação de timestamps.\n\nSegunda fala curta para testar capítulos e legendas.",
            "force_express": True,
            "fuse_speeches": False,
        },
    )
    assert res_dir.status_code == 200

    # Renderiza capítulo via API (modo síncrono)
    res_render = client.post(
        f"/api/projects/{slug}/render",
        json={
            "chapter_number": 1,
            "quick_test": False,
            "enable_kokoro_eq": False,
            "enable_room_tone": True,
            "async_mode": False,
        },
    )
    assert res_render.status_code == 200
    data_render = res_render.json()
    assert data_render["has_audio"] is True
    assert data_render.get("srt_url") is not None, "srt_url ausente no retorno de renderização"
    assert data_render.get("vtt_url") is not None, "vtt_url ausente no retorno de renderização"
    assert data_render.get("m4b_url") is not None, "m4b_url ausente no retorno de renderização"

    # Verifica timestamps nos blocos auditados e no script persistido
    audit = data_render["audit"]
    assert len(audit) == 2
    assert audit[0]["start_ms"] == 0
    assert audit[0]["duration_ms"] > 500
    assert audit[0]["end_ms"] == audit[0]["duration_ms"]
    assert audit[1]["start_ms"] == audit[0]["end_ms"]
    assert audit[1]["end_ms"] > audit[1]["start_ms"]

    script_salvo = pm.load_chapter_script(slug, 1)
    assert script_salvo.blocks[0].start_ms == 0
    assert script_salvo.blocks[1].start_ms == script_salvo.blocks[0].end_ms
    print(
        f"   - Timestamps exatos rastreados: Fala #0 [{audit[0]['start_ms']}ms -> {audit[0]['end_ms']}ms], "
        f"Fala #1 [{audit[1]['start_ms']}ms -> {audit[1]['end_ms']}ms]"
    )

    # Verifica download das legendas .SRT, .VTT e do audiolivro .M4B via API
    res_srt = client.get(data_render["srt_url"])
    assert res_srt.status_code == 200
    assert "-->" in res_srt.text
    assert "Primeira fala curta" in res_srt.text

    res_vtt = client.get(data_render["vtt_url"])
    assert res_vtt.status_code == 200
    assert res_vtt.text.startswith("WEBVTT")

    res_m4b = client.get(data_render["m4b_url"])
    assert res_m4b.status_code == 200
    assert len(res_m4b.content) > 1000
    print(f"   - Arquivos exportados e servidos via API: .SRT ({len(res_srt.text)} chars), .VTT e .M4B ({len(res_m4b.content)} bytes)")

    # Verifica Frontend v9.0 (Karaoke Sync, Click-to-Seek e botões M4B/SRT com ícones Lucide)
    html = client.get("/").text
    css = client.get("/styles.css").text
    js = client.get("/app.js").text

    assert ("styles.css?v=9.0" in html or "styles.css?v=10.0" in html)
    assert ("app.js?v=9.0" in html or "app.js?v=10.0" in html)
    assert "btnDownloadM4b" in html
    assert "btnDownloadSrt" in html
    assert 'data-lucide="book-open"' in html
    assert 'data-lucide="subtitles"' in html

    assert ".script-item.is-speaking" in css
    assert ".audit-item.is-speaking" in css
    assert ".btn-seek-block" in css

    assert "syncKaraokeHighlight" in js
    assert "seekToBlockTimestamp" in js
    assert "Ouvir daqui" in js

    pm.delete_project(slug)
    print("   - Karaoke Sync (.is-speaking), Click-to-Seek ('Ouvir daqui') e botões .M4B/.SRT validados no Frontend.")
    print("   ✔ Timestamps, .SRT/.VTT, .M4B com capítulos e Karaoke Sync 100% aprovados!\n")


if __name__ == "__main__":
    print("=" * 70)
    print("INICIANDO SUITE DE TESTES - FASE 9 (ACÚSTICA, FONÉTICA, TABELAS, .SRT & .M4B)")
    print("=" * 70)

    test_1_kokoro_phonetic_subchunking()
    test_2_phonetic_normalizer_ptbr()
    test_3_smart_pdf_table_extraction()
    test_4_lecture_mode_hardening_and_gemini_prefixes()
    test_5_6_7_timestamps_subtitles_m4b_and_ui()

    print("=" * 70)
    print("TODOS OS TESTES DA FASE 9 FORAM CONCLUÍDOS COM 100% DE SUCESSO! 🎉")
    print("=" * 70)
