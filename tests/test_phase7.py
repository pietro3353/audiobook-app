"""Bateria de testes automatizados da Fase 7 do AudioBook App.

Valida:
1. Atualização rápida de metadados do projeto via PUT /api/projects/{slug} (Modo, Estratégia e Título).
2. Edição inline atômica de blocos de roteiro via PUT /api/projects/{slug}/script/{chap}/blocks/{idx}.
3. Recálculo automático de parâmetros acústicos (rate, pitch, volume e acting_prompt) com Clamping.
4. Invalidação de cache temporário de blocos editados.
5. Integração frontend: entrega de assets v7.0 (index.html, styles.css com --bg-surface e toast container, app.js com showToast).
"""

import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from src.api import app, pm
from src.models import ChapterScript, SpeechBlock

client = TestClient(app)
TEST_SLUG = "teste_ux_phase7"


def test_quick_project_update():
    print("▶ 1. Testando Atualização de Modo e Estratégia do Projeto (PUT /api/projects/{slug})...")
    # Garante criação do projeto
    client.post(
        "/api/projects",
        json={
            "slug": TEST_SLUG,
            "title": "Projeto UX Teste",
            "mode": "fiction",
            "engine_strategy": "hybrid",
        },
    )

    # Atualiza para Não-Ficção e Ilimitado
    res = client.put(
        f"/api/projects/{TEST_SLUG}",
        json={
            "title": "Projeto UX Atualizado",
            "mode": "non_fiction",
            "engine_strategy": "unlimited",
        },
    )
    assert res.status_code == 200, f"Falha no PUT /projects: {res.text}"
    data = res.json()
    assert data["success"] is True
    assert data["project"]["mode"] == "non_fiction"
    assert data["project"]["engine_strategy"] == "unlimited"
    assert data["project"]["title"] == "Projeto UX Atualizado"

    # Confirma via GET
    get_res = client.get(f"/api/projects/{TEST_SLUG}")
    assert get_res.status_code == 200
    meta = get_res.json()
    assert meta["mode"] == "non_fiction"
    assert meta["engine_strategy"] == "unlimited"
    print("   - Metadados atualizados com sucesso via PUT:", meta["mode"], meta["engine_strategy"])
    print("   ✔ Rota PUT /api/projects/{slug} aprovada!\n")


def test_inline_block_editing_and_cache_invalidation():
    print("▶ 2. Testando Edição Inline de Blocos do Roteiro e Invalidação de Cache...")
    # Cria roteiro prévio para o capítulo 1
    script = ChapterScript(
        chapter_number=1,
        title="Capítulo 01 Teste",
        blocks=[
            SpeechBlock(
                index=1,
                character_id="narrador",
                text="Texto original de teste da fala.",
                emotion="neutro",
                pause_after_ms=600,
                engine="edge",
                voice_id="edge_antonio",
                actual_engine="edge",
                actual_voice_id="edge_antonio",
            ),
            SpeechBlock(
                index=2,
                character_id="narrador",
                text="Segunda fala.",
                emotion="neutro",
                pause_after_ms=600,
                engine="edge",
                voice_id="edge_antonio",
            ),
        ],
    )
    pm.save_chapter_script(TEST_SLUG, script)

    # Cria arquivo falso de cache para testar invalidação
    temp_dir = pm.get_project_dir(TEST_SLUG) / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    fake_chunk = temp_dir / "block_0001_edge_antonio.mp3"
    fake_chunk.write_bytes(b"dummy audio cache")
    assert fake_chunk.exists(), "Chunk falso não pôde ser criado para o teste."

    # Atualiza o bloco 1 com emoção 'sussurro', novo texto e pausa de 1200ms
    res = client.put(
        f"/api/projects/{TEST_SLUG}/script/1/blocks/1",
        json={
            "text": "Texto alterado com sussurro e suspense.",
            "emotion": "sussurro",
            "pause_after_ms": 1200,
        },
    )
    assert res.status_code == 200, f"Falha no PUT block: {res.text}"
    data = res.json()
    assert data["success"] is True
    bloco = data["block"]

    # Validações dos campos atualizados
    assert bloco["text"] == "Texto alterado com sussurro e suspense."
    assert bloco["emotion"] == "sussurro"
    assert bloco["pause_after_ms"] == 1200

    # Valida recálculo acústico com clamping (narrador baseline -4% + sussurro delta -4% = -8%)
    assert bloco["rate"] == "-8%"
    assert bloco["pitch"] == "-1Hz"
    assert bloco["volume"] == "-10%"
    assert "sussurro" in bloco["acting_prompt"].lower()

    # Valida reset de auditoria para nova síntese
    assert bloco["actual_engine"] is None
    assert bloco["actual_voice_id"] is None

    # Valida que o cache anterior foi invalidado e removido do disco
    assert not fake_chunk.exists(), "Cache temporário não foi invalidado na edição do bloco!"
    print("   - Bloco #1 atualizado com novos parâmetros acústicos:", bloco["rate"], bloco["pitch"], bloco["volume"])
    print("   - Cache temporário do bloco devidamente purgado do disco.")
    print("   ✔ Edição Inline de Blocos e Invalidação 100% aprovadas!\n")


def test_frontend_v7_assets_and_toast():
    print("▶ 3. Testando Frontend Integrado (Assets v7.0, Toast Container e Controles)...")
    res_index = client.get("/")
    assert res_index.status_code == 200
    html = res_index.text

    # Verifica cache-busting v7.0
    assert "styles.css?v=7.0" in html
    assert "app.js?v=7.0" in html

    # Verifica novos elementos visuais de UX
    assert "quickProjectMode" in html
    assert "quickProjectStrategy" in html
    assert "btnClearText" in html
    assert "btnPlayerBack10" in html
    assert "btnPlayerFwd10" in html
    assert "toastContainer" in html
    assert "statusBadgeGemini" in html

    # Valida styles.css
    res_css = client.get("/styles.css")
    assert res_css.status_code == 200
    css = res_css.text
    assert "--bg-surface: #12151e;" in css
    assert ".toast-container" in css
    assert ".btn-player-seek" in css
    assert ".playback-speed-group" in css

    # Valida app.js
    res_js = client.get("/app.js")
    assert res_js.status_code == 200
    js = res_js.text
    assert "function showToast" in js
    assert "saveBlockChanges" in js
    assert "btnPlayerBack10" in js
    assert "btnClearText" in js
    assert "audiobook_active_slug" in js

    print("   - Frontend entregando index.html com versão ?v=7.0")
    print("   - CSS contém --bg-surface, Toast e Controles do Player")
    print("   - JS contém showToast, edição inline de roteiro e persistência LocalStorage")
    print("   ✔ Frontend v7.0 validado com sucesso!\n")


def cleanup():
    # Remove projeto temporário de teste
    pm.delete_project(TEST_SLUG)


if __name__ == "__main__":
    print("=" * 70)
    print("INICIANDO SUITE DE TESTES - FASE 7 (REFINAMENTO UX/UI & INTEGRAÇÃO)")
    print("=" * 70)

    try:
        test_quick_project_update()
        test_inline_block_editing_and_cache_invalidation()
        test_frontend_v7_assets_and_toast()
        print("=" * 70)
        print("TODOS OS TESTES DA FASE 7 FORAM CONCLUÍDOS COM 100% DE SUCESSO! 🎉")
        print("=" * 70)
    finally:
        cleanup()
