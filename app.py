"""AudioBook Studio AI - Estúdio Web Interativo para Produção de Audiolivros.

Interface construída em Streamlit para teste com PDFs reais, direção dramática com IA,
inspeção de vozes com audição prévia de 2 segundos, teste rápido de 3 falas e renderização
multi-motor transparente com masterização de áudio.
"""

import asyncio
import os
import shutil
from pathlib import Path
from typing import List, Optional

import streamlit as st
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Importações dos módulos da engine
import src  # Configura caminhos e FFmpeg
from src.director import Director
from src.emotions import list_emotion_labels
from src.extractor import cure_text, detect_chapters, extract_from_pdf, get_pdf_page_count
from src.mixer import AudioMixer
from src.models import ChapterScript, ProjectMetadata, SpeechBlock
from src.project_manager import ProjectManager
from src.synthesizer import Synthesizer
from src.voices import VOICE_CATALOG, list_voices


# ==============================================================================
# CONFIGURAÇÃO GERAL DA PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="AudioBook Studio AI",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inicializa instâncias dos serviços na sessão do Streamlit
if "pm" not in st.session_state:
    st.session_state.pm = ProjectManager()
if "mixer" not in st.session_state:
    st.session_state.mixer = AudioMixer()
if "current_slug" not in st.session_state:
    st.session_state.current_slug = "demo_audiobook"
if "curated_text" not in st.session_state:
    st.session_state.curated_text = ""
if "last_rendered_mp3" not in st.session_state:
    st.session_state.last_rendered_mp3 = None

pm: ProjectManager = st.session_state.pm
mixer: AudioMixer = st.session_state.mixer


