"""FastAPI Backend Server para o AudioBook Studio AI.

Expõe endpoints REST para:
- Extração de documentos e PDFs (com contagem e filtro de páginas)
- Gestão de Projetos e Bíblia de Personagens
- Catálogo de Vozes e prévia sonora de 2 segundos
- Direção Cênica (Gemini LLM ou Modo Express)
- Renderização e Masterização de Áudio (Teste 3 Falas ou Capítulo Completo)
- Auditoria de Motores (transparência de síntese)
- Serviço de arquivos estáticos do frontend (docs/) e streaming de MP3s
"""

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

import src
from src.director import Director
from src.extractor import (
    cure_text,
    detect_chapters,
    extract_file,
    extract_from_pdf,
    get_pdf_page_count,
)
from src.mixer import AudioMixer
from src.models import ChapterScript, ProjectMetadata, SpeechBlock
from src.project_manager import ProjectManager
from src.synthesizer import Synthesizer
from src.voices import VOICE_CATALOG, find_fallback_voice, list_voices

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "docs"
DATA_DIR = BASE_DIR / "data"

# Inicialização da aplicação FastAPI
app = FastAPI(
    title="AudioBook Studio AI API",
    description="Motor de Produção de Audiolivros e Rádio-Teatro com IA",
    version="1.0.0",
)

# Habilita CORS para permitir acessos locais e do GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializa instâncias globais ancoradas ao diretório raiz
pm = ProjectManager(base_dir=DATA_DIR / "projects")
mixer = AudioMixer()


# ==============================================================================
# SCHEMAS PYDANTIC PARA REQUISIÇÕES
# ==============================================================================

class SaveKeyRequest(BaseModel):
    api_key: str


class CreateProjectRequest(BaseModel):
    slug: str
    title: str
    mode: str = "fiction"
    engine_strategy: str = "hybrid"


class UpdateCharacterRequest(BaseModel):
    voice_id: str
    personality: Optional[str] = None
    acting_style: Optional[str] = None


class DirectChapterRequest(BaseModel):
    chapter_number: int = 1
    chapter_title: str = "Capítulo 01"
    chapter_content: str
    force_express: bool = False


class RenderChapterRequest(BaseModel):
    chapter_number: int = 1
    quick_test: bool = False  # True = 3 primeiras falas
    enable_kokoro_eq: bool = True
    enable_room_tone: bool = True


class VoicePreviewRequest(BaseModel):
    voice_id: str
    sample_text: Optional[str] = None


class SaveTextRequest(BaseModel):
    text: str


# ==============================================================================
# 1. ROTAS DE STATUS & CONFIGURAÇÕES
# ==============================================================================

@app.get("/api/status")
def get_system_status():
    """Retorna o status do servidor, checagem de chave e modelos locais."""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    tem_gemini = bool(gemini_key and gemini_key != "sua_chave_api_aqui")
    
    kokoro_model = DATA_DIR / "models" / "kokoro-v1.0.onnx"
    kokoro_voices = DATA_DIR / "models" / "voices-v1.0.bin"
    tem_kokoro = kokoro_model.exists() and kokoro_voices.exists()

    return {
        "status": "online",
        "gemini_active": tem_gemini,
        "kokoro_local_ready": tem_kokoro,
        "ffmpeg_ready": bool(shutil.which(mixer.ffmpeg_path) or Path(mixer.ffmpeg_path).exists()),
    }


@app.post("/api/config/key")
def save_gemini_key(req: SaveKeyRequest):
    """Salva a chave da API do Gemini no arquivo .env e atualiza em memória."""
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Chave não pode ser vazia.")

    os.environ["GEMINI_API_KEY"] = key
    env_file = BASE_DIR / ".env"
    lines = []
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("GEMINI_API_KEY="):
                    lines.append(line)
    lines.append(f"GEMINI_API_KEY={key}\n")
    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return {"success": True, "message": "Chave API salva com sucesso no .env."}


# ==============================================================================
# 2. ROTAS DE PROJETOS & METADADOS
# ==============================================================================

@app.get("/api/projects")
def list_projects():
    """Lista todos os projetos cadastrados."""
    slugs = pm.list_projects()
    projetos = []
    for s in slugs:
        meta = pm.load_metadata(s)
        if meta:
            projetos.append(meta.model_dump())
    return {"projects": projetos}


@app.post("/api/projects")
def create_project(req: CreateProjectRequest):
    """Cria um novo workspace de projeto."""
    slug = req.slug.strip().lower()
    if not slug:
        raise HTTPException(status_code=400, detail="Slug inválido.")
    
    meta = pm.create_project(
        slug=slug,
        title=req.title.strip(),
        mode=req.mode,
        engine_strategy=req.engine_strategy,
    )
    return {"success": True, "project": meta.model_dump()}


