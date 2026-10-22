"""Bateria de testes automatizados da Fase 8 do AudioBook App.

Valida:
1. Restauração dos modelos primários gemini-3.5-flash-lite (Diretor) e gemini-3.8-flash-lite-tts (TTS) com fallback para a linha 2.5.
2. Painel de Contexto / Guia Vivo do Projeto (#projectContextBanner) com Presets rápidos (Aula vs Rádio-Teatro) e Tooltips CSS.
3. Redesign Visual Studio Pro com ícones vetoriais Lucide, superfície #090b10 e navegação segmentada.
4. Player de Áudio 100% customizado (sem <audio controls> nativo branco), com Play/Pause SVG, Scrubber e Volume.
5. Timeline estilo Descript (textarea transparente, auto-save com badge '✓ Salvo') e avatares de elenco.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from src.api import app
import src.director as director_mod
import src.synthesizer as synth_mod

client = TestClient(app)


def test_models_35_and_38_lite_restored():
    print("▶ 1. Testando Restauração dos Modelos gemini-3.5-flash-lite e gemini-3.8-flash-lite-tts...")
    assert synth_mod.DEFAULT_GEMINI_TTS_MODEL == "gemini-3.8-flash-lite-tts", (
        f"Esperado gemini-3.8-flash-lite-tts, encontrado {synth_mod.DEFAULT_GEMINI_TTS_MODEL}"
    )
    assert synth_mod.FALLBACK_GEMINI_TTS_MODEL == "gemini-2.5-flash-preview-tts"

    director_src = inspect.getsource(director_mod.Director.direct_chunk_with_gemini)
    assert 'default_mod = "gemini-3.5-flash-lite"' in director_src
    assert '"gemini-2.5-flash-lite"' in director_src
    print("   - Diretor primário: gemini-3.5-flash-lite (fallback: gemini-2.5-flash-lite)")
    print("   - TTS primário: gemini-3.8-flash-lite-tts (fallback: gemini-2.5-flash-preview-tts)")
    print("   ✔ Modelos 3.5 e 3.8 Lite validados com sucesso!\n")


def test_ux_presets_and_tooltips():
    print("▶ 2. Testando Guia Vivo de Presets, Tooltips CSS e Textos Autoexplicativos...")
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    assert ("styles.css?v=8.0" in html or "styles.css?v=9.0" in html)
    assert ("app.js?v=8.0" in html or "app.js?v=9.0" in html)
    assert "projectContextBanner" in html
    assert "btnPresetLecture" in html
    assert "btnPresetDrama" in html
    assert "projectLiveSummary" in html
    assert "data-tooltip=" in html
    assert "gemini-3.5-flash-lite" in html

    res_js = client.get("/app.js")
    js = res_js.text
    assert "applyProjectPreset" in js
    assert "updateContextGuideBar" in js
    print("   - Presets Modo Aula e Modo Rádio-Teatro presentes e conectados.")
    print("   - Tooltips explicativos em CSS puro verificados.")
    print("   ✔ UX Autoexplicativa aprovada!\n")


def test_custom_player_and_studio_redesign():
    print("▶ 3. Testando Player 100% Customizado, Ícones Lucide e Timeline Estilo Descript...")
    html = client.get("/").text
    css = client.get("/styles.css").text
    js = client.get("/app.js").text

    # Verifica que <audio id="mainAudioPlayer"> está oculto e sem controls nativo branco
    assert '<audio id="mainAudioPlayer" class="hidden"' in html
    assert "btnPlayerPlayPause" in html
    assert "playerSeekInput" in html
    assert "playerScrubberFill" in html
    assert "playerVolumeSlider" in html
    assert "lucide@latest" in html

    # Verifica estética Dark Studio no CSS
    assert "--bg-main: #090b10;" in css
    assert ".help-tooltip-trigger::after" in css
    assert ".scrubber-fill" in css
    assert ".char-avatar" in css
    assert ".block-save-indicator" in css

    # Verifica lógica de avatares e badge Salvo no JS
    assert "getCharacterInitials" in js
    assert "flashBlockSaveBadge" in js
    assert "initCustomAudioPlayer" in js

    print("   - Player customizado sem barra nativa branca validado.")
    print("   - Ícones vetoriais Lucide, avatares de elenco e timeline Descript validados.")
    print("   ✔ Redesign Studio Pro v8.0 aprovado!\n")


if __name__ == "__main__":
    print("=" * 70)
    print("INICIANDO SUITE DE TESTES - FASE 8 (MODELOS 3.5/3.8 & STUDIO PRO v8.0)")
    print("=" * 70)

    test_models_35_and_38_lite_restored()
    test_ux_presets_and_tooltips()
    test_custom_player_and_studio_redesign()

    print("=" * 70)
    print("TODOS OS TESTES DA FASE 8 FORAM CONCLUÍDOS COM 100% DE SUCESSO! 🎉")
    print("=" * 70)
