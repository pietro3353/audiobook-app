/**
 * AUDIOBOOK STUDIO AI - FRONTEND APPLICATION (SPA)
 * Conecta-se à API FastAPI local ou remota para extração, direção e síntese de voz.
 */

// URL configurável da API Backend (ajustável para nuvem no futuro)
const API_BASE = window.location.origin.includes("github.io")
  ? "http://localhost:8000"
  : window.location.origin;

// Estado da Aplicação
const state = {
  currentSlug: "demo_audiobook",
  voicesCatalog: [],
  characters: [],
  script: null,
  activeStep: 1,
  selectedFile: null,
  isRendering: false,
};

// ==============================================================================
// INICIALIZAÇÃO
// ==============================================================================
document.addEventListener("DOMContentLoaded", async () => {
  initEventListeners();
  await checkBackendStatus();
  await loadVoicesCatalog();
  await loadProjects();
  await loadCurrentProjectData();

  // Verifica status do backend a cada 10 segundos
  setInterval(checkBackendStatus, 10000);
});

// ==============================================================================
// 1. STATUS DO BACKEND & CONFIGURAÇÃO
// ==============================================================================
async function checkBackendStatus() {
  const badge = document.getElementById("backendStatusBadge");
  const text = document.getElementById("backendStatusText");

  try {
    const res = await fetch(`${API_BASE}/api/status`);
    if (res.ok) {
      const data = await res.json();
      badge.className = "status-badge status-online";
      text.textContent = data.gemini_active ? "🟢 Motor Online (Gemini + Local)" : "🟢 Motor Online (100% Local)";
    } else {
      throw new Error();
    }
  } catch (e) {
    badge.className = "status-badge status-offline";
    text.textContent = "⚪ Motor Offline (Inicie o backend)";
  }
}

async function loadVoicesCatalog() {
  try {
    const res = await fetch(`${API_BASE}/api/voices`);
    if (res.ok) {
      const data = await res.json();
      state.voicesCatalog = data.voices || [];
    }
  } catch (e) {
    console.error("Erro ao carregar catálogo de vozes:", e);
  }
}

// ==============================================================================
// 2. GESTÃO DE PROJETOS
// ==============================================================================
async function loadProjects() {
  const select = document.getElementById("projectSelect");
  try {
    const res = await fetch(`${API_BASE}/api/projects`);
    if (res.ok) {
      const data = await res.json();
      select.innerHTML = "";
      const projs = data.projects || [];

      projs.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.slug;
        opt.textContent = `${p.title} (${p.slug})`;
        if (p.slug === state.currentSlug) opt.selected = true;
        select.appendChild(opt);
      });

      if (projs.length > 0) {
        if (!state.currentSlug || !projs.some((p) => p.slug === state.currentSlug)) {
          state.currentSlug = projs[0].slug;
          select.value = state.currentSlug;
        }
      } else {
        // Se a lista estiver vazia, cria projeto padrão
        state.currentSlug = "meu_audiolivro";
        await fetch(`${API_BASE}/api/projects`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug: "meu_audiolivro", title: "Meu Audiolivro", mode: "fiction", engine_strategy: "hybrid" }),
        });
        await loadProjects();
        return;
      }
    }
  } catch (e) {
    console.error("Erro ao carregar projetos:", e);
  }
}

