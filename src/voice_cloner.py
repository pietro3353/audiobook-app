"""Voice Studio Lab: Módulo de Clonagem Acústica Zero-Shot Local.

Analisa uma amostra de voz de referência (5s a 15s em WAV/MP3/M4A/OGG),
extrai telemetria acústica real via DSP (Frequência Fundamental F0 em Hz,
Brilho Espectral / Spectral Centroid em Hz e Cadência / Energia RMS),
infere gênero, faixa etária e receita homogênea de Voice Blending no Kokoro-ONNX,
e persiste vozes customizadas em data/voices/custom_voices.json.
"""

import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydub import AudioSegment

from src.voices import VOICE_CATALOG, VoiceProfile, validate_same_gender_blend

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CUSTOM_VOICES_DIR = BASE_DIR / "data" / "voices"
CUSTOM_VOICES_FILENAME = "custom_voices.json"


def _slugify_voice_name(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[àáâãäå]", "a", s)
    s = re.sub(r"[èéêë]", "e", s)
    s = re.sub(r"[ìíîï]", "i", s)
    s = re.sub(r"[òóôõö]", "o", s)
    s = re.sub(r"[ùúûü]", "u", s)
    s = re.sub(r"[ç]", "c", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "voz_custom"


def _decode_audio_to_float32(audio_bytes: bytes, filename: str = "ref.wav") -> Tuple[np.ndarray, int]:
    """Decodifica áudio de referência para array float32 mono 24kHz normalizado [-1.0, 1.0]."""
    if not audio_bytes:
        raise ValueError("Arquivo de áudio de referência está vazio.")

    sr_target = 24000
    seg: Optional[AudioSegment] = None
    ext = Path(filename).suffix.lstrip(".").lower() if filename else ""

    try:
        if ext:
            seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format=ext)
        else:
            seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
    except Exception:
        try:
            if audio_bytes.startswith(b"RIFF"):
                seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
            elif audio_bytes.startswith(b"ID3") or audio_bytes[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
                seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
            else:
                seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
        except Exception:
            seg = AudioSegment(audio_bytes, sample_width=2, frame_rate=sr_target, channels=1)

    seg = seg.set_frame_rate(sr_target).set_channels(1).set_sample_width(2)
    samples = np.frombuffer(seg.raw_data, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, sr_target


def _estimate_f0_autocorr(voiced_samples: np.ndarray, sr: int) -> float:
    """Estima a frequência fundamental F0 (70 Hz a 340 Hz) via autocorrelação normalizada em janelas de 40ms."""
    win_len = int(sr * 0.04)  # 40ms (~960 samples a 24kHz)
    hop_len = max(1, win_len // 2)
    min_lag = max(1, int(sr / 340.0))
    max_lag = min(win_len - 1, int(sr / 70.0))

    if len(voiced_samples) < win_len or max_lag <= min_lag:
        return 145.0

    f0_estimates: List[float] = []
    window = np.hanning(win_len).astype(np.float32)

    for start in range(0, len(voiced_samples) - win_len + 1, hop_len):
        frame = voiced_samples[start : start + win_len]
        rms = float(np.sqrt(np.mean(frame ** 2)))
        if rms < 0.01:
            continue

        frame_w = (frame - float(np.mean(frame))) * window
        energy = float(np.dot(frame_w, frame_w))
        if energy <= 1e-8:
            continue

        # Autocorrelação rápida via numpy.correlate
        corr_full = np.correlate(frame_w, frame_w, mode="full")[win_len - 1 :]
        corr_sub = corr_full[min_lag : max_lag + 1] / energy
        if corr_sub.size == 0:
            continue

        max_corr = float(np.max(corr_sub))
        if max_corr < 0.25:
            continue

        # Seleciona o primeiro pico local significativo (>= 0.88 * max_corr) para evitar erro de oitava inferior
        threshold = 0.88 * max_corr
        chosen_offset = int(np.argmax(corr_sub))
        for idx in range(1, len(corr_sub) - 1):
            if corr_sub[idx] >= threshold and corr_sub[idx] >= corr_sub[idx - 1] and corr_sub[idx] >= corr_sub[idx + 1]:
                chosen_offset = idx
                break

        best_lag = min_lag + chosen_offset
        f0 = float(sr) / float(best_lag)
        if 70.0 <= f0 <= 340.0:
            f0_estimates.append(f0)

    if not f0_estimates:
        return 145.0
    return float(np.median(f0_estimates))


def analyze_reference_audio(
    audio_bytes: bytes,
    filename: str = "ref.wav",
    gender_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analisa amostra vocal de referência e extrai telemetria acústica + receita de Voice Blending.
    """
    samples, sr = _decode_audio_to_float32(audio_bytes, filename=filename)
    duration_sec = round(len(samples) / float(sr), 2)

    if len(samples) < int(sr * 0.25):
        raise ValueError("Amostra de áudio muito curta para clonagem (mínimo ~0.3 segundos).")

    # Remove silêncios extremos usando energia em janelas de 50ms
    rms_win = int(sr * 0.05)
    rms_vals: List[float] = []
    voiced_chunks: List[np.ndarray] = []
    peak = float(np.max(np.abs(samples))) or 1.0
    silence_thresh = max(0.005, peak * 0.05)

    for start in range(0, len(samples), rms_win):
        chunk = samples[start : start + rms_win]
        if chunk.size == 0:
            continue
        r = float(np.sqrt(np.mean(chunk ** 2)))
        rms_vals.append(r)
        if r >= silence_thresh:
            voiced_chunks.append(chunk)

    voiced = np.concatenate(voiced_chunks) if voiced_chunks else samples

    # 1. Frequência Fundamental (F0)
    f0_hz = round(_estimate_f0_autocorr(voiced, sr), 1)

    # 2. Brilho Espectral (Spectral Centroid em Hz via FFT)
    n_fft = min(len(voiced), 16384)
    fft_seg = voiced[:n_fft] * np.hanning(n_fft).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(fft_seg))
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    spec_sum = float(np.sum(spectrum))
    if spec_sum > 1e-8:
        spectral_centroid_hz = round(float(np.sum(freqs * spectrum) / spec_sum), 1)
    else:
        spectral_centroid_hz = 1200.0

    # 3. Cadência / Energia Dinâmica
    rms_arr = np.asarray(rms_vals, dtype=np.float32) if rms_vals else np.array([0.05], dtype=np.float32)
    rms_mean = float(np.mean(rms_arr))
    rms_std = float(np.std(rms_arr))
    cadence_ratio = round(rms_std / max(rms_mean, 1e-6), 3)

    # 4. Inferência de Gênero, Idade, Offsets e Receita Kokoro Homogênea
    g_clean = (gender_override or "").strip().upper()
    if g_clean in ("M", "F"):
        gender = g_clean
    else:
        gender = "M" if f0_hz < 168.0 else "F"

    if gender == "M":
        if f0_hz < 112.0:
            apparent_age = "maduro"
        elif f0_hz > 142.0 or cadence_ratio > 0.65:
            apparent_age = "jovem"
        else:
            apparent_age = "adulto"

        pitch_offset_hz = int(max(-3, min(3, round((f0_hz - 120.0) / 20.0))))
        rate_offset_pct = int(max(-6, min(6, round((cadence_ratio - 0.5) * 8.0))))

        # Receita masculina homogênea baseada em F0 e brilho espectral
        grave_factor = max(0.0, min(1.0, (145.0 - f0_hz) / 55.0))
        brilho_factor = max(0.0, min(1.0, (spectral_centroid_hz - 900.0) / 1400.0))

        w_santa = 0.15 + 0.55 * grave_factor
        w_fenrir = 0.10 + 0.25 * (1.0 - brilho_factor) * (0.5 + 0.5 * grave_factor)
        w_michael = 0.10 + 0.25 * brilho_factor
        w_alex = max(0.20, 1.0 - (w_santa + w_fenrir + w_michael) + 0.35)

        total_w = w_santa + w_alex + w_fenrir + w_michael
        raw_recipe = {
            "pm_alex": round(w_alex / total_w, 2),
            "pm_santa": round(w_santa / total_w, 2),
            "am_fenrir": round(w_fenrir / total_w, 2),
            "am_michael": round(w_michael / total_w, 2),
        }
    else:
        if f0_hz < 195.0:
            apparent_age = "maduro"
        elif f0_hz > 228.0 or cadence_ratio > 0.65:
            apparent_age = "jovem"
        else:
            apparent_age = "adulto"

        pitch_offset_hz = int(max(-3, min(3, round((f0_hz - 210.0) / 25.0))))
        rate_offset_pct = int(max(-6, min(6, round((cadence_ratio - 0.5) * 8.0))))

        # Receita feminina homogênea baseada em F0 e brilho espectral
        suave_factor = max(0.0, min(1.0, (f0_hz - 180.0) / 70.0))
        brilho_factor = max(0.0, min(1.0, (spectral_centroid_hz - 1100.0) / 1600.0))

        w_dora = 0.45 + 0.20 * (1.0 - brilho_factor)
        w_bella = 0.20 + 0.20 * suave_factor
        w_sarah = 0.15 + 0.20 * (1.0 - suave_factor)
        w_nicole = 0.05 + 0.15 * brilho_factor

        total_w = w_dora + w_bella + w_sarah + w_nicole
        raw_recipe = {
            "pf_dora": round(w_dora / total_w, 2),
            "af_bella": round(w_bella / total_w, 2),
            "af_sarah": round(w_sarah / total_w, 2),
            "af_nicole": round(w_nicole / total_w, 2),
        }

    # Mantém top 3 componentes com maior peso e garante soma exata = 1.00
    top3 = sorted(raw_recipe.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top3_sum = sum(w for _, w in top3) or 1.0
    blend_recipe: Dict[str, float] = {}
    acc = 0.0
    for i, (k, w) in enumerate(top3):
        if i == len(top3) - 1:
            blend_recipe[k] = round(max(0.05, 1.0 - acc), 2)
        else:
            val = round(w / top3_sum, 2)
            blend_recipe[k] = val
            acc += val

    if not validate_same_gender_blend(blend_recipe):
        blend_recipe = {"pm_alex": 0.65, "pm_santa": 0.35} if gender == "M" else {"pf_dora": 0.70, "af_bella": 0.30}

    timbre_label = "grave_profundo" if (gender == "M" and f0_hz < 125.0) else (
        "brilhante_dinamico" if spectral_centroid_hz > 1600.0 else "equilibrado_natural"
    )

    return {
        "f0_hz": f0_hz,
        "spectral_centroid_hz": spectral_centroid_hz,
        "cadence_ratio": cadence_ratio,
        "duration_sec": duration_sec,
        "gender": gender,
        "apparent_age": apparent_age,
        "timbre": timbre_label,
        "pitch_offset_hz": pitch_offset_hz,
        "rate_offset_pct": rate_offset_pct,
        "blend_recipe": blend_recipe,
    }


def _custom_voices_json_path(custom_dir: Optional[Path] = None) -> Path:
    base = Path(custom_dir) if custom_dir else DEFAULT_CUSTOM_VOICES_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / CUSTOM_VOICES_FILENAME


def _dict_to_profile(item: Dict[str, Any]) -> VoiceProfile:
    return VoiceProfile(
        id=item["id"],
        name=item["name"],
        engine=item.get("engine", "kokoro"),
        gender=item["gender"],
        apparent_age=item.get("apparent_age", "adulto"),
        accent=item.get("accent", "brasileiro"),
        timbre=item.get("timbre", "clonado_studio_lab"),
        engine_voice_id=item["engine_voice_id"],
        supports_acting_prompt=False,
        supports_pitch_rate=False,
        is_blend=True,
        blend_recipe=item.get("blend_recipe"),
        description=item.get("description", ""),
    )


def load_custom_voices(custom_dir: Optional[Path] = None) -> List[VoiceProfile]:
    """Carrega todas as vozes customizadas persistidas em JSON e registra no VOICE_CATALOG."""
    json_path = _custom_voices_json_path(custom_dir)
    if not json_path.exists():
        return []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    profiles: List[VoiceProfile] = []
    for item in data if isinstance(data, list) else []:
        try:
            prof = _dict_to_profile(item)
            VOICE_CATALOG[prof.id] = prof
            profiles.append(prof)
        except Exception:
            continue
    return profiles


def create_cloned_voice_profile(
    name: str,
    audio_bytes: bytes,
    filename: str = "ref.wav",
    gender_override: Optional[str] = None,
    custom_dir: Optional[Path] = None,
) -> Tuple[VoiceProfile, Dict[str, Any]]:
    """
    Analisa a amostra vocal, cria um VoiceProfile homogêneo do Kokoro para Voice Studio Lab,
    persiste em data/voices/custom_voices.json e registra em VOICE_CATALOG.
    """
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Informe um nome para a voz clonada.")

    telemetry = analyze_reference_audio(audio_bytes, filename=filename, gender_override=gender_override)
    slug = _slugify_voice_name(clean_name)
    voice_id = f"clone_{slug}"

    json_path = _custom_voices_json_path(custom_dir)
    existing: List[Dict[str, Any]] = []
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    existing = loaded
        except Exception:
            existing = []

    # Garante ID único se já existir outro perfil distinto
    existing_ids = {item.get("id") for item in existing} | set(VOICE_CATALOG.keys())
    if voice_id in existing_ids:
        contador = 2
        while f"{voice_id}_{contador}" in existing_ids:
            contador += 1
        voice_id = f"{voice_id}_{contador}"

    recipe = telemetry["blend_recipe"]
    receita_desc = ", ".join(f"{k}: {int(round(v * 100))}%" for k, v in recipe.items())
    profile_dict = {
        "id": voice_id,
        "name": f"{clean_name} (Clone Lab)",
        "engine": "kokoro",
        "gender": telemetry["gender"],
        "apparent_age": telemetry["apparent_age"],
        "accent": "brasileiro",
        "timbre": telemetry["timbre"],
        "engine_voice_id": f"blend_{voice_id}",
        "is_blend": True,
        "blend_recipe": recipe,
        "description": (
            f"Voz clonada no Studio Lab (F0={telemetry['f0_hz']} Hz, "
            f"Brilho={telemetry['spectral_centroid_hz']} Hz). Receita Kokoro: {receita_desc}."
        ),
        "telemetry": telemetry,
    }

    existing.append(profile_dict)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    prof = _dict_to_profile(profile_dict)
    VOICE_CATALOG[prof.id] = prof
    return prof, telemetry


def delete_custom_voice(voice_id: str, custom_dir: Optional[Path] = None) -> bool:
    """Remove uma voz customizada ('clone_*') do catálogo em memória e do disco."""
    if not voice_id or not voice_id.startswith("clone_"):
        return False

    json_path = _custom_voices_json_path(custom_dir)
    removed = False

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

        if isinstance(existing, list):
            nova_lista = [item for item in existing if item.get("id") != voice_id]
            if len(nova_lista) != len(existing):
                removed = True
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(nova_lista, f, indent=2, ensure_ascii=False)

    if voice_id in VOICE_CATALOG:
        VOICE_CATALOG.pop(voice_id, None)
        removed = True

    return removed
