"""Bateria de testes automatizados da Fase 10 do AudioBook App.

Valida todos os pilares da Fase 10:
1. Correção de Edição Inline (sincronização text <-> text_for_tts) + Re-síntese cirúrgica de bloco único.
2. Cura Avançada de PDFs Acadêmicos (remoção automática de cabeçalhos/rodapés repetitivos, \u0000 e aviso de sumário).
3. Motor Fonético Matemático & Estatístico PT-BR (fatoriais, P(A|B), conjuntos) preservando exclamações comuns.
4. Sessão ONNX Otimizada no Kokoro (DirectML/ROCm/CUDA/CPU) e telemetria em /api/status.
5. Direção Cênica Assíncrona com Barra de Progresso em /api/projects/{slug}/direct/status.
6. Voice Studio Lab: Clonagem Acústica Zero-Shot (F0 Hz, Spectral Centroid, Blend Homogêneo) e DELETE /api/voices/{id}.
7. Frontend v10.0 (botões Lucide, barra de progresso do Diretor, modal de clonagem e botão Sintetizar fala).
"""

import io
import inspect
import sys
import time
from pathlib import Path

import numpy as np
from pydub import AudioSegment

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from src.api import app, pm
from src.extractor import cure_text, extract_from_pdf
from src.models import ChapterScript, SpeechBlock
from src.phonetics import normalize_phonetics_ptbr
from src.synthesizer import Synthesizer
from src.voices import VOICE_CATALOG, validate_same_gender_blend

client = TestClient(app)


def test_1_inline_edit_sync_and_single_block_resynthesis():
    print("▶ 1. Testando Sincronização de Edição Inline (text <-> text_for_tts) e Re-síntese de Bloco Único...")
    slug = "teste_phase10_block_sync"
    if pm.project_exists(slug):
        pm.delete_project(slug)

    pm.create_project(slug=slug, title="Teste Bloco Único", mode="summary", engine_strategy="unlimited")
    script = ChapterScript(
        chapter_number=1,
        title="Capítulo 01",
        blocks=[
            SpeechBlock(
                index=0,
                character_id="narrador",
                speech_type="narracao",
                text="Texto original que será substituído.",
                text_for_tts="Texto original antigo na memória do TTS.",
                emotion="neutro",
                pause_after_ms=300,
                engine="kokoro",
                voice_id="kokoro_alex",
            ),
        ],
    )
    pm.save_chapter_script(slug, script)

    # Cria cache falso dentro da subpasta temp/cap_01 para validar remoção recursiva
    temp_cap = pm.get_project_dir(slug) / "temp" / "cap_01"
    temp_cap.mkdir(parents=True, exist_ok=True)
    cache_antigo = temp_cap / "block_0000_kokoro_alex.mp3"
    cache_antigo.write_bytes(b"stale-cache")
    assert cache_antigo.exists()

    # Edita apenas `text` via PUT (sem enviar `text_for_tts`)
    novo_texto = "Novo texto editado pelo usuário na Timeline."
    res_put = client.put(
        f"/api/projects/{slug}/script/1/blocks/0",
        json={"text": novo_texto},
    )
    assert res_put.status_code == 200, res_put.text
    bloco_att = res_put.json()["block"]
    assert bloco_att["text"] == novo_texto
    assert bloco_att["text_for_tts"] == novo_texto, "text_for_tts não foi sincronizado ao editar text!"
    assert not cache_antigo.exists(), "Cache em temp/cap_01 não foi purgado!"

    # Testa o novo endpoint de re-síntese cirúrgica de bloco único
    res_synth = client.post(f"/api/projects/{slug}/script/1/blocks/0/synthesize")
    assert res_synth.status_code == 200, res_synth.text
    data_synth = res_synth.json()
    assert data_synth["success"] is True
    assert data_synth["audio_url"] == f"/api/audio/projects/{slug}/block/1/0"
    assert data_synth["block"]["duration_ms"] > 200

    res_audio = client.get(data_synth["audio_url"])
    assert res_audio.status_code == 200
    assert len(res_audio.content) > 1000

    pm.delete_project(slug)
    print("   - Edição inline sincronizou text <-> text_for_tts e purgou cache em temp/cap_01.")
    print("   - Endpoint cirúrgico /synthesize gerou e serviu MP3 individual em 1 passo.")
    print("   ✔ Edição inline e re-síntese de bloco único 100% aprovadas!\n")