@app.get("/api/projects/{slug}")
def get_project(slug: str):
    """Obtém os metadados de um projeto específico."""
    meta = pm.load_metadata(slug)
    if not meta:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    return meta.model_dump()


@app.delete("/api/projects/{slug}")
def delete_project(slug: str):
    """Exclui permanentemente um projeto e todos os seus arquivos."""
    if not pm.project_exists(slug):
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    sucesso = pm.delete_project(slug)
    if not sucesso:
        raise HTTPException(status_code=500, detail="Erro ao excluir a pasta do projeto.")
    return {"success": True, "message": f"Projeto '{slug}' excluído com sucesso."}


@app.get("/api/projects/{slug}/text")
def get_project_text(slug: str):
    """Retorna o texto de trabalho atualmente associado ao projeto."""
    if not pm.project_exists(slug):
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    texto = pm.load_source_text(slug)
    palavras = len(texto.strip().split()) if texto.strip() else 0
    paragrafos = len([p for p in texto.split("\n\n") if p.strip()]) if texto.strip() else 0
    return {
        "slug": slug,
        "text": texto,
        "words_count": palavras,
        "paragraphs_count": paragrafos,
    }


@app.put("/api/projects/{slug}/text")
def update_project_text(slug: str, req: SaveTextRequest):
    """Salva/atualiza o texto de trabalho do projeto."""
    if not pm.project_exists(slug):
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    pm.save_source_text(slug, req.text)
    return {"success": True, "message": "Texto salvo com sucesso."}


@app.get("/api/projects/{slug}/audio")
def get_project_audio_info(slug: str):
    """Verifica se o projeto já possui áudio masterizado gerado."""
    if not pm.project_exists(slug):
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    output_dir = pm.get_project_dir(slug) / "output"
    cap1_mp3 = output_dir / "cap_01.mp3"
    demo_mp3 = output_dir / "demo_teste_3_falas.mp3"
    
    alvo = cap1_mp3 if cap1_mp3.exists() else (demo_mp3 if demo_mp3.exists() else None)
    if not alvo:
        return {"has_audio": False}

    script = pm.load_chapter_script(slug, 1)
    blocks_count = len(script.blocks) if script and script.blocks else 0
    
    return {
        "has_audio": True,
        "audio_url": f"/api/audio/projects/{slug}/{alvo.name}",
        "filename": alvo.name,
        "size_kb": round(alvo.stat().st_size / 1024, 1),
        "blocks_count": blocks_count,
    }


@app.get("/api/projects/{slug}/bible")
def get_character_bible(slug: str):
    """Retorna a Bíblia de Personagens do projeto."""
    bible = pm.load_character_bible(slug)
    return bible.model_dump()


@app.put("/api/projects/{slug}/characters/{char_id}")
@app.put("/api/projects/{slug}/bible/character/{char_id}")
def update_character(slug: str, char_id: str, req: UpdateCharacterRequest):
    """Atualiza permanentemente a voz ou atributos de um personagem na Bíblia e propaga para os roteiros."""
    try:
        char = pm.update_character_voice(
            slug=slug,
            char_id=char_id,
            voice_id=req.voice_id,
            personality=req.personality,
            acting_style=req.acting_style,
        )
        return {"success": True, "character": char.model_dump()}
    except KeyError as ke:
        raise HTTPException(status_code=404, detail=str(ke))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar personagem: {str(e)}")


@app.get("/api/projects/{slug}/script/{chapter_number}")
def get_chapter_script(slug: str, chapter_number: int):
    """Retorna o roteiro estruturado de um capítulo."""
    script = pm.load_chapter_script(slug, chapter_number)
    if not script:
        return {"exists": False, "script": None}
    return {"exists": True, "script": script.model_dump()}


# ==============================================================================
# 3. ROTAS DE CATÁLOGO DE VOZES & PREVIEW (AMOSTRA 2s)
# ==============================================================================

@app.get("/api/voices")
def get_voices():
    """Retorna o catálogo completo de vozes com metadados."""
    catalogo = []
    for v in VOICE_CATALOG.values():
        catalogo.append({
            "id": v.id,
            "name": v.name,
            "engine": v.engine,
            "gender": v.gender,
            "apparent_age": v.apparent_age,
            "accent": v.accent,
            "timbre": v.timbre,
            "is_blend": v.is_blend,
            "description": v.description,
        })
    return {"voices": catalogo}