# ==============================================================================
# BARRA LATERAL: CONFIGURAÇÕES & PROJETOS
# ==============================================================================
with st.sidebar:
    st.title("🎙️ AudioBook Studio")
    st.caption("Engine Universal de Áudio Dramático com Memória")
    st.divider()

    # 1. Configuração de Chave API (Google AI Studio)
    st.subheader("🔑 Google AI Studio (Gemini)")
    gemini_key_env = os.getenv("GEMINI_API_KEY", "")
    gemini_key_input = st.text_input(
        "Chave API do Gemini:",
        value=gemini_key_env if gemini_key_env != "sua_chave_api_aqui" else "",
        type="password",
        placeholder="Cole sua chave AI Studio...",
        help="Permite atuação por prompt no Gemini TTS e Direção Inteligente de cena.",
    )

    if st.button("💾 Salvar Chave no .env", use_container_width=True):
        if gemini_key_input.strip():
            os.environ["GEMINI_API_KEY"] = gemini_key_input.strip()
            env_file = Path(".env")
            lines = []
            if env_file.exists():
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.startswith("GEMINI_API_KEY="):
                            lines.append(line)
            lines.append(f"GEMINI_API_KEY={gemini_key_input.strip()}\n")
            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(lines)
            st.success("Chave salva com sucesso!")
        else:
            st.warning("Insira uma chave válida.")

    # Status da Chave
    tem_chave = bool(os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_API_KEY") != "sua_chave_api_aqui")
    if tem_chave:
        st.success("🟢 Gemini Ativo (Direção & Atuação por Prompt)")
    else:
        st.info("⚪ Modo 100% Offline (Edge-TTS & Kokoro Hugging Face)")

    st.divider()

    # 2. Gerenciamento de Projetos
    st.subheader("📁 Gerenciador de Projetos")
    projetos_existentes = pm.list_projects()
    if "demo_audiobook" not in projetos_existentes and not projetos_existentes:
        projetos_existentes = ["demo_audiobook"]

    modo_projeto = st.radio(
        "Ação:",
        ["Carregar Existente", "Criar Novo Projeto"],
        horizontal=True,
    )

    if modo_projeto == "Carregar Existente" and projetos_existentes:
        slug_selecionado = st.selectbox(
            "Selecionar Projeto:",
            projetos_existentes,
            index=0 if st.session_state.current_slug not in projetos_existentes else projetos_existentes.index(st.session_state.current_slug),
        )
        st.session_state.current_slug = slug_selecionado
    else:
        novo_titulo = st.text_input("Título da Obra:", "O Mistério da Mansão")
        novo_slug = st.text_input("Slug da Obra (identificador):", "misterio_mansao")
        novo_modo = st.selectbox(
            "Gênero / Formato:",
            ["fiction", "non_fiction", "summary"],
            format_func=lambda x: {"fiction": "Ficção / Literatura", "non_fiction": "Não-Ficção / Acadêmico", "summary": "Resumo Narrado"}[x],
        )
        nova_estrategia = st.selectbox(
            "Estratégia de Motores:",
            ["hybrid", "unlimited"],
            format_func=lambda x: {"hybrid": "Híbrido (Gemini Diálogos + Edge/Kokoro)", "unlimited": "Ilimitado 100% Gratuito (Kokoro + Edge)"}[x],
        )

        if st.button("➕ Criar Workspace", use_container_width=True):
            if novo_slug.strip() and novo_titulo.strip():
                pm.create_project(
                    slug=novo_slug.strip(),
                    title=novo_titulo.strip(),
                    mode=novo_modo,
                    engine_strategy=nova_estrategia,
                )
                st.session_state.current_slug = novo_slug.strip()
                st.success(f"Projeto '{novo_titulo}' criado com sucesso!")
                st.rerun()

    st.divider()

    # 3. Masterização & Equalização
    st.subheader("🎛️ Equalização e Acústica")
    enable_kokoro_eq = st.checkbox(
        "Brilho no Kokoro (+2.5dB agudos)",
        value=True,
        help="Aplica equalização high-shelf para casar a resposta de frequência do Kokoro ao Edge/Gemini.",
    )
    enable_room_tone = st.checkbox(
        "Room Tone de Estúdio (-56 dBFS)",
        value=True,
        help="Insere ruído contínuo de cabine nas pausas para evitar o corte abrupto de vácuo digital.",
    )


# Metadados do projeto ativo
meta_atual = pm.load_metadata(st.session_state.current_slug) or ProjectMetadata(
    slug=st.session_state.current_slug,
    title=st.session_state.current_slug,
)
bible_atual = pm.load_character_bible(st.session_state.current_slug)
director_engine = Director(project_manager=pm)
synthesizer = Synthesizer(gemini_api_key=os.getenv("GEMINI_API_KEY", ""))


# ==============================================================================
# PAINEL PRINCIPAL EM 3 ETAPAS
# ==============================================================================
st.title(f"📖 {meta_atual.title}")
st.caption(f"Workspace Ativo: `{meta_atual.slug}` | Modo: **{meta_atual.mode.upper()}** | Estratégia: **{meta_atual.engine_strategy.upper()}**")

tab_upload, tab_diretor, tab_render = st.tabs([
    "1. 📄 Upload de PDF Real & Escopo",
    "2. 🎭 Sala do Diretor & Elenco",
    "3. 🎧 Renderização & Player",
])


# ==============================================================================
# ABA 1: UPLOAD DE PDF REAL E FILTRO DE ESCOPO
# ==============================================================================
with tab_upload:
    st.subheader("Extração Limpa e Seleção de Páginas")
    st.markdown("Arraste um PDF ou livro real. O sistema permite selecionar um trecho específico para testar em segundos.")

    col_up1, col_up2 = st.columns([1, 1])

    with col_up1:
        uploaded_file = st.file_uploader(
            "Carregar arquivo (.pdf, .epub, .txt, .md):",
            type=["pdf", "epub", "txt", "md"],
        )

        texto_extraido_bruto = ""
        total_paginas = 1

        if uploaded_file is not None:
            file_bytes = uploaded_file.getvalue()
            nome_arq = uploaded_file.name.lower()

            if nome_arq.endswith(".pdf"):
                total_paginas = get_pdf_page_count(file_bytes)
                st.info(f"📚 PDF detectado com **{total_paginas} páginas totais**.")

                c_p1, c_p2 = st.columns(2)
                with c_p1:
                    pag_inicio = st.number_input("Página Inicial:", min_value=1, max_value=total_paginas, value=1)
                with c_p2:
                    pag_fim = st.number_input("Página Final:", min_value=1, max_value=total_paginas, value=min(3, total_paginas))

                limite_paragrafos = st.slider("Limite máximo de parágrafos (opcional para teste rápido):", min_value=1, max_value=50, value=10)

                if st.button("⚡ Extrair e Curar Trecho do PDF", use_container_width=True):
                    with st.spinner("Extraindo e aplicando cura de texto..."):
                        raw_pdf = extract_from_pdf(file_bytes, start_page=pag_inicio, end_page=pag_fim)
                        curado = cure_text(raw_pdf)
                        # Aplica limite de parágrafos se selecionado
                        parags = [p for p in curado.split("\n\n") if p.strip()]
                        if limite_paragrafos and len(parags) > limite_paragrafos:
                            curado = "\n\n".join(parags[:limite_paragrafos])
                        st.session_state.curated_text = curado
                        st.success(f"Extraído com sucesso! {len(parags[:limite_paragrafos])} parágrafos curados.")
            else:
                if st.button("⚡ Extrair e Curar Texto", use_container_width=True):
                    texto_decodificado = file_bytes.decode("utf-8", errors="ignore")
                    st.session_state.curated_text = cure_text(texto_decodificado)
                    st.success("Texto curado com sucesso!")

    with col_up2:
        st.markdown("**Texto Curado (Pronto para a Direção):**")
        texto_editado = st.text_area(
            "Você pode editar o texto antes de enviar para o Diretor:",
            value=st.session_state.curated_text or (
                "A tempestade desabava com violência sobre a velha torre de pedra.\n\n"
                "— Precisamos fechar as comportas antes que a represa transborde! — gritou Pierre, apontando para o abismo.\n\n"
                "— Não há tempo, senhor! As engrenagens estão emperradas! — respondeu Arthur em pânico.\n\n"
                "— Eu posso tentar passar pelo duto de ventilação... — sussurrou a pequena Aninha, tremendo de frio.\n\n"
                "— Paciência, meus jovens. O vento nos revela mais do que a pressa — advertiu o Mestre Ancião."
            ),
            height=300,
        )
        st.session_state.curated_text = texto_editado


# ==============================================================================
# ABA 2: SALA DO DIRETOR & ELENCO (BÍBLIA DE PERSONAGENS)
# ==============================================================================
with tab_diretor:
    st.subheader("Sala do Diretor & Elenco da Obra")
    st.markdown("O Diretor identifica os personagens, infere emoções e atribui vozes respeitando a anti-colisão.")

    col_dir1, col_dir2 = st.columns([1, 2])

    with col_dir1:
        st.markdown("### Ação do Diretor")
        modo_direcao = st.radio(
            "Modo de Direção:",
            ["✨ Diretor LLM (Google Gemini)", "⚡ Modo Express (100% Offline / Determinístico)"],
            index=0 if tem_chave else 1,
        )
        usar_express = "Express" in modo_direcao or not tem_chave

        if st.button("🎬 1. Analisar e Dirigir Cena", type="primary", use_container_width=True):
            if not st.session_state.curated_text.strip():
                st.warning("Extraia ou insira um texto na Aba 1 antes de dirigir.")
            else:
                with st.spinner("O Diretor está analisando a cena, personagens e emoções..."):
                    script = director_engine.direct_chapter(
                        project_slug=st.session_state.current_slug,
                        chapter_number=1,
                        chapter_title="Capítulo 01",
                        chapter_content=st.session_state.curated_text,
                        force_express=usar_express,
                    )
                    st.success(f"Direção concluída! {len(script.blocks)} falas roteirizadas.")
                    st.rerun()

    with col_dir2:
        st.markdown("### 👥 Elenco da Bíblia de Personagens")
        bible_atual = pm.load_character_bible(st.session_state.current_slug)

        if not bible_atual.characters:
            st.info("Nenhum personagem cadastrado ainda. Clique em 'Analisar e Dirigir Cena' para construir o elenco.")
        else:
            catalogo_opcoes = list(VOICE_CATALOG.keys())

            for char_id, char in list(bible_atual.characters.items()):
                with st.expander(f"🎭 **{char.name}** ({char.gender}, {char.apparent_age}, sotaque: {char.accent})", expanded=True):
                    c_c1, c_c2, c_c3 = st.columns([2, 1, 1])

                    with c_c1:
                        voz_idx = catalogo_opcoes.index(char.voice_id) if char.voice_id in catalogo_opcoes else 0
                        nova_voz = st.selectbox(
                            f"Voz Primária para {char.name}:",
                            catalogo_opcoes,
                            index=voz_idx,
                            key=f"voice_select_{char_id}",
                            format_func=lambda v: f"{VOICE_CATALOG[v].name} [{VOICE_CATALOG[v].engine.upper()}] - {VOICE_CATALOG[v].timbre}",
                        )
                        if nova_voz != char.voice_id:
                            prof_escolhido = VOICE_CATALOG[nova_voz]
                            char.voice_id = prof_escolhido.id
                            char.engine = prof_escolhido.engine
                            char.blend_recipe = prof_escolhido.blend_recipe
                            pm.save_character_bible(bible_atual)
                            st.toast(f"Voz de {char.name} atualizada para {prof_escolhido.name}!")

                    with c_c2:
                        st.caption(f"**Motor:** `{char.engine.upper()}`")
                        st.caption(f"**Personalidade:** {char.personality}")

                    with c_c3:
                        # Botão de Preview Sonoro de 2 Segundos
                        btn_preview = st.button("▶ Ouvir Amostra (2s)", key=f"preview_btn_{char_id}")
                        if btn_preview:
                            with st.spinner("Gerando amostra de voz..."):
                                loop = asyncio.new_event_loop()
                                async_synthesizer = Synthesizer(gemini_api_key=os.getenv("GEMINI_API_KEY", ""))
                                sample_path = loop.run_until_complete(
                                    async_synthesizer.generate_voice_sample(char.voice_id)
                                )
                                loop.close()
                                if sample_path and sample_path.exists():
                                    st.audio(str(sample_path), format="audio/mp3")

    # Tabela do Roteiro Gerado
    script_atual = pm.load_chapter_script(st.session_state.current_slug, 1)
    if script_atual and script_atual.blocks:
        st.divider()
        st.markdown(f"### 📜 Roteiro Estruturado ({len(script_atual.blocks)} falas)")
        tabela_roteiro = []
        for b in script_atual.blocks:
            tabela_roteiro.append({
                "Nº": b.index,
                "Personagem": b.character_id,
                "Tipo": b.speech_type,
                "Emoção": b.emotion,
                "Motor": b.engine.upper(),
                "Voz": b.voice_id,
                "Texto": b.text,
                "Texto Adaptado (TTS)": b.text_for_tts or b.text,
                "Atuação Cênica": b.acting_prompt or "—",
            })
        st.dataframe(tabela_roteiro, use_container_width=True)


# ==============================================================================
# ABA 3: RENDERIZAÇÃO, AUDITORIA & PLAYER
# ==============================================================================
with tab_render:
    st.subheader("Renderização Multi-Motor e Masterização de Estúdio")
    st.markdown("Sintetize as falas com transparência total de qual motor gerou cada trecho e ouça na hora no navegador.")

    script_carregado = pm.load_chapter_script(st.session_state.current_slug, 1)

    if not script_carregado or not script_carregado.blocks:
        st.warning("Nenhum roteiro pronto para renderizar. Acesse a Aba 2 e clique em 'Analisar e Dirigir Cena'.")
    else:
        col_ctrl1, col_ctrl2 = st.columns(2)

        with col_ctrl1:
            btn_teste_rapido = st.button(
                "⚡ Teste Rápido (3 Primeiras Falas)",
                help="Gera apenas as 3 primeiras falas em ~4 segundos para testar a acústica e a transição entre vozes.",
                use_container_width=True,
            )

        with col_ctrl2:
            btn_render_total = st.button(
                "🎙️ Renderizar Cena Completa",
                type="primary",
                help="Sintetiza todas as falas do capítulo com os motores configurados e masteriza o áudio final.",
                use_container_width=True,
            )

        if btn_teste_rapido or btn_render_total:
            blocos_alvo = script_carregado.blocks[:3] if btn_teste_rapido else script_carregado.blocks
            subscript = ChapterScript(
                chapter_number=script_carregado.chapter_number,
                title=f"{script_carregado.title} ({'Teste 3 Falas' if btn_teste_rapido else 'Completo'})",
                blocks=blocos_alvo,
                total_chars=sum(len(b.text) for b in blocos_alvo),
            )

            progresso_bar = st.progress(0, text="Iniciando síntese de voz...")
            status_placeholder = st.empty()

            loop = asyncio.new_event_loop()
            async_synth = Synthesizer(gemini_api_key=os.getenv("GEMINI_API_KEY", ""))

            def atualizar_progresso(concluidos, total):
                pct = int((concluidos / total) * 100)
                progresso_bar.progress(pct, text=f"Sintetizando falas: {concluidos}/{total} ({pct}%)")

            # 1. Síntese concorrente
            temp_pasta = pm.get_project_dir(st.session_state.current_slug) / "temp" / f"cap_{subscript.chapter_number:02d}"
            chunks_brutos = loop.run_until_complete(
                async_synth.synthesize_chapter(
                    script=subscript,
                    project_slug=st.session_state.current_slug,
                    temp_dir=temp_pasta,
                    on_progress=atualizar_progresso,
                )
            )
            loop.close()

            # 2. Masterização acústica
            status_placeholder.info("🎛️ Masterizando áudio com micro-fades, equalização de brilho e room tone...")
            saida_final = pm.get_project_dir(st.session_state.current_slug) / "output" / (
                "demo_teste_3_falas.mp3" if btn_teste_rapido else "demo_cena_dramatica.mp3"
            )

            mixer.mix_chapter(
                script=subscript,
                raw_chunks=chunks_brutos,
                output_chapter_mp3=saida_final,
                enable_kokoro_eq=enable_kokoro_eq,
                enable_room_tone=enable_room_tone,
            )

            st.session_state.last_rendered_mp3 = saida_final
            progresso_bar.progress(100, text="🎉 Renderização concluída com sucesso!")
            st.success(f"Áudio gerado em: `{saida_final}`")

        # Exibição do Player e Auditoria de Motores
        if st.session_state.last_rendered_mp3 and Path(st.session_state.last_rendered_mp3).exists():
            caminho_audio = Path(st.session_state.last_rendered_mp3)
            st.divider()
            st.markdown("### 🎧 Player de Áudio Masterizado")
            st.audio(str(caminho_audio), format="audio/mp3")

            tamanho_kb = round(caminho_audio.stat().st_size / 1024, 1)
            with open(caminho_audio, "rb") as f_down:
                st.download_button(
                    label=f"⬇️ Baixar Arquivo MP3 ({tamanho_kb} KB)",
                    data=f_down,
                    file_name=caminho_audio.name,
                    mime="audio/mp3",
                )

            # Transparência e Auditoria de Motores Executados
            st.markdown("### 🔍 Auditoria Visual de Motores Utilizados")
            st.caption("Garante transparência total. Você sabe exatamente qual IA gerou cada frase.")

            for i, b in enumerate(script_carregado.blocks[:3] if "3_falas" in caminho_audio.name else script_carregado.blocks):
                motor_real = b.actual_engine or b.engine
                c_a1, c_a2, c_a3 = st.columns([1, 2, 3])

                with c_a1:
                    if motor_real == "kokoro":
                        st.markdown("🟢 **Kokoro HF (Local)**")
                    elif motor_real == "gemini":
                        st.markdown("🔵 **Gemini TTS (Atuado)**")
                    else:
                        st.markdown("🟣 **Edge-TTS (Nuvem)**")

                with c_a2:
                    st.write(f"**Fala {b.index}:** [{b.character_id}]")
                    if b.fallback_triggered:
                        st.warning(f"⚠️ Contingência: {b.fallback_reason}")

                with c_a3:
                    st.write(f"\"{b.text[:80]}...\"")
