"""Normalizador Fonético PT-BR para Motores TTS (Kokoro, Edge-TTS e Gemini).

Converte siglas técnicas de TI/Dados, símbolos matemáticos/lógicos e algarismos
romanos em sua forma fonética por extenso para leitura fluida em português brasileiro,
sem alterar o texto exibido na interface do usuário.
"""

import re
from typing import Dict, Optional

# Mapeamento case-sensitive de siglas técnicas (ordenadas das mais específicas/plurais para as simples)
TECH_ACRONYMS_PTBR: Dict[str, str] = {
    "SGBDs": "Ésse Gê Bê Dês",
    "SGBD": "Ésse Gê Bê Dê",
    "NoSQL": "Nô Ésse Quê Éle",
    "SQL": "Ésse Quê Éle",
    "HTTPS": "Agá Tê Tê Pê Ésse",
    "HTTP": "Agá Tê Tê Pê",
    "OLTP": "Ó Éle Tê Pê",
    "OLAP": "Ó Éle A Pê",
    "LGPD": "Éle Gê Pê Dê",
    "JSON": "Jêison",
    "LLMs": "Éle Éle Êmes",
    "LLM": "Éle Éle Ême",
    "APIs": "A Pê Ís",
    "API": "A Pê Í",
    "KPIs": "Cá Pê Ís",
    "KPI": "Cá Pê Í",
    "ETL": "É Tê Éle",
    "ELT": "É Éle Tê",
    "XAI": "Êxis A Í",
    "NLP": "Êne Éle Pê",
    "CPU": "Cê Pê Ú",
    "GPU": "Gê Pê Ú",
    "CSV": "Cê Ésse Vê",
    "DW": "Dê Dáblio",
    "BI": "Bê Í",
    "IA": "I Á",
    "ML": "Ême Éle",
    "DL": "Dê Éle",
}

_CARDINAIS_UNIDADES = {
    1: "um",
    2: "dois",
    3: "três",
    4: "quatro",
    5: "cinco",
    6: "seis",
    7: "sete",
    8: "oito",
    9: "nove",
    10: "dez",
    11: "onze",
    12: "doze",
    13: "treze",
    14: "quatorze",
    15: "quinze",
    16: "dezesseis",
    17: "dezessete",
    18: "dezoito",
    19: "dezenove",
}

_CARDINAIS_DEZENAS = {
    20: "vinte",
    30: "trinta",
    40: "quarenta",
    50: "cinquenta",
    60: "sessenta",
    70: "setenta",
    80: "oitenta",
    90: "noventa",
    100: "cem",
}

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}

_VALID_ROMAN_RE = re.compile(
    r"^C?(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$"
)

_ROMAN_CONTEXT_RE = re.compile(
    r"\b(S[ée]culo|Cap[íi]tulo|Aula|Parte|Tomo|Volume|M[óo]dulo|Se[çc][ãa]o|Livro)\s+([IVXLC]+)\b",
    flags=re.IGNORECASE,
)


def roman_to_int(roman: str) -> Optional[int]:
    """Converte um algarismo romano válido (I a C) para inteiro."""
    r = roman.strip().upper()
    if not r or not _VALID_ROMAN_RE.match(r):
        return None
    total = 0
    prev = 0
    for ch in reversed(r):
        val = _ROMAN_VALUES.get(ch, 0)
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total if total > 0 else None


def int_to_ptbr(n: int) -> str:
    """Converte inteiros de 1 a 100 para leitura cardinal em português."""
    if n in _CARDINAIS_UNIDADES:
        return _CARDINAIS_UNIDADES[n]
    if n in _CARDINAIS_DEZENAS:
        return _CARDINAIS_DEZENAS[n]
    if 20 < n < 100:
        dezena = (n // 10) * 10
        unidade = n % 10
        return f"{_CARDINAIS_DEZENAS[dezena]} e {_CARDINAIS_UNIDADES[unidade]}"
    return str(n)


def _replace_roman_after_keyword(match: re.Match) -> str:
    prefixo = match.group(1)
    romano = match.group(2)
    # Apenas converte se o numeral romano estiver em maiúsculas no original
    if not romano.isupper():
        return match.group(0)
    valor = roman_to_int(romano)
    if valor is None:
        return match.group(0)
    return f"{prefixo} {int_to_ptbr(valor)}"


def normalize_phonetics_ptbr(text: str) -> str:
    """
    Aplica normalização fonética para português brasileiro:
    1. Símbolos matemáticos e setas (>=, <=, !=, ->, ➔).
    2. Algarismos romanos após substantivos clássicos (Século XXI, Capítulo IV, Aula III, Parte II).
    3. Siglas técnicas case-sensitive com fronteira de palavra (SGBD, SQL, NoSQL, ETL, DW, XAI, etc.).
    """
    if not text:
        return ""

    t = text

    # 1. Símbolos matemáticos e lógicos
    t = t.replace(">=", " maior ou igual a ")
    t = t.replace("<=", " menor ou igual a ")
    t = t.replace("!=", " diferente de ")
    t = t.replace("->", ", levando a ")
    t = t.replace("➔", ", levando a ")

    # 2. Algarismos romanos após termos clássicos
    t = _ROMAN_CONTEXT_RE.sub(_replace_roman_after_keyword, t)

    # 3. Siglas técnicas (case-sensitive, com fronteira de palavra \b)
    for sigla, fonetica in TECH_ACRONYMS_PTBR.items():
        t = re.sub(rf"\b{re.escape(sigla)}\b", fonetica, t)

    # Limpa espaços múltiplos gerados por substituições de operadores
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([,;:!?])", r"\1", t)
    return t.strip()