def test_2_advanced_pdf_header_footer_and_null_byte_cure():
    print("▶ 2. Testando Cura Avançada de PDFs Acadêmicos (Cabeçalhos Repetidos, \\u0000 e Sumário)...")
    import fitz

    doc = fitz.open()
    for pag_num in range(1, 5):
        page = doc.new_page(width=595, height=842)
        conteudo = (
            "FEE0242 — UNICAMP | INTRODUÇÃO AO DATA SCIENCE\n"
            f"AULA {pag_num} — GUIA MESTRE\n"
            f"Neste tópico {pag_num}, explicamos como modelos probabilísticos avaliam riscos reais.\n"
            f"Página {pag_num} de 4\n"
            "Especialização em Data Science — Unicamp\n"
        )
        page.insert_text((50, 60), conteudo, fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()

    texto_pdf = extract_from_pdf(pdf_bytes)
    assert "FEE0242" not in texto_pdf, f"Cabeçalho repetido permaneceu: {texto_pdf}"
    assert "Especialização em Data Science — Unicamp" not in texto_pdf, f"Rodapé repetido permaneceu: {texto_pdf}"
    assert "modelos probabilísticos avaliam riscos reais" in texto_pdf

    # Valida cure_text contra byte nulo (\u0000) e aviso automático do Word
    sujo = (
        "Título da Aula\x00 sobre Ciência de Dados.\n\n"
        "Nota sobre o Sumário: O campo acima será preenchido e formatado automaticamente quando este arquivo for aberto no Microsoft Word ou Google Docs.\n\n"
        "Conteúdo real permanece intacto."
    )
    limpo = cure_text(sujo)
    assert "\x00" not in limpo
    assert "Nota sobre o Sumário" not in limpo
    assert "Conteúdo real permanece intacto" in limpo

    print("   - Cabeçalhos e rodapés institucionais removidos automaticamente das páginas.")
    print("   - Caracteres nulos (\\u0000) e aviso automático de sumário higienizados.")
    print("   ✔ Cura avançada de PDFs acadêmicos aprovada!\n")


def test_3_math_and_statistics_phonetic_normalizer():
    print("▶ 3. Testando Motor Fonético Matemático & Estatístico PT-BR...")
    formula_texto = (
        "P(A|B) = P(A ∩ B) / P(B). Já P(A ∪ B) usa união e A^c indica complementar. "
        "Na combinatória, 5! = 5 · 4 · 3 · 2 · 1 e A(n, k) = n! / (n - k)! com complexidade O(n!)! "
        "Excelente aula! Muita atenção! Parabéns a todos!"
    )
    norm = normalize_phonetics_ptbr(formula_texto)

    esperados = [
        "Pê de A dado B",
        "Pê de A interseção B",
        "Pê de A união B",
        "A complementar",
        "5 fatorial",
        "vezes",
        "êne fatorial",
        "êne menos cá fatorial",
        "Ó de êne fatorial",
    ]
    for e in esperados:
        assert e in norm, f"Esperado '{e}' em: {norm}"

    # Garante que exclamações normais do português não foram transformadas em 'fatorial'
    assert "Excelente aula!" in norm, f"Exclamação comum alterada indevidamente: {norm}"
    assert "Muita atenção!" in norm
    assert "Parabéns a todos!" in norm
    assert "aula fatorial" not in norm
    assert "todos fatorial" not in norm

    # Operadores de conjuntos e matemáticos unicode
    unicode_ops = normalize_phonetics_ptbr("Se x ∈ A e y ∉ B com A ⊂ C, √9 = 3, ∑x ≤ ∞.")
    assert "pertence a" in unicode_ops
    assert "não pertence a" in unicode_ops
    assert "contido em" in unicode_ops
    assert "raiz quadrada de" in unicode_ops
    assert "somatório" in unicode_ops
    assert "menor ou igual a" in unicode_ops
    assert "infinito" in unicode_ops

    print("   - Fatoriais, probabilidade condicional e conjuntos convertidos sem afetar exclamações comuns.")
    print("   ✔ Motor fonético matemático e estatístico 100% aprovado!\n")


def test_4_onnx_session_optimization_and_status():
    print("▶ 4. Testando Sessão ONNX Otimizada e Status de Hardware em /api/status...")
    src_kokoro_init = inspect.getsource(Synthesizer._get_kokoro_model)
    assert "ORT_ENABLE_ALL" in src_kokoro_init
    assert "DmlExecutionProvider" in src_kokoro_init
    assert "Kokoro.from_session" in src_kokoro_init

    res_status = client.get("/api/status")
    assert res_status.status_code == 200
    st = res_status.json()
    assert "onnx_provider" in st
    assert "custom_voices_count" in st

    # Testa carregamento real da sessão Kokoro otimizada
    synth = Synthesizer()
    kokoro = synth._get_kokoro_model()
    assert kokoro is not None
    assert synth.active_onnx_provider is not None

    print(f"   - /api/status -> onnx_provider={st['onnx_provider']}, active={synth.active_onnx_provider}")
    print("   ✔ Sessão ONNX otimizada e status de hardware aprovados!\n")


def test_5_async_direction_with_progress():
    print("▶ 5. Testando Direção Cênica Assíncrona com Progresso (/direct + /direct/status)...")
    slug = "teste_phase10_async_dir"
    if pm.project_exists(slug):
        pm.delete_project(slug)

    pm.create_project(slug=slug, title="Direção Assíncrona", mode="summary", engine_strategy="unlimited")

    paragrafos = [
        f"Parágrafo didático número {i}: explicando engenharia de dados em escala corporativa com múltiplos lotes."
        for i in range(1, 16)
    ]
    texto_grande = "\n\n".join(paragrafos)

    with TestClient(app) as async_client:
        res_start = async_client.post(
            f"/api/projects/{slug}/direct",
            json={
                "chapter_number": 1,
                "chapter_title": "Capítulo Longo",
                "chapter_content": texto_grande,
                "force_express": True,
                "fuse_speeches": True,
                "async_mode": True,
            },
        )
        assert res_start.status_code == 200, res_start.text
        d = res_start.json()
        assert d["status"] == "running"
        assert d["total_chunks"] >= 2

        # Polling até completar
        final_job = None
        for _ in range(40):
            st_res = async_client.get(f"/api/projects/{slug}/direct/status")
            assert st_res.status_code == 200
            job = st_res.json()
            if job.get("status") in ("completed", "error"):
                final_job = job
                break
            time.sleep(0.1)

    assert final_job is not None and final_job["status"] == "completed", f"Job não finalizou: {final_job}"
    assert final_job["percent"] == 100
    assert final_job["result"]["success"] is True
    assert len(final_job["result"]["script"]["blocks"]) >= 1

    pm.delete_project(slug)
    print(f"   - Direção assíncrona executou {d['total_chunks']} lotes e retornou roteiro via /direct/status.")
    print("   ✔ Direção Cênica assíncrona com progresso aprovada!\n")


def _make_synthetic_voice_wav(f0_hz: float = 125.0, duration_sec: float = 1.2) -> bytes:
    """Gera um WAV sintético rico em harmônicos com F0 conhecida para testar o analisador DSP."""
    sr = 24000
    t = np.linspace(0.0, duration_sec, int(sr * duration_sec), endpoint=False, dtype=np.float32)
    sig = (
        0.55 * np.sin(2.0 * np.pi * f0_hz * t)
        + 0.25 * np.sin(2.0 * np.pi * (2.0 * f0_hz) * t)
        + 0.12 * np.sin(2.0 * np.pi * (3.0 * f0_hz) * t)
    )
    pcm = (np.clip(sig, -1.0, 1.0) * 32767.0).astype(np.int16)
    seg = AudioSegment(pcm.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    buf = io.BytesIO()
    seg.export(buf, format="wav")
    return buf.getvalue()


def test_6_and_7_voice_studio_lab_cloning_and_ui_v10():
    print("▶ 6 & 7. Testando Voice Studio Lab (Clonagem Acústica Zero-Shot) e Frontend v10.0...")
    wav_bytes = _make_synthetic_voice_wav(f0_hz=125.0, duration_sec=1.2)

    res_clone = client.post(
        "/api/voices/clone",
        data={"name": "Professor Teste F10"},
        files={"file": ("ref_prof.wav", wav_bytes, "audio/wav")},
    )
    assert res_clone.status_code == 200, res_clone.text
    clone_data = res_clone.json()
    assert clone_data["success"] is True

    voz = clone_data["voice"]
    tel = clone_data["telemetry"]
    vid = voz["id"]
    assert vid.startswith("clone_")
    assert tel["gender"] == "M", f"Esperado M para F0~125Hz, obtido {tel}"
    assert 115.0 <= tel["f0_hz"] <= 135.0, f"F0 esperada ~125Hz, obtido {tel['f0_hz']}"
    assert validate_same_gender_blend(tel["blend_recipe"]) is True
    assert abs(sum(tel["blend_recipe"].values()) - 1.0) <= 0.03
    assert clone_data["preview_url"] is not None

    # Confirma presença no catálogo /api/voices
    voices_list = client.get("/api/voices").json()["voices"]
    assert any(v["id"] == vid and v.get("is_custom") is True for v in voices_list)

    # Remove voz clonada via DELETE e verifica limpeza
    res_del = client.delete(f"/api/voices/{vid}")
    assert res_del.status_code == 200
    assert vid not in VOICE_CATALOG

    # Verifica assets v10.0 do Frontend
    html = client.get("/").text
    css = client.get("/styles.css").text
    js = client.get("/app.js").text

    assert "styles.css?v=10.0" in html
    assert "app.js?v=10.0" in html
    assert "btnOpenVoiceCloneModal" in html
    assert "directorProgressWrapper" in html
    assert "voiceCloneModal" in html
    assert ".btn-resynth-block" in css
    assert ".telemetry-panel" in css
    assert "synthesizeSingleBlock" in js
    assert "/api/voices/clone" in js
    assert "/direct/status" in js

    print(f"   - Voice Studio Lab: F0 detectada={tel['f0_hz']}Hz, gênero={tel['gender']}, receita={tel['blend_recipe']}")
    print("   - Frontend v10.0 (progresso do Diretor, botão Sintetizar fala e modal Voice Studio Lab) validado!")
    print("   ✔ Voice Studio Lab e Frontend v10.0 100% aprovados!\n")


if __name__ == "__main__":
    print("=" * 70)
    print("INICIANDO SUITE DE TESTES - FASE 10 (VOICE STUDIO LAB, MATEMÁTICA, CURA PDF & GPU/ONNX)")
    print("=" * 70)

    test_1_inline_edit_sync_and_single_block_resynthesis()
    test_2_advanced_pdf_header_footer_and_null_byte_cure()
    test_3_math_and_statistics_phonetic_normalizer()
    test_4_onnx_session_optimization_and_status()
    test_5_async_direction_with_progress()
    test_6_and_7_voice_studio_lab_cloning_and_ui_v10()

    print("=" * 70)
    print("TODOS OS TESTES DA FASE 10 FORAM CONCLUÍDOS COM 100% DE SUCESSO! 🎉")
    print("=" * 70)
