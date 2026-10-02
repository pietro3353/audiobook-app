"""Catálogo unificado e inteligente de vozes com metadados para múltiplos motores (Edge-TTS, Kokoro-ONNX e Gemini Audio)."""

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

EngineType = Literal["edge", "kokoro", "gemini"]
GenderType = Literal["M", "F", "neutral"]
AgeGroup = Literal["crianca", "jovem", "adulto", "maduro"]
AccentType = Literal[
    "brasileiro",
    "portugues",
    "americano",
    "frances",
    "italiano",
    "alemao",
    "espanhol",
    "britanico",
    "asiatico",
]


@dataclass
class VoiceProfile:
    """Perfil completo de uma voz no banco de talentos."""

    id: str
    name: str
    engine: EngineType
    gender: GenderType
    apparent_age: AgeGroup
    accent: AccentType
    timbre: str
    engine_voice_id: str
    supports_acting_prompt: bool = False
    supports_pitch_rate: bool = True
    is_blend: bool = False
    blend_recipe: Optional[Dict[str, float]] = None
    description: str = ""


# ==============================================================================
# BANCO DE TALENTOS MULTI-MOTOR
# ==============================================================================

VOICE_CATALOG: Dict[str, VoiceProfile] = {
    # --------------------------------------------------------------------------
    # EDGE-TTS: Nativas do Brasil
    # --------------------------------------------------------------------------
    "edge_antonio": VoiceProfile(
        id="edge_antonio",
        name="Antônio",
        engine="edge",
        gender="M",
        apparent_age="maduro",
        accent="brasileiro",
        timbre="grave_sobrio",
        engine_voice_id="pt-BR-AntonioNeural",
        supports_pitch_rate=True,
        description="Voz masculina grave, aveludada e clássica. Padrão ideal para narração e homens adultos ou idosos.",
    ),
    "edge_francisca": VoiceProfile(
        id="edge_francisca",
        name="Francisca",
        engine="edge",
        gender="F",
        apparent_age="adulta",
        accent="brasileiro",
        timbre="expressivo_envolvente",
        engine_voice_id="pt-BR-FranciscaNeural",
        supports_pitch_rate=True,
        description="Voz feminina expressiva, com cadência literária refinada. Excelente para narradoras e mulheres maduras.",
    ),
    "edge_thalita": VoiceProfile(
        id="edge_thalita",
        name="Thalita",
        engine="edge",
        gender="F",
        apparent_age="jovem",
        accent="brasileiro",
        timbre="jovem_suave",
        engine_voice_id="pt-BR-ThalitaMultilingualNeural",
        supports_pitch_rate=True,
        description="Voz feminina jovem, doce e moderna. Com pitch elevado (+6Hz), simula com precisão crianças e meninas.",
    ),
    # --------------------------------------------------------------------------
    # EDGE-TTS: Portugal (Sotaque Lusitano)
    # --------------------------------------------------------------------------
    "edge_duarte": VoiceProfile(
        id="edge_duarte",
        name="Duarte",
        engine="edge",
        gender="M",
        apparent_age="adulto",
        accent="portugues",
        timbre="sobrio_lusitano",
        engine_voice_id="pt-PT-DuarteNeural",
        supports_pitch_rate=True,
        description="Voz masculina nativa de Portugal. Ideal para personagens portugueses ou contos clássicos.",
    ),
    "edge_raquel": VoiceProfile(
        id="edge_raquel",
        name="Raquel",
        engine="edge",
        gender="F",
        apparent_age="adulta",
        accent="portugues",
        timbre="suave_lusitano",
        engine_voice_id="pt-PT-RaquelNeural",
        supports_pitch_rate=True,
        description="Voz feminina de Portugal, dicção elegante e tom melódico.",
    ),
    # --------------------------------------------------------------------------
    # EDGE-TTS: Vozes Multilíngues (Sotaque Estrangeiro Autêntico)
    # --------------------------------------------------------------------------
    "edge_brian_us": VoiceProfile(
        id="edge_brian_us",
        name="Brian",
        engine="edge",
        gender="M",
        apparent_age="adulto",
        accent="americano",
        timbre="conversacional_amigavel",
        engine_voice_id="en-US-BrianMultilingualNeural",
        supports_pitch_rate=True,
        description="Americano falando português com leve sotaque descontraído e amigável.",
    ),
    "edge_andrew_us": VoiceProfile(
        id="edge_andrew_us",
        name="Andrew",
        engine="edge",
        gender="M",
        apparent_age="maduro",
        accent="americano",
        timbre="grave_confiante",
        engine_voice_id="en-US-AndrewMultilingualNeural",
        supports_pitch_rate=True,
        description="Americano maduro com timbre firme e autoritário lendo em português.",
    ),
    "edge_emma_us": VoiceProfile(
        id="edge_emma_us",
        name="Emma",
        engine="edge",
        gender="F",
        apparent_age="jovem",
        accent="americano",
        timbre="energica_clara",
        engine_voice_id="en-US-EmmaMultilingualNeural",
        supports_pitch_rate=True,
        description="Jovem americana entusiasmada falando português com sotaque nativo dos EUA.",
    ),
    "edge_ava_us": VoiceProfile(
        id="edge_ava_us",
        name="Ava",
        engine="edge",
        gender="F",
        apparent_age="adulta",
        accent="americano",
        timbre="expressiva_calorosa",
        engine_voice_id="en-US-AvaMultilingualNeural",
        supports_pitch_rate=True,
        description="Mulher adulta americana com dicção calorosa e expressiva lendo em português.",
    ),
    "edge_remy_fr": VoiceProfile(
        id="edge_remy_fr",
        name="Rémy",
        engine="edge",
        gender="M",
        apparent_age="adulto",
        accent="frances",
        timbre="expressivo_charme",
        engine_voice_id="fr-FR-RemyMultilingualNeural",
        supports_pitch_rate=True,
        description="Francês falando português com o clássico charme e cadência europeia.",
    ),
    "edge_vivienne_fr": VoiceProfile(
        id="edge_vivienne_fr",
        name="Vivienne",
        engine="edge",
        gender="F",
        apparent_age="adulta",
        accent="frances",
        timbre="suave_elegante",
        engine_voice_id="fr-FR-VivienneMultilingualNeural",
        supports_pitch_rate=True,
        description="Mulher francesa com timbre aveludado e elegante falando português.",
    ),
    "edge_giuseppe_it": VoiceProfile(
        id="edge_giuseppe_it",
        name="Giuseppe",
        engine="edge",
        gender="M",
        apparent_age="adulto",
        accent="italiano",
        timbre="caloroso_expressivo",
        engine_voice_id="it-IT-GiuseppeMultilingualNeural",
        supports_pitch_rate=True,
        description="Italiano expressivo e apaixonado lendo português com cadência melódica.",
    ),
    "edge_florian_de": VoiceProfile(
        id="edge_florian_de",
        name="Florian",
        engine="edge",
        gender="M",
        apparent_age="adulto",
        accent="alemao",
        timbre="firme_imponente",
        engine_voice_id="de-DE-FlorianMultilingualNeural",
        supports_pitch_rate=True,
        description="Alemão com tom firme, sério e imponente falando português.",
    ),
    "edge_seraphina_de": VoiceProfile(
        id="edge_seraphina_de",
        name="Seraphina",
        engine="edge",
        gender="F",
        apparent_age="adulta",
        accent="alemao",
        timbre="clara_precisa",
        engine_voice_id="de-DE-SeraphinaMultilingualNeural",
        supports_pitch_rate=True,
        description="Mulher alemã com articulação límpida e tom controlado lendo em português.",
    ),
    "edge_william_au": VoiceProfile(
        id="edge_william_au",
        name="William",
        engine="edge",
        gender="M",
        apparent_age="adulto",
        accent="britanico",
        timbre="aristocratico_sobrio",
        engine_voice_id="en-AU-WilliamMultilingualNeural",
        supports_pitch_rate=True,
        description="Timbre sóbrio com inflexão aristocrática anglo-saxã.",
    ),
    "edge_alvaro_es": VoiceProfile(
        id="edge_alvaro_es",
        name="Álvaro",
        engine="edge",
        gender="M",
        apparent_age="adulto",
        accent="espanhol",
        timbre="energico_latino",
        engine_voice_id="es-ES-AlvaroNeural",
        supports_pitch_rate=True,
        description="Espanhol com ritmo enérgico e pronúncia rica para personagens hispânicos.",
    ),
    "edge_elvira_es": VoiceProfile(
        id="edge_elvira_es",
        name="Elvira",
        engine="edge",
        gender="F",
        apparent_age="adulta",
        accent="espanhol",
        timbre="expressiva_vibrante",
        engine_voice_id="es-ES-ElviraNeural",
        supports_pitch_rate=True,
        description="Mulher espanhola vibrante e teatral.",
    ),
    # --------------------------------------------------------------------------
    # KOKORO-ONNX (Hugging Face - 100% Offline e Fusão de Vozes)
    # --------------------------------------------------------------------------
    "kokoro_dora": VoiceProfile(
        id="kokoro_dora",
        name="Dora",
        engine="kokoro",
        gender="F",
        apparent_age="jovem",
        accent="brasileiro",
        timbre="natural_cristalina",
        engine_voice_id="pf_dora",
        supports_pitch_rate=False,
        description="Voz feminina brasileira aberta e natural do Kokoro-82M.",
    ),
    "kokoro_alex": VoiceProfile(
        id="kokoro_alex",
        name="Alex",
        engine="kokoro",
        gender="M",
        apparent_age="adulto",
        accent="brasileiro",
        timbre="neutro_moderno",
        engine_voice_id="pm_alex",
        supports_pitch_rate=False,
        description="Voz masculina brasileira equilibrada, dinâmica e jovem-adulta.",
    ),
    "kokoro_santa": VoiceProfile(
        id="kokoro_santa",
        name="Santa",
        engine="kokoro",
        gender="M",
        apparent_age="maduro",
        accent="brasileiro",
        timbre="grave_pesado",
        engine_voice_id="pm_santa",
        supports_pitch_rate=False,
        description="Voz masculina envelhecida, profunda e pesada. Perfeita para idosos e mentores.",
    ),
    # Presets de Fusão Matemática (Voice Blending) do Kokoro
    "kokoro_blend_anciao": VoiceProfile(
        id="kokoro_blend_anciao",
        name="Mestre Ancião (Fusão)",
        engine="kokoro",
        gender="M",
        apparent_age="maduro",
        accent="brasileiro",
        timbre="anciao_sabio",
        engine_voice_id="blend_pm_santa_70_pm_alex_30",
        is_blend=True,
        blend_recipe={"pm_santa": 0.70, "pm_alex": 0.30},
        supports_pitch_rate=False,
        description="Fusão matemática: 70% Santa + 30% Alex. Cria um timbre único de senhor sábio ou ranzinza.",
    ),
    "kokoro_blend_jovem_dinamico": VoiceProfile(
        id="kokoro_blend_jovem_dinamico",
        name="Rapaz Dinâmico (Fusão)",
        engine="kokoro",
        gender="M",
        apparent_age="jovem",
        accent="brasileiro",
        timbre="agil_expressivo",
        engine_voice_id="blend_pm_alex_60_pf_dora_40",
        is_blend=True,
        blend_recipe={"pm_alex": 0.60, "pf_dora": 0.40},
        supports_pitch_rate=False,
        description="Fusão: 60% Alex + 40% Dora. Tom juvenil leve, ágil e vibrante.",
    ),
    "kokoro_blend_mulher_madura": VoiceProfile(
        id="kokoro_blend_mulher_madura",
        name="Matriarca (Fusão)",
        engine="kokoro",
        gender="F",
        apparent_age="maduro",
        accent="brasileiro",
        timbre="aveludada_profunda",
        engine_voice_id="blend_pf_dora_60_pm_santa_40",
        is_blend=True,
        blend_recipe={"pf_dora": 0.60, "pm_santa": 0.40},
        supports_pitch_rate=False,
        description="Fusão: 60% Dora + 40% Santa. Tom feminino maduro, aveludado e com presença cênica.",
    ),
    # --------------------------------------------------------------------------
    # GEMINI AUDIO TTS (Google AI Studio - 30+ Vozes com Atuação por Prompt)
    # --------------------------------------------------------------------------
    "gemini_puck": VoiceProfile(
        id="gemini_puck",
        name="Puck (Gemini)",
        engine="gemini",
        gender="M",
        apparent_age="jovem",
        accent="brasileiro",
        timbre="versatil_jovem",
        engine_voice_id="Puck",
        supports_acting_prompt=True,
        supports_pitch_rate=False,
        description="Voz maleável e jovem. Executa direção cênica de deboche, medo ou entusiasmo com perfeição.",
    ),
    "gemini_charon": VoiceProfile(
        id="gemini_charon",
        name="Charon (Gemini)",
        engine="gemini",
        gender="M",
        apparent_age="maduro",
        accent="brasileiro",
        timbre="solene_profundo",
        engine_voice_id="Charon",
        supports_acting_prompt=True,
        supports_pitch_rate=False,
        description="Voz grave e profunda de cinema. Interpreta personagens idosos, mistérios e autoridade com peso dramático.",
    ),
    "gemini_kore": VoiceProfile(
        id="gemini_kore",
        name="Kore (Gemini)",
        engine="gemini",
        gender="F",
        apparent_age="jovem",
        accent="brasileiro",
        timbre="doce_serena",
        engine_voice_id="Kore",
        supports_acting_prompt=True,
        supports_pitch_rate=False,
        description="Voz feminina suave e emotiva. Responde muito bem a prompts de sussurro, tristeza ou ingenuidade.",
    ),
    "gemini_fenrir": VoiceProfile(
        id="gemini_fenrir",
        name="Fenrir (Gemini)",
        engine="gemini",
        gender="M",
        apparent_age="maduro",
        accent="brasileiro",
        timbre="forte_agressivo",
        engine_voice_id="Fenrir",
        supports_acting_prompt=True,
        supports_pitch_rate=False,
        description="Timbre ríspido e potente. Ideal para vilões, generais ou personagens em fúria.",
    ),
    "gemini_aoede": VoiceProfile(
        id="gemini_aoede",
        name="Aoede (Gemini)",
        engine="gemini",
        gender="F",
        apparent_age="maduro",
        accent="brasileiro",
        timbre="dramatica_teatral",
        engine_voice_id="Aoede",
        supports_acting_prompt=True,
        supports_pitch_rate=False,
        description="Voz madura e dramática, como uma atriz veterana de rádio-teatro.",
    ),
    "gemini_zephyr": VoiceProfile(
        id="gemini_zephyr",
        name="Zephyr (Gemini)",
        engine="gemini",
        gender="M",
        apparent_age="jovem",
        accent="brasileiro",
        timbre="calmo_reflexivo",
        engine_voice_id="Zephyr",
        supports_acting_prompt=True,
        supports_pitch_rate=False,
        description="Voz masculina contemplativa e intimista.",
    ),
    "gemini_leda": VoiceProfile(
        id="gemini_leda",
        name="Leda (Gemini)",
        engine="gemini",
        gender="F",
        apparent_age="adulta",
        accent="brasileiro",
        timbre="elegante_firme",
        engine_voice_id="Leda",
        supports_acting_prompt=True,
        supports_pitch_rate=False,
        description="Mulher adulta com segurança e elegância vocal.",
    ),
    "gemini_orus": VoiceProfile(
        id="gemini_orus",
        name="Orus (Gemini)",
        engine="gemini",
        gender="M",
        apparent_age="maduro",
        accent="brasileiro",
        timbre="autoritario_grave",
        engine_voice_id="Orus",
        supports_acting_prompt=True,
        supports_pitch_rate=False,
        description="Comandante maduro com autoridade inquestionável.",
    ),
}