async function loadCurrentProjectData() {
  if (!state.currentSlug) return;

  // 1. Carrega Texto Curado do Projeto
  try {
    const res = await fetch(`${API_BASE}/api/projects/${state.currentSlug}/text`);
    if (res.ok) {
      const data = await res.json();
      const txtArea = document.getElementById("curatedTextArea");
      txtArea.value = data.text || "";
      updateTextMetrics(txtArea.value);
    }
  } catch (e) {
    console.error("Erro ao carregar Texto do Projeto:", e);
  }

  // 2. Carrega Bíblia de Personagens
  try {
    const res = await fetch(`${API_BASE}/api/projects/${state.currentSlug}/bible`);
    if (res.ok) {
      const data = await res.json();
      state.characters = Object.values(data.characters || {});
      renderCastGrid();
    }
  } catch (e) {
    console.error("Erro ao carregar Bíblia:", e);
  }

  // 3. Carrega Roteiro existente do Capítulo 1
  try {
    const res = await fetch(`${API_BASE}/api/projects/${state.currentSlug}/script/1`);
    if (res.ok) {
      const data = await res.json();
      if (data.exists && data.script) {
        state.script = data.script;
        renderScriptTimeline();
      } else {
        state.script = null;
        renderScriptTimeline();
      }
    }
  } catch (e) {
    console.error("Erro ao carregar Roteiro:", e);
  }

  // 4. Carrega Status do Áudio Renderizado
  try {
    const res = await fetch(`${API_BASE}/api/projects/${state.currentSlug}/audio`);
    if (res.ok) {
      const data = await res.json();
      if (data.has_audio) {
        setupAudioPlayer(data, false);
      } else {
        resetAudioPlayer();
      }
    }
  } catch (e) {
    console.error("Erro ao verificar áudio do projeto:", e);
  }
}

// ==============================================================================
// 3. NAVEGAÇÃO DE ETAPAS
// ==============================================================================
function setStep(stepNum) {
  state.activeStep = stepNum;
  document.querySelectorAll(".step-btn").forEach((btn) => {
    btn.classList.toggle("active", parseInt(btn.dataset.step) === stepNum);
  });
  document.querySelectorAll(".step-panel").forEach((panel, idx) => {
    panel.classList.toggle("active", idx + 1 === stepNum);
  });
}

// ==============================================================================
// 4. ETAPA 1: UPLOAD & SELEÇÃO DE PÁGINAS
// ==============================================================================
async function handleFileSelected(file) {
  state.selectedFile = file;
  const isPdf = file.name.toLowerCase().endsWith(".pdf");
  const pdfControls = document.getElementById("pdfControls");
  const pdfPageInputsWrapper = document.getElementById("pdfPageInputsWrapper");
  const badge = document.getElementById("pdfPageBadge");
  const typeHint = document.getElementById("fileTypeHint");

  pdfControls.classList.remove("hidden");

  if (isPdf) {
    if (pdfPageInputsWrapper) pdfPageInputsWrapper.classList.remove("hidden");
    badge.textContent = "⏳ Analisando páginas do PDF...";
    if (typeHint) typeHint.textContent = `${file.name} (${Math.round(file.size / 1024)} KB)`;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/extract/pdf/page-count`, {
        method: "POST",
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        badge.textContent = `📚 PDF: ${data.total_pages} páginas detectadas`;
        const endInput = document.getElementById("endPageInput");
        endInput.max = data.total_pages;
        endInput.value = Math.min(3, data.total_pages);
      } else {
        const err = await res.json().catch(() => ({}));
        const errMsg = err.detail || res.statusText || "Não foi possível ler as páginas do PDF.";
        badge.textContent = `⚠️ Erro ao ler PDF: ${errMsg}`;
        alert(`Erro ao ler páginas do PDF: ${errMsg}`);
      }
    } catch (e) {
      badge.textContent = "Erro de conexão ao ler páginas do PDF";
      alert(`Erro de conexão ao ler páginas do PDF: ${e.message || e}`);
    }
  } else {
    // TXT, EPUB ou MD
    if (pdfPageInputsWrapper) pdfPageInputsWrapper.classList.add("hidden");
    badge.textContent = `📄 Arquivo: ${file.name}`;
    if (typeHint) typeHint.textContent = `${Math.round(file.size / 1024)} KB • Texto puro`;
  }
}

async function extractDocumentScope() {
  if (!state.selectedFile) return;

  const btn = document.getElementById("btnExtractScope");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Processando texto...";
  }

  const formData = new FormData();
  formData.append("file", state.selectedFile);

  const isPdf = state.selectedFile.name.toLowerCase().endsWith(".pdf");
  if (isPdf) {
    const startPage = document.getElementById("startPageInput").value || 1;
    const endPage = document.getElementById("endPageInput").value || 3;
    formData.append("start_page", startPage);
    formData.append("end_page", endPage);
  }

  // Verifica se o usuário quer importar o documento completo ou limitar
  const checkImportAll = document.getElementById("checkImportAll");
  if (checkImportAll && !checkImportAll.checked) {
    const maxParags = document.getElementById("maxParagsInput").value || 15;
    formData.append("max_paragraphs", maxParags);
  }

  try {
    const res = await fetch(`${API_BASE}/api/extract`, {
      method: "POST",
      body: formData,
    });
    if (res.ok) {
      const data = await res.json();
      const txtArea = document.getElementById("curatedTextArea");
      txtArea.value = data.curated_text || "";
      updateTextMetrics(txtArea.value);

      // Salva o texto automaticamente no projeto ativo
      await saveProjectText(txtArea.value);
    } else {
      const err = await res.json().catch(() => ({}));
      const errMsg = err.detail || res.statusText || "Erro ao extrair o documento.";
      alert(`⚠️ Erro na extração: ${errMsg}`);
    }
  } catch (e) {
    alert(`Falha na conexão com a API de extração: ${e.message || e}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "⚡ Processar e Inserir no Editor";
    }
  }
}