@app.post("/api/voices/preview")
async def generate_voice_preview(req: VoicePreviewRequest):
    """Gera amostra curta de 2 segundos para teste de voz."""
    synth = Synthesizer(gemini_api_key=os.getenv("GEMINI_API_KEY", ""))
    sample_file = await synth.generate_voice_sample(
        voice_id=req.voice_id,
        sample_text=req.sample_text,
    )
    if not sample_file.exists():
        raise HTTPException(status_code=500, detail="Falha ao gerar amostra de voz.")

    return {
        "audio_url": f"/api/audio/sample/{sample_file.name}",
        "filename": sample_file.name,
    }


# ==============================================================================
# 4. ROTAS DE EXTRAÇÃO DE DOCUMENTOS (PDF COM INTERVALO DE PÁGINAS)
# ==============================================================================

@app.post("/api/extract/pdf/page-count")
async def get_pdf_pages(file: UploadFile = File(...)):
    """Lê instantaneamente o total de páginas de um arquivo PDF."""
    try:
        conteudo = await file.read()
        if not conteudo:
            raise HTTPException(status_code=400, detail="O arquivo enviado está vazio (0 bytes).")
        total = get_pdf_page_count(conteudo)
        return {"filename": file.filename, "total_pages": total}
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao analisar o arquivo PDF: {str(e)}")