# ==============================================================================
# FUNÇÕES DE CONSULTA E FALLBACK INTELIGENTE
# ==============================================================================


def get_voice_by_id(voice_id: str) -> Optional[VoiceProfile]:
    """Retorna o perfil da voz pelo ID ou None se não existir."""
    return VOICE_CATALOG.get(voice_id)


def list_voices(
    engine: Optional[EngineType] = None,
    gender: Optional[GenderType] = None,
    apparent_age: Optional[AgeGroup] = None,
    accent: Optional[AccentType] = None,
) -> List[VoiceProfile]:
    """Filtra o catálogo de vozes por múltiplos critérios."""
    resultado = list(VOICE_CATALOG.values())
    if engine:
        resultado = [v for v in resultado if v.engine == engine]
    if gender:
        resultado = [v for v in resultado if v.gender == gender]
    if apparent_age:
        resultado = [v for v in resultado if v.apparent_age == apparent_age]
    if accent:
        resultado = [v for v in resultado if v.accent == accent]
    return resultado


def find_fallback_voice(primary_voice: VoiceProfile) -> VoiceProfile:
    """
    Encontra a melhor voz de contingência ilimitada (Edge-TTS ou Kokoro)
    para um personagem, garantindo que o sistema nunca pare se a cota do
    Gemini acabar ou a internet falhar.
    """
    if primary_voice.engine in ("edge", "kokoro"):
        return primary_voice

    # Para vozes Gemini, busca o gêmeo mais próximo no Edge ou Kokoro
    candidatas = [v for v in VOICE_CATALOG.values() if v.engine in ("edge", "kokoro")]

    # 1. Tenta casar Gênero + Idade + Sotaque
    exatas = [
        v
        for v in candidatas
        if v.gender == primary_voice.gender
        and v.apparent_age == primary_voice.apparent_age
        and v.accent == primary_voice.accent
    ]
    if exatas:
        return exatas[0]

    # 2. Tenta casar Gênero + Idade
    idade_genero = [
        v
        for v in candidatas
        if v.gender == primary_voice.gender
        and v.apparent_age == primary_voice.apparent_age
    ]
    if idade_genero:
        return idade_genero[0]

    # 3. Tenta casar apenas Gênero
    apenas_genero = [v for v in candidatas if v.gender == primary_voice.gender]
    if apenas_genero:
        return apenas_genero[0]

    # Fallback supremo
    return VOICE_CATALOG["edge_antonio"]