async function saveProjectText(text) {
  if (!state.currentSlug) return;
  try {
    await fetch(`${API_BASE}/api/projects/${state.currentSlug}/text`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch (e) {
    console.error("Erro ao salvar texto do projeto:", e);
  }
}

function updateTextMetrics(text) {
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const parags = text.trim() ? text.split("\n\n").length : 0;
  document.getElementById("textMetrics").textContent = `${words} palavras | ${parags} parágrafos`;
}

// ==============================================================================
// 5. ETAPA 2: SALA DO DIRETOR & ELENCO
// ==============================================================================
async function runDirector() {
  const text = document.getElementById("curatedTextArea").value.trim();
  if (!text) {
    alert("Insira ou extraia um texto na Etapa 1 antes de dirigir a cena.");
    setStep(1);
    return;
  }

  const btn = document.getElementById("btnRunDirector");
  btn.disabled = true;
  btn.textContent = "Analisando cena com IA...";

  const mode = document.querySelector('input[name="directorMode"]:checked').value;
  const forceExpress = mode === "express";
  const fuseSpeeches = document.getElementById("checkFuseSpeeches") ? document.getElementById("checkFuseSpeeches").checked : true;

  try {
    const res = await fetch(`${API_BASE}/api/projects/${state.currentSlug}/direct`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chapter_number: 1,
        chapter_title: "Capítulo 01",
        chapter_content: text,
        force_express: forceExpress,
        fuse_speeches: fuseSpeeches,
        max_chars_per_speech: 1200,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      state.script = data.script;
      state.characters = data.characters || [];
      renderCastGrid();
      renderScriptTimeline();
    } else {
      const err = await res.json().catch(() => ({}));
      const errMsg = err.detail || res.statusText || "Erro desconhecido ao processar o roteiro.";
      alert(`⚠️ Erro na Direção: ${errMsg}`);
    }
  } catch (e) {
    alert(`Falha de conexão com o motor do Diretor: ${e.message || e}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "🎬 Analisar e Dirigir Cena";
  }
}

function renderCastGrid() {
  const grid = document.getElementById("castGrid");
  const countBadge = document.getElementById("castCountBadge");
  countBadge.textContent = `${state.characters.length} atores`;

  if (!state.characters || state.characters.length === 0) {
    grid.innerHTML = '<div class="empty-state">Nenhum personagem escalado ainda. Clique em "Analisar e Dirigir Cena".</div>';
    return;
  }

  grid.innerHTML = "";
  state.characters.forEach((char) => {
    const card = document.createElement("div");
    card.className = "char-card";

    // Opções de voz para o select
    const optionsHtml = state.voicesCatalog
      .map((v) => {
        const selected = v.id === char.voice_id ? "selected" : "";
        return `<option value="${v.id}" ${selected}>${v.name} [${v.engine.toUpperCase()}] - ${v.timbre}</option>`;
      })
      .join("");

    card.innerHTML = `
      <div class="char-card-top">
        <div>
          <span class="char-name">${char.name}</span>
          <div class="char-details">${char.gender} • ${char.apparent_age} • sotaque ${char.accent}</div>
        </div>
        <span class="badge badge-accent">${char.engine.toUpperCase()}</span>
      </div>
      <div class="char-card-body">
        <label style="font-size: 0.72rem; color: var(--text-muted)">Voz Primária:</label>
        <select class="styled-select voice-changer" data-char-id="${char.id}">
          ${optionsHtml}
        </select>
      </div>
      <div class="char-card-footer">
        <button class="btn btn-secondary btn-sm btn-preview-voice" data-voice-id="${char.voice_id}">▶ Amostra (2s)</button>
      </div>
    `;

    grid.appendChild(card);
  });

  // Event Listeners nos selects de voz
  grid.querySelectorAll(".voice-changer").forEach((sel) => {
    sel.addEventListener("change", async (e) => {
      const charId = e.target.dataset.charId;
      const voiceId = e.target.value;

      // Sincroniza imediatamente o botão de prévia acústica do card
      const card = e.target.closest(".char-card");
      if (card) {
        const previewBtn = card.querySelector(".btn-preview-voice");
        if (previewBtn) previewBtn.dataset.voiceId = voiceId;
      }

      await updateCharacterVoice(charId, voiceId);
    });
  });

  // Event Listeners nos botões de amostra sonora de 2s
  grid.querySelectorAll(".btn-preview-voice").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      const voiceId = e.target.dataset.voiceId;
      await playVoiceSample(voiceId, e.target);
    });
  });
}

async function updateCharacterVoice(charId, voiceId) {
  try {
    const res = await fetch(`${API_BASE}/api/projects/${state.currentSlug}/characters/${charId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_id: voiceId }),
    });
    if (res.ok) {
      await loadCurrentProjectData();
    } else {
      const err = await res.json().catch(() => ({}));
      alert(`⚠️ Erro ao salvar voz: ${err.detail || res.statusText}`);
    }
  } catch (e) {
    console.error("Erro ao atualizar voz:", e);
    alert(`Erro de conexão ao salvar voz: ${e.message || e}`);
  }
}