@app.post("/api/extract")
async def extract_and_cure_document(
    file: UploadFile = File(...),
    start_page: int = Form(1),
    end_page: Optional[int] = Form(None),
    max_paragraphs: Optional[int] = Form(None),
):
    """Extrai e cura texto de arquivo PDF, EPUB, TXT ou MD com controle de escopo."""
    try:
        conteudo = await file.read()
        if not conteudo:
            raise HTTPException(status_code=400, detail="O arquivo enviado está vazio (0 bytes).")
        nome_arq = file.filename.lower() if file.filename else ""

        if nome_arq.endswith(".pdf"):
            raw_text = extract_from_pdf(conteudo, start_page=start_page, end_page=end_page)
        elif nome_arq.endswith((".txt", ".md")):
            raw_text = conteudo.decode("utf-8", errors="ignore")
        elif nome_arq.endswith(".epub"):
            temp_epub = Path("data") / "temp" / f"_upload_{file.filename}"
            temp_epub.parent.mkdir(parents=True, exist_ok=True)
            with open(temp_epub, "wb") as f_ep:
                f_ep.write(conteudo)
            try:
                raw_text = extract_file(temp_epub)
            finally:
                if temp_epub.exists():
                    temp_epub.unlink()
        else:
            raise HTTPException(status_code=400, detail="Formato não suportado. Use PDF, EPUB, TXT ou MD.")

        texto_curado = cure_text(raw_text)
        if not texto_curado.strip():
            raise HTTPException(
                status_code=400,
                detail="Texto extraído está vazio. Verifique se o arquivo possui texto legível (não escaneado) nas páginas escolhidas."
            )

        paragrafos = [p for p in texto_curado.split("\n\n") if p.strip()]
        if max_paragraphs and max_paragraphs > 0 and len(paragrafos) > max_paragraphs:
            texto_curado = "\n\n".join(paragrafos[:max_paragraphs])
            paragrafos = paragrafos[:max_paragraphs]

        capitulos = detect_chapters(texto_curado)

        return {
            "filename": file.filename,
            "curated_text": texto_curado,
            "paragraphs_count": len(paragrafos),
            "chapters_detected": len(capitulos),
            "chapters": capitulos,
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na extração do documento: {str(e)}")


# ==============================================================================
# 5. ROTAS DO DIRETOR CÊNICO
# ==============================================================================

@app.post("/api/projects/{slug}/direct")
def direct_scene(slug: str, req: DirectChapterRequest):
    """Executa a Direção Cênica e gera o ChapterScript estruturado."""
    try:
        # Garante que o projeto e sua pasta existam no workspace
        meta = pm.load_metadata(slug)
        if not meta:
            meta = pm.create_project(
                slug=slug,
                title=slug.replace("_", " ").title(),
                mode="fiction",
                engine_strategy="hybrid",
            )

        if not req.chapter_content.strip():
            raise HTTPException(status_code=400, detail="O texto da cena a ser dirigida não pode estar vazio.")

        director = Director(project_manager=pm)
        script = director.direct_chapter(
            project_slug=slug,
            chapter_number=req.chapter_number,
            chapter_title=req.chapter_title,
            chapter_content=req.chapter_content,
            force_express=req.force_express,
        )
        # Remove áudios renderizados antigos deste capítulo para não tocar áudio de texto anterior
        out_cap = pm.get_project_dir(slug) / "output" / f"cap_{req.chapter_number:02d}.mp3"
        out_demo = pm.get_project_dir(slug) / "output" / "demo_teste_3_falas.mp3"
        if out_cap.exists():
            out_cap.unlink(missing_ok=True)
        if out_demo.exists():
            out_demo.unlink(missing_ok=True)

        bible = pm.load_character_bible(slug)
        return {
            "success": True,
            "script": script.model_dump(),
            "characters": [c.model_dump() for c in bible.characters.values()],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na execução do Diretor: {str(e)}")


# ==============================================================================
# 6. ROTAS DE RENDERIZAÇÃO & AUDITORIA DE MOTORES
# ==============================================================================

@app.post("/api/projects/{slug}/render")
async def render_audio(slug: str, req: RenderChapterRequest):
    """
    Renderiza o capítulo (Completo ou Teste Rápido de 3 Falas) com transparência
    total de qual motor gerou cada fala e masterização de estúdio.
    """
    try:
        script_original = pm.load_chapter_script(slug, req.chapter_number)
        if not script_original or not script_original.blocks:
            raise HTTPException(status_code=400, detail="Nenhum roteiro encontrado para renderizar.")

        blocos_alvo = script_original.blocks[:3] if req.quick_test else script_original.blocks
        subscript = ChapterScript(
            chapter_number=script_original.chapter_number,
            title=f"{script_original.title} ({'3 Falas' if req.quick_test else 'Completo'})",
            blocks=blocos_alvo,
            total_chars=sum(len(b.text) for b in blocos_alvo),
        )

        # Garante sincronização estrita com a Bíblia de Personagens mais recente
        bible = pm.load_character_bible(slug)
        for b in subscript.blocks:
            char = bible.get(b.character_id) or (bible.get("narrador") if b.character_id in ("narrador", "narracao") else None)
            if char:
                b.voice_id = char.voice_id
                b.engine = char.engine
                b.blend_recipe = char.blend_recipe
                b.fallback_voice_id = char.fallback_voice_id
                b.fallback_engine = char.fallback_engine

        synth = Synthesizer(gemini_api_key=os.getenv("GEMINI_API_KEY", ""))
        temp_dir = pm.get_project_dir(slug) / "temp" / f"cap_{subscript.chapter_number:02d}"

        # 1. Síntese concorrente
        chunks_brutos = await synth.synthesize_chapter(
            script=subscript,
            project_slug=slug,
            temp_dir=temp_dir,
        )

        # 2. Masterização acústica
        nome_saida = "demo_teste_3_falas.mp3" if req.quick_test else f"cap_{req.chapter_number:02d}.mp3"
        saida_final = pm.get_project_dir(slug) / "output" / nome_saida

        mixer.mix_chapter(
            script=subscript,
            raw_chunks=chunks_brutos,
            output_chapter_mp3=saida_final,
            enable_kokoro_eq=req.enable_kokoro_eq,
            enable_room_tone=req.enable_room_tone,
        )

        # Atualiza o script persistido com os campos de auditoria
        pm.save_chapter_script(slug, script_original)

        # Coleta dados de auditoria
        auditoria = []
        for b in subscript.blocks:
            auditoria.append({
                "index": b.index,
                "character_id": b.character_id,
                "actual_engine": b.actual_engine or b.engine,
                "actual_voice_id": b.actual_voice_id or b.voice_id,
                "fallback_triggered": b.fallback_triggered,
                "fallback_reason": b.fallback_reason,
                "text": b.text,
            })

        tamanho_kb = round(saida_final.stat().st_size / 1024, 1)

        return {
            "success": True,
            "audio_url": f"/api/audio/projects/{slug}/{saida_final.name}",
            "filename": saida_final.name,
            "size_kb": tamanho_kb,
            "blocks_count": len(subscript.blocks),
            "audit": auditoria,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro durante a renderização de áudio: {str(e)}")


# ==============================================================================
# 7. ROTAS DE STREAMING DE ÁUDIO
# ==============================================================================

@app.get("/api/audio/projects/{slug}/{filename}")
def stream_project_audio(slug: str, filename: str):
    """Transmite o arquivo MP3 masterizado de um projeto."""
    arq = pm.get_project_dir(slug) / "output" / filename
    if not arq.exists():
        raise HTTPException(status_code=404, detail="Arquivo de áudio não encontrado.")
    return FileResponse(path=str(arq), media_type="audio/mpeg", filename=filename)


@app.get("/api/audio/sample/{filename}")
def stream_sample_audio(filename: str):
    """Transmite o arquivo MP3 de prévia de voz."""
    arq = DATA_DIR / "temp" / "samples" / filename
    if not arq.exists():
        raise HTTPException(status_code=404, detail="Amostra de áudio não encontrada.")
    return FileResponse(path=str(arq), media_type="audio/mpeg", filename=filename)


# ==============================================================================
# 8. SERVIÇO DE ARQUIVOS ESTÁTICOS DO FRONTEND (docs/)
# ==============================================================================

if DOCS_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DOCS_DIR), html=True), name="frontend")
