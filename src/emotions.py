"""Matriz Acústica de Emoções, Cálculo de Delta e Clamping de Segurança.

Transforma rótulos emocionais da cena em parâmetros acústicos para Edge-TTS/Kokoro
e em instruções de atuação dramática para o Gemini Audio.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class EmotionProfile:
    """Perfil acústico e cênico de uma emoção."""

    label: str
    rate_delta: int  # Pontos percentuais (ex: +5 para +5%, -8 para -8%)
    pitch_delta: int  # Hz de deslocamento (ex: +3 para +3Hz, -4 para -4Hz)
    volume_delta: int  # Pontos percentuais de volume
    pause_multiplier: float  # Multiplicador do tempo de respiração padrão
    acting_instruction: str  # Descrição cênica (apenas informativa/UI; nunca enviada como texto ao TTS)


# ==============================================================================
# LIMITES DE SEGURANÇA (ACOUSTIC CLAMPING)
# Evitam distorções robóticas ou estalos na síntese neural
# ==============================================================================
RATE_MIN: int = -10
RATE_MAX: int = 12

PITCH_MIN: int = -3
PITCH_MAX: int = 3

VOLUME_MIN: int = -15
VOLUME_MAX: int = 10


# ==============================================================================
# TABELA CALIBRADA DE EMOÇÕES (DELTAS SUTIS E NATURAIS)
# ==============================================================================
EMOTION_MATRIX: Dict[str, EmotionProfile] = {
    "neutro": EmotionProfile(
        label="neutro",
        rate_delta=0,
        pitch_delta=0,
        volume_delta=0,
        pause_multiplier=1.0,
        acting_instruction="Tom equilibrado, natural e claro, sem carga dramática excessiva.",
    ),
    "sussurro": EmotionProfile(
        label="sussurro",
        rate_delta=-4,
        pitch_delta=-1,
        volume_delta=-10,
        pause_multiplier=1.2,
        acting_instruction="Fale em tom de sussurro contido, próximo e abafado, como se temesse ser ouvido.",
    ),
    "tenso": EmotionProfile(
        label="tenso",
        rate_delta=3,
        pitch_delta=1,
        volume_delta=3,
        pause_multiplier=0.8,
        acting_instruction="Tom tenso, vigilante e em alerta. Frases rápidas e respiração curta.",
    ),
    "panico": EmotionProfile(
        label="panico",
        rate_delta=6,
        pitch_delta=2,
        volume_delta=6,
        pause_multiplier=0.7,
        acting_instruction="Voz desesperada e trêmula de pânico, respiração ofegante e fala entrecortada.",
    ),
    "raiva": EmotionProfile(
        label="raiva",
        rate_delta=4,
        pitch_delta=1,
        volume_delta=6,
        pause_multiplier=0.75,
        acting_instruction="Voz agressiva, firme e inflamada de fúria, com ênfase cortante nas palavras.",
    ),
    "tristeza": EmotionProfile(
        label="tristeza",
        rate_delta=-4,
        pitch_delta=-2,
        volume_delta=-6,
        pause_multiplier=1.3,
        acting_instruction="Voz lenta, abatida e embargada pelo luto ou pela melancolia profunda.",
    ),
    "alegria": EmotionProfile(
        label="alegria",
        rate_delta=4,
        pitch_delta=2,
        volume_delta=4,
        pause_multiplier=0.85,
        acting_instruction="Tom aberto, caloroso e luminoso, transmitindo felicidade genuína.",
    ),
    "ironia_sarcasmo": EmotionProfile(
        label="ironia_sarcasmo",
        rate_delta=-2,
        pitch_delta=1,
        volume_delta=0,
        pause_multiplier=1.1,
        acting_instruction="Tom irônico, sarcástico e debochado, com um sorriso cínico evidente na fala.",
    ),
    "solene": EmotionProfile(
        label="solene",
        rate_delta=-3,
        pitch_delta=-2,
        volume_delta=3,
        pause_multiplier=1.3,
        acting_instruction="Tom reverente, majestoso e cerimonioso, conferindo peso histórico e respeito.",
    ),
    "cansado_fraco": EmotionProfile(
        label="cansado_fraco",
        rate_delta=-6,
        pitch_delta=-2,
        volume_delta=-10,
        pause_multiplier=1.4,
        acting_instruction="Voz fraca, exausta e arrastada, como quem fala com esforço físico evidente.",
    ),
    "pensamento": EmotionProfile(
        label="pensamento",
        rate_delta=-3,
        pitch_delta=-1,
        volume_delta=-6,
        pause_multiplier=1.2,
        acting_instruction="Voz íntima de monólogo interno, suave, reflexiva e voltada para dentro.",
    ),
    "destaque_didatico": EmotionProfile(
        label="destaque_didatico",
        rate_delta=-2,
        pitch_delta=0,
        volume_delta=3,
        pause_multiplier=1.2,
        acting_instruction="Tom professoral, didático e articulado, enfatizando conceitos fundamentais com pausas precisas.",
    ),
    "misterio": EmotionProfile(
        label="misterio",
        rate_delta=-3,
        pitch_delta=-1,
        volume_delta=-4,
        pause_multiplier=1.3,
        acting_instruction="Tom misterioso e conspiratório, criando suspense com cadência paciente e enigmática.",
    ),
    "animado": EmotionProfile(
        label="animado",
        rate_delta=5,
        pitch_delta=2,
        volume_delta=5,
        pause_multiplier=0.8,
        acting_instruction="Tom eufórico, elétrico e vibrante, transbordando energia e urgência positiva.",
    ),
    "autoritario": EmotionProfile(
        label="autoritario",
        rate_delta=-2,
        pitch_delta=-1,
        volume_delta=6,
        pause_multiplier=1.0,
        acting_instruction="Comando inquestionável e imponente, voz grave, pausada e inflexível.",
    ),
}


# ==============================================================================
# PREFIXOS CURTOS DE ESTILO PARA O GEMINI TTS
# Regra: no máximo 3 palavras, sem ponto final, sempre seguidos de ':' + texto.
# Emoções neutras/didáticas NÃO recebem prefixo → texto puro → timbre 100% estável.
# ==============================================================================
GEMINI_TTS_PREFIXES: Dict[str, str] = {
    "sussurro": "Say in whisper",
    "tenso": "Say tensely",
    "panico": "Say panicked",
    "raiva": "Say angrily",
    "tristeza": "Say sadly",
    "alegria": "Say cheerfully",
    "ironia_sarcasmo": "Say sarcastically",
    "cansado_fraco": "Say wearily",
    "pensamento": "Say softly",
    "misterio": "Say mysteriously",
    "animado": "Say excitedly",
    "autoritario": "Say firmly",
}

NEUTRAL_EMOTIONS = {"neutro", "destaque_didatico", "solene"}


def get_tts_style_prefix(emotion_label: Optional[str]) -> str:
    """Retorna o prefixo curto de estilo do Gemini TTS ou '' para emoções neutras/didáticas."""
    if not emotion_label:
        return ""
    label = emotion_label.strip().lower()
    if label in NEUTRAL_EMOTIONS:
        return ""
    return GEMINI_TTS_PREFIXES.get(label, "")



# ==============================================================================
# CÁLCULO ACÚSTICO COM CLAMPING E ATUAÇÃO
# ==============================================================================


def clamp(value: int, min_val: int, max_val: int) -> int:
    """Trava o valor numérico dentro de um intervalo de segurança."""
    return max(min_val, min(value, max_val))


def get_emotion(emotion_label: str) -> EmotionProfile:
    """Busca o perfil da emoção ou retorna o padrão 'neutro' se não encontrado."""
    label_normalizado = emotion_label.strip().lower()
    return EMOTION_MATRIX.get(label_normalizado, EMOTION_MATRIX["neutro"])


def list_emotion_labels() -> List[str]:
    """Retorna a lista de todas as tags de emoção suportadas."""
    return list(EMOTION_MATRIX.keys())


def calculate_acoustic_parameters(
    baseline_rate_pct: int = 0,
    baseline_pitch_hz: int = 0,
    baseline_volume_pct: int = 0,
    emotion_label: str = "neutro",
    character_personality: str = "",
) -> Tuple[str, str, str, float, str]:
    """Calcula os parâmetros finais com Clamping e formata o acting_prompt.

    Retorna:
        rate_str: string para Edge-TTS (ex: "+3%" ou "-5%")
        pitch_str: string para Edge-TTS (ex: "+2Hz" ou "-4Hz")
        volume_str: string para Edge-TTS (ex: "+0%" ou "-10%")
        pause_multiplier: multiplicador de pausa (ex: 1.2)
        acting_prompt: prompt formatado para motores de atuação (Gemini)
    """
    emotion = get_emotion(emotion_label)

    # 1. Soma matemática: Baseline Fixo + Delta da Cena
    total_rate = baseline_rate_pct + emotion.rate_delta
    total_pitch = baseline_pitch_hz + emotion.pitch_delta
    total_volume = baseline_volume_pct + emotion.volume_delta

    # 2. Clamping Acústico
    final_rate = clamp(total_rate, RATE_MIN, RATE_MAX)
    final_pitch = clamp(total_pitch, PITCH_MIN, PITCH_MAX)
    final_volume = clamp(total_volume, VOLUME_MIN, VOLUME_MAX)

    # 3. Formatação em Strings compatíveis com SSML / Edge-TTS
    rate_str = f"{final_rate:+d}%"
    pitch_str = f"{final_pitch:+d}Hz"
    volume_str = f"{final_volume:+d}%"

    # 4. Descrição cênica informativa (exibida na UI/auditoria; NUNCA enviada como texto ao TTS)
    prompt_elementos = [emotion.acting_instruction]
    if character_personality:
        prompt_elementos.append(f"Personagem: {character_personality}")

    acting_prompt = " ".join(prompt_elementos)

    return rate_str, pitch_str, volume_str, emotion.pause_multiplier, acting_prompt