async function playVoiceSample(voiceId, btnEl) {
  const originalText = btnEl.textContent;
  btnEl.disabled = true;
  btnEl.textContent = "⏳...";

  try {
    const res = await fetch(`${API_BASE}/api/voices/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_id: voiceId }),
    });
    if (res.ok) {
      const data = await res.json();
      const audioEl = document.getElementById("previewAudioElement");
      audioEl.src = `${API_BASE}${data.audio_url}`;
      audioEl.play();
    } else {
      const err = await res.json().catch(() => ({}));
      alert(`Erro ao reproduzir amostra sonora: ${err.detail || res.statusText}`);
    }
  } catch (e) {
    alert(`Falha ao reproduzir amostra sonora: ${e.message || e}`);
  } finally {
    btnEl.disabled = false;
    btnEl.textContent = originalText;
  }
}

function renderScriptTimeline() {
  const container = document.getElementById("scriptTimeline");
  const badge = document.getElementById("scriptBlocksBadge");

  if (!state.script || !state.script.blocks || state.script.blocks.length === 0) {
    container.innerHTML = '<div class="empty-state">O roteiro gerado aparecerá aqui.</div>';
    badge.textContent = "0 falas";
    return;
  }

  badge.textContent = `${state.script.blocks.length} falas`;
  container.innerHTML = "";

  state.script.blocks.forEach((b) => {
    const item = document.createElement("div");
    item.className = "script-item";

    const actingHtml = b.acting_prompt ? `<div class="script-item-acting">🎭 "${b.acting_prompt}"</div>` : "";

    item.innerHTML = `
      <div class="script-item-header">
        <span class="script-item-speaker">#${b.index} • [${b.character_id}]</span>
        <div class="script-badges">
          <span class="badge badge-info">${b.emotion}</span>
          <span class="badge badge-accent">${b.engine.toUpperCase()}</span>
        </div>
      </div>
      <div class="script-item-text">${b.text}</div>
      ${actingHtml}
    `;

    container.appendChild(item);
  });
}

// ==============================================================================
// 6. ETAPA 3: RENDERIZAÇÃO & AUDITORIA DE MOTORES
// ==============================================================================
async function startRender(quickTest = false) {
  if (state.isRendering) return;

  const btnQuick = document.getElementById("btnQuickRender");
  const btnFull = document.getElementById("btnFullRender");
  btnQuick.disabled = true;
  btnFull.disabled = true;
  state.isRendering = true;

  const progressWrapper = document.getElementById("renderProgressWrapper");
  const progressFill = document.getElementById("progressBarFill");
  const progressText = document.getElementById("progressStatusText");
  const progressPct = document.getElementById("progressPctText");

  progressWrapper.classList.remove("hidden");
  progressFill.style.width = "5%";
  progressText.textContent = quickTest ? "Iniciando teste rápido de 3 falas..." : "Iniciando renderização em segundo plano...";
  progressPct.textContent = "5%";

  const kokoroEq = document.getElementById("checkKokoroEq").checked;
  const roomTone = document.getElementById("checkRoomTone").checked;

  try {
    const res = await fetch(`${API_BASE}/api/projects/${state.currentSlug}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chapter_number: 1,
        quick_test: quickTest,
        enable_kokoro_eq: kokoroEq,
        enable_room_tone: roomTone,
        async_mode: true,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const errMsg = err.detail || res.statusText || "Erro ao iniciar a renderização.";
      progressText.textContent = `❌ ${errMsg}`;
      alert(`⚠️ Erro na Renderização: ${errMsg}`);
      btnQuick.disabled = false;
      btnFull.disabled = false;
      state.isRendering = false;
      return;
    }

    const initData = await res.json();
    const totalBlocks = initData.total_blocks || 1;

    // Polling a cada 1 segundo para acompanhar o status sem timeout HTTP
    const pollTimer = setInterval(async () => {
      try {
        const statusRes = await fetch(`${API_BASE}/api/projects/${state.currentSlug}/render/status`);
        if (!statusRes.ok) return;
        const job = await statusRes.json();

        if (job.status === "running") {
          const pct = Math.max(5, job.percent || Math.round((job.current_block / (job.total_blocks || totalBlocks)) * 90));
          progressFill.style.width = `${pct}%`;
          progressPct.textContent = `${pct}%`;
          let txt = `🎙️ Sintetizando fala ${job.current_block} de ${job.total_blocks || totalBlocks}...`;
          if (job.current_text) {
            txt += ` ("${job.current_text}...")`;
          }
          if (job.quota_exceeded) {
            txt += ` ⚠️ (Cota Gemini atingida: gravando com voz reserva)`;
          }
          progressText.textContent = txt;
        } else if (job.status === "completed") {
          clearInterval(pollTimer);
          progressFill.style.width = "100%";
          progressPct.textContent = "100%";

          if (job.quota_exceeded) {
            progressText.textContent = "⚠️ Concluído! Cota diária do Gemini atingida (voz reserva ativada nas falas restantes).";
            alert("⚠️ Atenção à Cota do Google:\nSua cota gratuita diária do Gemini TTS (10 requisições/dia) foi atingida.\nAs falas restantes foram gravadas automaticamente na voz de contingência (Edge-TTS) para não perder o áudio.");
          } else {
            progressText.textContent = "🎉 Masterização concluída com sucesso!";
          }

          if (job.result) {
            setupAudioPlayer(job.result);
            renderAuditList(job.result.audit || []);
          }

          btnQuick.disabled = false;
          btnFull.disabled = false;
          state.isRendering = false;
        } else if (job.status === "error") {
          clearInterval(pollTimer);
          progressText.textContent = `❌ ${job.error || "Erro durante a síntese."}`;
          alert(`⚠️ Erro na Renderização: ${job.error || "Erro desconhecido"}`);
          btnQuick.disabled = false;
          btnFull.disabled = false;
          state.isRendering = false;
        }
      } catch (errPoll) {
        console.error("Erro no polling de status:", errPoll);
      }
    }, 1000);

  } catch (e) {
    progressText.textContent = `❌ Falha de conexão: ${e.message || e}`;
    alert(`Falha de conexão durante a renderização: ${e.message || e}`);
    btnQuick.disabled = false;
    btnFull.disabled = false;
    state.isRendering = false;
  }
}

