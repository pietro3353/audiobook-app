"""Extrator Universal de Textos e Algoritmo de Cura de Documentos.

Suporta arquivos .txt, .md, .pdf e .epub com:
1. Remoção de cabeçalhos, rodapés e números de página isolados.
2. Desfazer hifenizações de quebra de linha (ex: 'transfor-\\nmação' -> 'transformação').
3. Reconstrução de parágrafos reais (unir linhas quebradas artificialmente em PDFs).
4. Detecção automática de capítulos e seções.
5. Chunker semântico em lotes de 5 a 8 parágrafos.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ==============================================================================
# ALGORITMO DE CURA DE TEXTO E RECONSTRUÇÃO DE PARÁGRAFOS
# ==============================================================================


def cure_text(raw_text: str) -> str:
    """
    Higieniza o texto bruto de PDFs/EPUBs:
    - Desfaz hifenizações no final de linhas.
    - Remove números de página e rodapés soltos.
    - Une linhas quebradas que pertencem ao mesmo parágrafo.
    - Preserva marcações de diálogo e pontuação final.
    """
    if not raw_text:
        return ""

    # 1. Normaliza quebras de linha Windows/Mac para Unix
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Desfaz hifenização de fim de linha (ex: 'desenvol-\\nver' -> 'desenvolver')
    text = re.sub(r"(\w+)-\n\s*(\w+)", r"\1\2", text)

    linhas = text.split("\n")
    linhas_curadas: List[str] = []

    # Regex para identificar números de página soltos ou cabeçalhos recorrentes
    padrao_pagina = re.compile(
        r"^\s*(?:p[áa]g(?:ina)?\.?\s*)?\d+(?:\s*(?:de|/)\s*\d+)?\s*$",
        re.IGNORECASE,
    )

    for linha in linhas:
        l_strip = linha.strip()

        # Descarta linhas vazias ou números de página isolados
        if not l_strip:
            linhas_curadas.append("")
            continue
        if padrao_pagina.match(l_strip):
            continue

        linhas_curadas.append(l_strip)

    # 3. Reconstrução de Parágrafos:
    # Em PDFs, cada linha visual tem \n. Se a linha não terminar com pontuação forte
    # (., !, ?, :, ", ”, —) e a próxima linha não iniciar com travessão de diálogo,
    # as duas linhas devem ser concatenadas com um espaço.
    paragrafos: List[str] = []
    buffer_paragrafo: List[str] = []

    pontuacao_terminal = (".", "!", "?", ":", "…", "—", '"', "”", "'")

    for linha in linhas_curadas:
        if not linha:
            # Linha em branco sinaliza fim de parágrafo
            if buffer_paragrafo:
                paragrafos.append(" ".join(buffer_paragrafo).strip())
                buffer_paragrafo = []
            continue

        # Início de fala com travessão em parágrafo novo
        eh_inicio_dialogo = linha.startswith(("-", "—", "–"))

        if eh_inicio_dialogo and buffer_paragrafo:
            # Conclui o parágrafo anterior antes de abrir diálogo
            paragrafos.append(" ".join(buffer_paragrafo).strip())
            buffer_paragrafo = [linha]
            continue

        if not buffer_paragrafo:
            buffer_paragrafo.append(linha)
        else:
            linha_anterior = buffer_paragrafo[-1]
            termina_com_pontuacao = any(linha_anterior.endswith(p) for p in pontuacao_terminal)

            if termina_com_pontuacao:
                # O parágrafo anterior terminou de fato
                paragrafos.append(" ".join(buffer_paragrafo).strip())
                buffer_paragrafo = [linha]
            else:
                # Linha quebrada no meio da frase: une à frase atual
                buffer_paragrafo.append(linha)

    if buffer_paragrafo:
        paragrafos.append(" ".join(buffer_paragrafo).strip())

    # 4. Limpeza de múltiplos espaços internos
    paragrafos_finais = [
        re.sub(r"[ \t]+", " ", p).strip()
        for p in paragrafos
        if p.strip()
    ]

    return "\n\n".join(paragrafos_finais)


# ==============================================================================
# EXTRATORES ESPECÍFICOS POR FORMATO
# ==============================================================================


def extract_from_txt_or_md(file_path: Path) -> str:
    """Lê arquivo de texto puro ou markdown com codificação resiliente."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Não foi possível decodificar o arquivo {file_path}")


def get_pdf_page_count(file_input: Any) -> int:
    """Retorna a contagem total de páginas de um arquivo PDF instantaneamente."""
    import fitz  # PyMuPDF

    if isinstance(file_input, bytes):
        doc = fitz.open(stream=file_input, filetype="pdf")
    else:
        doc = fitz.open(file_input)
    total = len(doc)
    doc.close()
    return total


def extract_from_pdf(
    file_input: Any,
    start_page: int = 1,
    end_page: Optional[int] = None,
) -> str:
    """Extrai texto de arquivo PDF ou buffer de bytes com suporte a intervalo de páginas."""
    import fitz  # PyMuPDF

    if isinstance(file_input, bytes):
        doc = fitz.open(stream=file_input, filetype="pdf")
    else:
        doc = fitz.open(file_input)

    total_paginas = len(doc)
    inicio = max(0, start_page - 1)
    fim = min(total_paginas, end_page) if end_page is not None else total_paginas

    paginas = []
    for num_pag in range(inicio, fim):
        pagina = doc[num_pag]
        paginas.append(pagina.get_text("text"))
    doc.close()
    return "\n\n".join(paginas)


