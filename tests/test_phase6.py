"""Bateria de testes automatizados da Fase 6 do AudioBook App.

Valida:
1. API FastAPI (src/api.py) e endpoints REST com TestClient.
2. Status do sistema, checagem de chaves e catálogo de vozes.
3. Extração e contagem de páginas de PDF via upload multipart.
4. Geração e streaming de amostra sonora rápida de 2 segundos.
5. Renderização com auditoria transparente de motores via API.
6. Servidor de arquivos estáticos do frontend (docs/).
"""

import io
import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import fitz  # PyMuPDF
from fastapi.testclient import TestClient
from src.api import app

client = TestClient(app)


def test_api_status_and_voices():
    print("▶ 1. Testando Endpoints de Status e Catálogo de Vozes...")
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert "kokoro_local_ready" in data
    assert "ffmpeg_ready" in data
    print(f"   - Status da API: {data['status']} (Kokoro={data['kokoro_local_ready']}, FFmpeg={data['ffmpeg_ready']})")

    res_voices = client.get("/api/voices")
    assert res_voices.status_code == 200
    voices = res_voices.json()["voices"]
    assert len(voices) >= 20
    print(f"   - Catálogo retornado pela API: {len(voices)} vozes disponíveis.")
    print("   ✔ Endpoints de Status e Catálogo aprovados!\n")


def test_api_project_management():
    print("▶ 2. Testando Gestão de Projetos e Bíblia de Personagens via API...")
    # Lista projetos
    res = client.get("/api/projects")
    assert res.status_code == 200
    assert "projects" in res.json()

    # Cria projeto temporário de teste
    test_slug = "teste_api_phase6"
    res_create = client.post(
        "/api/projects",
        json={
            "slug": test_slug,
            "title": "Projeto Teste API",
            "mode": "fiction",
            "engine_strategy": "unlimited",
        },
    )
    assert res_create.status_code == 200
    print(f"   - Projeto criado com sucesso via API: {test_slug}")

    # Consulta Bíblia do projeto demo_audiobook
    res_bible = client.get("/api/projects/demo_audiobook/bible")
    assert res_bible.status_code == 200
    chars = res_bible.json().get("characters", {})
    assert len(chars) > 0
    print(f"   - Bíblia de Personagens consultada via API: {len(chars)} personagens ativos.")
    print("   ✔ Gestão de Projetos e Bíblia 100% aprovadas!\n")


def test_api_pdf_page_count_and_extract():
    print("▶ 3. Testando Extração de PDF e Contagem de Páginas via Upload Multipart...")
    # Cria PDF em memória com 4 páginas
    doc = fitz.open()
    for i in range(1, 5):
        p = doc.new_page()
        p.insert_text((50, 50), f"Página {i} do livro digital de teste.\nParágrafo de conteúdo da página {i}.")
    pdf_bytes = doc.tobytes()
    doc.close()

    # 1. Teste de contagem de páginas
    files = {"file": ("livro_teste.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    res_count = client.post("/api/extract/pdf/page-count", files=files)
    assert res_count.status_code == 200
    assert res_count.json()["total_pages"] == 4
    print(f"   - Contagem de páginas via API: {res_count.json()['total_pages']} páginas detectadas.")

    # 2. Teste de extração por intervalo (Páginas 2 a 3)
    files_ext = {"file": ("livro_teste.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    data = {"start_page": 2, "end_page": 3, "max_paragraphs": 5}
    res_ext = client.post("/api/extract", files=files_ext, data=data)
    assert res_ext.status_code == 200
    ext_data = res_ext.json()
    assert "Página 2" in ext_data["curated_text"]
    assert "Página 3" in ext_data["curated_text"]
    assert "Página 1" not in ext_data["curated_text"]
    assert "Página 4" not in ext_data["curated_text"]
    print("   - Extração por intervalo (2 a 3) via API: Aprovada com sucesso.")
    print("   ✔ Endpoints de Extração de PDF 100% validados!\n")


def test_api_voice_preview_sample():
    print("▶ 4. Testando Geração e Streaming de Amostra de Voz (Preview 2s)...")
    res = client.post(
        "/api/voices/preview",
        json={"voice_id": "edge_antonio", "sample_text": "Amostra rápida de voz."},
    )
    assert res.status_code == 200
    data = res.json()
    assert "audio_url" in data
    print(f"   - Amostra gerada via API: {data['audio_url']}")

    # Testa streaming do áudio gerado
    res_audio = client.get(data["audio_url"])
    assert res_audio.status_code == 200
    assert res_audio.headers["content-type"] == "audio/mpeg"
    assert len(res_audio.content) > 1000
    print(f"   - Streaming de áudio validado: {len(res_audio.content)} bytes transferidos.")
    print("   ✔ Geração e streaming de amostra sonora aprovados!\n")


def test_api_render_quick_test_and_audit():
    print("▶ 5. Testando Renderização com Auditoria de Motores via API...")
    res = client.post(
        "/api/projects/demo_audiobook/render",
        json={
            "chapter_number": 1,
            "quick_test": True,  # Teste rápido de 3 falas
            "enable_kokoro_eq": True,
            "enable_room_tone": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["blocks_count"] == 3
    assert len(data["audit"]) == 3
    print(f"   - Renderização rápida via API concluída: {data['filename']} ({data['size_kb']} KB)")
    print(f"   - Auditoria de motores: {[b['actual_engine'] for b in data['audit']]}")

    # Testa streaming do MP3 masterizado
    res_stream = client.get(data["audio_url"])
    assert res_stream.status_code == 200
    assert res_stream.headers["content-type"] == "audio/mpeg"
    print("   ✔ Renderização, auditoria e streaming via API 100% aprovados!\n")


def test_frontend_static_serving():
    print("▶ 6. Testando Servidor de Arquivos Estáticos do Frontend (docs/)...")
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "AudioBook Studio" in res_root.text

    res_css = client.get("/styles.css")
    assert res_css.status_code == 200
    assert "--bg-main" in res_css.text

    res_js = client.get("/app.js")
    assert res_js.status_code == 200
    assert "API_BASE" in res_js.text
    print("   - Frontend servido perfeitamente em / (index.html, styles.css, app.js)")
    print("   ✔ Servidor de Arquivos Estáticos aprovado com sucesso!\n")


if __name__ == "__main__":
    print("=" * 70)
    print("INICIANDO SUITE DE TESTES - FASE 6 (FASTAPI & FRONTEND DESACOPLADO)")
    print("=" * 70)

    test_api_status_and_voices()
    test_api_project_management()
    test_api_pdf_page_count_and_extract()
    test_api_voice_preview_sample()
    test_api_render_quick_test_and_audit()
    test_frontend_static_serving()

    print("=" * 70)
    print("TODOS OS TESTES DA FASE 6 FORAM CONCLUÍDOS COM 100% DE SUCESSO! 🎉")
    print("=" * 70)