function setupAudioPlayer(renderData, autoPlay = true) {
  const audioEl = document.getElementById("mainAudioPlayer");
  const titleEl = document.getElementById("playerTitle");
  const metaEl = document.getElementById("playerMeta");
  const downloadBtn = document.getElementById("btnDownloadAudio");

  const fullAudioUrl = `${API_BASE}${renderData.audio_url}`;
  audioEl.src = fullAudioUrl;
  if (autoPlay) {
    audioEl.play().catch(() => {});
  }

  titleEl.textContent = renderData.filename;
  metaEl.textContent = `${renderData.size_kb} KB • ${renderData.blocks_count} falas masterizadas`;

  downloadBtn.href = fullAudioUrl;
  downloadBtn.classList.remove("disabled");
}

function resetAudioPlayer() {
  const audioEl = document.getElementById("mainAudioPlayer");
  const titleEl = document.getElementById("playerTitle");
  const metaEl = document.getElementById("playerMeta");
  const downloadBtn = document.getElementById("btnDownloadAudio");

  audioEl.src = "";
  titleEl.textContent = "Nenhum áudio gerado";
  metaEl.textContent = "Aguardando síntese";

  downloadBtn.href = "#";
  downloadBtn.classList.add("disabled");
}

function renderAuditList(auditItems) {
  const list = document.getElementById("auditList");
  list.innerHTML = "";

  if (!auditItems || auditItems.length === 0) {
    list.innerHTML = '<div class="empty-state">Nenhum dado de auditoria disponível.</div>';
    return;
  }

  auditItems.forEach((item) => {
    const row = document.createElement("div");
    row.className = "audit-item";

    let badgeClass = "engine-edge";
    let badgeText = "Edge-TTS";
    if (item.actual_engine === "kokoro") {
      badgeClass = "engine-kokoro";
      badgeText = "Kokoro HF";
    } else if (item.actual_engine === "gemini") {
      badgeClass = "engine-gemini";
      badgeText = "Gemini Acted";
    }

    const fallbackAlert = item.fallback_triggered
      ? `<span class="badge badge-warning" title="${item.fallback_reason}">⚠️ Contingência</span>`
      : "";

    row.innerHTML = `
      <span style="font-weight: 700; color: var(--text-muted)">#${item.index}</span>
      <div><span class="engine-badge ${badgeClass}">${badgeText}</span> ${fallbackAlert}</div>
      <div style="font-weight: 600">[${item.character_id}]</div>
      <div style="color: var(--text-secondary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap">"${item.text}"</div>
    `;

    list.appendChild(row);
  });
}