def extract_from_epub(file_path: Path) -> str:
    """Extrai texto limpo de arquivo EPUB sem tags HTML."""
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    livro = epub.read_epub(str(file_path))
    textos = []

    for item in livro.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            texto_limpo = soup.get_text(separator="\n")
            if texto_limpo.strip():
                textos.append(texto_limpo)

    return "\n\n".join(textos)


def extract_file(file_path: str | Path) -> str:
    """Ponto de entrada único que detecta a extensão e cura o texto."""
    caminho = Path(file_path)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    sufixo = caminho.suffix.lower()

    if sufixo in (".txt", ".md"):
        bruto = extract_from_txt_or_md(caminho)
    elif sufixo == ".pdf":
        bruto = extract_from_pdf(caminho)
    elif sufixo == ".epub":
        bruto = extract_from_epub(caminho)
    else:
        raise ValueError(
            f"Extensão não suportada: '{sufixo}'. Use .txt, .md, .pdf ou .epub"
        )

    return cure_text(bruto)


# ==============================================================================
# DETECTOR DE CAPÍTULOS E CHUNKER SEMÂNTICO
# ==============================================================================

PADROES_CAPITULO = [
    re.compile(r"^(?:#{1,3}\s*)?(?:cap[íi]tulo|cap\.?)\s+([0-9ivxlcdm]+)(?:\s*[:.-]\s*(.*))?$", re.IGNORECASE),
    re.compile(r"^(?:#{1,3}\s*)?(?:chapter)\s+([0-9ivxlcdm]+)(?:\s*[:.-]\s*(.*))?$", re.IGNORECASE),
    re.compile(r"^(?:#{1,3}\s*)?(?:parte|livro)\s+([0-9ivxlcdm]+)(?:\s*[:.-]\s*(.*))?$", re.IGNORECASE),
    re.compile(r"^#{1,2}\s+([^#\n]+)$"),  # Headers markdown de nível 1 ou 2
]


def detect_chapters(text: str) -> List[Dict[str, Any]]:
    """
    Identifica capítulos no texto. Se nenhum capítulo explícito for detectado,
    retorna o texto integral como Capítulo 1.
    """
    linhas = text.split("\n\n")
    capitulos: List[Dict[str, Any]] = []

    capitulo_atual_num = 1
    capitulo_atual_titulo = "Início"
    buffer_capitulo: List[str] = []

    for bloco in linhas:
        bloco_strip = bloco.strip()
        eh_cabecalho = False
        titulo_detectado = ""

        # Verifica apenas blocos curtos (títulos raramente passam de 100 caracteres)
        if len(bloco_strip) <= 120 and "\n" not in bloco_strip:
            for padrao in PADROES_CAPITULO:
                match = padrao.match(bloco_strip)
                if match:
                    eh_cabecalho = True
                    titulo_detectado = bloco_strip.lstrip("#").strip()
                    break

        if eh_cabecalho:
            if buffer_capitulo:
                capitulos.append({
                    "chapter_number": capitulo_atual_num,
                    "title": capitulo_atual_titulo,
                    "content": "\n\n".join(buffer_capitulo).strip(),
                })
                capitulo_atual_num += 1
                buffer_capitulo = []
            capitulo_atual_titulo = titulo_detectado
        else:
            buffer_capitulo.append(bloco_strip)

    if buffer_capitulo:
        capitulos.append({
            "chapter_number": capitulo_atual_num,
            "title": capitulo_atual_titulo,
            "content": "\n\n".join(buffer_capitulo).strip(),
        })

    return capitulos if capitulos else [{
        "chapter_number": 1,
        "title": "Texto Completo",
        "content": text.strip(),
    }]


def chunk_chapter(
    chapter_content: str,
    max_paragraphs: int = 6,
    max_chars: int = 2500,
) -> List[Dict[str, Any]]:
    """
    Divide um capítulo em lotes (chunks) de 5 a 8 parágrafos (~1500 a 2500 caracteres),
    preservando a integridade das frases e garantindo tamanho ideal para a LLM.
    """
    paragrafos = [p.strip() for p in chapter_content.split("\n\n") if p.strip()]
    if not paragrafos:
        return []

    chunks: List[Dict[str, Any]] = []
    chunk_atual: List[str] = []
    chars_atual = 0

    for p in paragrafos:
        len_p = len(p)
        # Se ultrapassar o limite de parágrafos ou caracteres, fecha o lote atual
        if chunk_atual and (len(chunk_atual) >= max_paragraphs or chars_atual + len_p > max_chars):
            texto_chunk = "\n\n".join(chunk_atual)
            chunks.append({
                "chunk_index": len(chunks),
                "paragraphs": chunk_atual,
                "text": texto_chunk,
                "char_count": len(texto_chunk),
                "word_count": len(texto_chunk.split()),
            })
            chunk_atual = [p]
            chars_atual = len_p
        else:
            chunk_atual.append(p)
            chars_atual += len_p + 2

    if chunk_atual:
        texto_chunk = "\n\n".join(chunk_atual)
        chunks.append({
            "chunk_index": len(chunks),
            "paragraphs": chunk_atual,
            "text": texto_chunk,
            "char_count": len(texto_chunk),
            "word_count": len(texto_chunk.split()),
        })

    return chunks