// ==============================================================================
// 7. EVENT LISTENERS GERAIS
// ==============================================================================
function initEventListeners() {
  // Navegação de Etapas
  document.querySelectorAll(".step-btn").forEach((btn) => {
    btn.addEventListener("click", () => setStep(parseInt(btn.dataset.step)));
  });

  // Botão de avanço da Etapa 1 para Etapa 2
  document.getElementById("btnGoToStep2").addEventListener("click", () => setStep(2));

  // Dropzone de Arquivos
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");

  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) handleFileSelected(e.target.files[0]);
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  });

  // Botão de Extração com Escopo de PDF
  document.getElementById("btnExtractScope").addEventListener("click", extractDocumentScope);

  // Controle de limite de parágrafos
  const checkImportAll = document.getElementById("checkImportAll");
  const limitWrapper = document.getElementById("limitParagsWrapper");
  if (checkImportAll && limitWrapper) {
    checkImportAll.addEventListener("change", (e) => {
      limitWrapper.classList.toggle("hidden", e.target.checked);
    });
  }

  // Contador de palavras do textarea e auto-save com debounce
  let textSaveTimeout = null;
  document.getElementById("curatedTextArea").addEventListener("input", (e) => {
    updateTextMetrics(e.target.value);
    clearTimeout(textSaveTimeout);
    textSaveTimeout = setTimeout(() => {
      saveProjectText(e.target.value);
    }, 800);
  });

  // Botão de Direção
  document.getElementById("btnRunDirector").addEventListener("click", runDirector);

  // Botões de Renderização
  document.getElementById("btnQuickRender").addEventListener("click", () => startRender(true));
  document.getElementById("btnFullRender").addEventListener("click", () => startRender(false));

  // Seletor de Projeto Ativo
  document.getElementById("projectSelect").addEventListener("change", async (e) => {
    state.currentSlug = e.target.value;
    await loadCurrentProjectData();
  });

  // Botão de Excluir Projeto
  const btnDelete = document.getElementById("btnDeleteProject");
  if (btnDelete) {
    btnDelete.addEventListener("click", async () => {
      if (!state.currentSlug) return;
      const ok = confirm(`Tem certeza que deseja excluir o projeto "${state.currentSlug}"?\nTodos os roteiros, áudios e textos deste projeto serão excluídos permanentemente.`);
      if (!ok) return;

      try {
        const res = await fetch(`${API_BASE}/api/projects/${state.currentSlug}`, {
          method: "DELETE",
        });
        if (res.ok) {
          state.currentSlug = null;
          await loadProjects();
          await loadCurrentProjectData();
          alert("Projeto excluído com sucesso!");
        } else {
          const err = await res.json().catch(() => ({}));
          alert(`Erro ao excluir projeto: ${err.detail || res.statusText}`);
        }
      } catch (e) {
        alert(`Falha ao excluir projeto: ${e.message || e}`);
      }
    });
  }

  // Modais
  const modalSettings = document.getElementById("settingsModal");
  document.getElementById("btnOpenSettings").addEventListener("click", () => modalSettings.classList.remove("hidden"));
  document.getElementById("btnCloseSettings").addEventListener("click", () => modalSettings.classList.add("hidden"));

  const modalNewProj = document.getElementById("newProjectModal");
  document.getElementById("btnNewProject").addEventListener("click", () => modalNewProj.classList.remove("hidden"));
  document.getElementById("btnCloseNewProject").addEventListener("click", () => modalNewProj.classList.add("hidden"));

  // Salvar Chave API
  document.getElementById("btnSaveApiKey").addEventListener("click", async () => {
    const key = document.getElementById("inputApiKey").value.trim();
    if (!key) return alert("Insira uma chave.");
    try {
      const res = await fetch(`${API_BASE}/api/config/key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key }),
      });
      if (res.ok) {
        alert("Chave salva com sucesso!");
        modalSettings.classList.add("hidden");
        await checkBackendStatus();
      } else {
        const err = await res.json().catch(() => ({}));
        alert(`Erro ao salvar chave: ${err.detail || res.statusText}`);
      }
    } catch (e) {
      alert(`Falha ao salvar chave: ${e.message || e}`);
    }
  });

  // Confirmar Novo Projeto
  document.getElementById("btnConfirmNewProject").addEventListener("click", async () => {
    const title = document.getElementById("newProjTitle").value.trim();
    const slug = document.getElementById("newProjSlug").value.trim();
    const mode = document.getElementById("newProjMode").value;
    const strategy = document.getElementById("newProjStrategy").value;

    if (!title || !slug) return alert("Preencha título e slug.");

    try {
      const res = await fetch(`${API_BASE}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, slug, mode, engine_strategy: strategy }),
      });
      if (res.ok) {
        modalNewProj.classList.add("hidden");
        state.currentSlug = slug;
        await loadProjects();
        await loadCurrentProjectData();
      } else {
        const err = await res.json().catch(() => ({}));
        alert(`Erro ao criar projeto: ${err.detail || res.statusText}`);
      }
    } catch (e) {
      alert(`Falha ao criar projeto: ${e.message || e}`);
    }
  });
}
