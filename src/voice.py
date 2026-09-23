import os
import re
import shutil
import threading
import unicodedata
import requests
import soundfile as sf
import time
from pathlib import Path

try:
    from elevenlabs import ElevenLabs, save
except ImportError:
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import save
    except Exception:
        ElevenLabs = None
        save = None

try:
    from kokoro_onnx import Kokoro
except Exception as exc:
    Kokoro = None
    print(f"[ERROR] No se pudo importar Kokoro: {exc}")
from pydub import AudioSegment
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from debug_logger import voice_logger, log_elevenlabs_request, log_elevenlabs_response, log_elevenlabs_error, log_audio_rendering
from audio.mixer import overlay_background_music, add_crossfade_between_segments, add_intro_outro, cues_from_segments

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


ensure_output_dir()

SPANISH_KOKORO_VOICES = {
    "alex": "em_alex",
    "casey": "ef_dora",
    "morgan": "ef_dora",
    "jordan": "em_alex",
    "riley": "ef_dora",
    "sam": "em_santa",
    "taylor": "ef_dora",
    "marcus": "em_santa",
    "quinn": "em_santa",
    "system": "em_alex",
}

CONVERTER_VOICE_OPTIONS = {
    "Hombre (Alex)": "em_alex",
    "Hombre (Santa)": "em_santa",
    "Mujer (Dora)": "ef_dora",
}

_SKIP_SPEAKERS = {
    "",
    "system",
    "sistema",
    "titulo",
    "título",
    "nota",
    "tema",
    "narrador",
    "narradora",
}
_VOICE_A_ALIASES = {
    "alex",
    "voz 1",
    "voz1",
    "voz uno",
    "andres",
    "andrés",
    "fiscal",
    "acusador",
    "hombre",
}
_VOICE_B_ALIASES = {
    "casey",
    "voz 2",
    "voz2",
    "voz dos",
    "valentina",
    "defensor",
    "defensora",
    "mujer",
    "dora",
}
_INLINE_SPEAKER = re.compile(
    r"(?im)^\s*(ALEX|CASEY|VOZ\s*[12]|VOZ[12]|FISCAL|DEFENSORA?|ANDR[EÉ]S|VALENTINA|MAURICIO)\s*:\s*"
)


def _fold_speaker(name):
    raw = unicodedata.normalize("NFKD", str(name or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", raw).strip().lower()


def _slot_for_speaker(name):
    folded = _fold_speaker(name)
    if folded in _SKIP_SPEAKERS:
        return None
    if folded in _VOICE_A_ALIASES:
        return "A"
    if folded in _VOICE_B_ALIASES:
        return "B"
    return "OTHER"


def _split_by_inline_speakers(speaker, text):
    text = str(text or "").replace("\r\n", "\n")
    matches = list(_INLINE_SPEAKER.finditer(text))
    if not matches:
        blob = text.strip()
        return [{"speaker": str(speaker or "").strip(), "text": blob}] if blob else []
    rows = []
    if matches[0].start() > 0:
        head = text[: matches[0].start()].strip()
        if head:
            rows.append({"speaker": str(speaker or "").strip(), "text": head})
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body:
            rows.append({"speaker": match.group(1).strip(), "text": body})
    return rows


def explode_spoken_lines(lines):
    """Turn JSON/TXT rows into speakable {speaker, text}, splitting inner ALEX:/CASEY:."""
    out = []
    for item in lines or []:
        if isinstance(item, dict):
            speaker = str(item.get("speaker") or item.get("vocero") or item.get("who") or "").strip()
            text = item.get("text")
            if text is None:
                text = item.get("dialogue") or item.get("line") or ""
            extra = dict(item)
        else:
            speaker, text, extra = "", str(item), {}
        for part in _split_by_inline_speakers(speaker, text):
            row = dict(extra)
            row["speaker"] = part["speaker"]
            row["text"] = part["text"]
            out.append(row)
    return out


def apply_two_voices(lines, voice_a="em_alex", voice_b="ef_dora"):
    """Assign Kokoro voice 1 / voice 2. Skip Título/Nota. Alternate if there is only one vocero."""
    voice_a = voice_a or "em_alex"
    voice_b = voice_b or "ef_dora"
    if voice_a == voice_b:
        voice_b = "ef_dora" if voice_a != "ef_dora" else "em_alex"
    rows = explode_spoken_lines(lines)
    if not rows:
        return []

    slots = [_slot_for_speaker(ln.get("speaker")) for ln in rows]
    has_a = any(s == "A" for s in slots)
    has_b = any(s == "B" for s in slots)
    others = []
    for ln, slot in zip(rows, slots):
        sp = str(ln.get("speaker") or "").strip()
        if slot == "OTHER" and sp and sp not in others:
            others.append(sp)

    def stamp(ln, which):
        if which == "A":
            ln["speaker"] = "ALEX"
            ln["voice_id"] = voice_a
        else:
            ln["speaker"] = "CASEY"
            ln["voice_id"] = voice_b
        return ln

    if has_a and has_b:
        for ln, slot in zip(rows, slots):
            stamp(ln, "A" if slot != "B" else "B")
        return rows
    if len(others) >= 2:
        a_name, b_name = others[0], others[1]
        for i, (ln, slot) in enumerate(zip(rows, slots)):
            sp = str(ln.get("speaker") or "").strip()
            if slot == "A" or sp == a_name:
                stamp(ln, "A")
            elif slot == "B" or sp == b_name:
                stamp(ln, "B")
            elif sp in others:
                stamp(ln, "A" if others.index(sp) % 2 == 0 else "B")
            else:
                stamp(ln, "A" if i % 2 == 0 else "B")
        return rows
    for i, ln in enumerate(rows):
        stamp(ln, "A" if i % 2 == 0 else "B")
    return rows



def _configure_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        if winget.exists():
            matches = list(winget.glob("**/ffmpeg.exe"))
            ffmpeg = str(matches[0]) if matches else None
    if ffmpeg:
        AudioSegment.converter = ffmpeg
        AudioSegment.ffmpeg = ffmpeg
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            probe_candidate = Path(ffmpeg).with_name("ffprobe.exe")
            if probe_candidate.exists():
                ffprobe = str(probe_candidate)
        if ffprobe:
            AudioSegment.ffprobe = ffprobe
        voice_logger.info(f"Using ffmpeg: {ffmpeg}")
    else:
        voice_logger.warning("ffmpeg not found in PATH; exporting WAV instead of MP3")


_configure_ffmpeg()

# URLs for the models
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"

def download_file(url, filename):
    print(f"[DOWNLOAD] Downloading {filename}...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"[OK] Downloaded {filename}")
    except Exception as e:
        print(f"[ERROR] Failed to download {filename}: {e}")
        # Delete partial file so we try again next time
        if os.path.exists(filename):
            os.remove(filename)

def check_and_install_models():
    """Checks if models exist and are valid (not empty)."""

    # Check Model File
    if not os.path.exists(MODEL_FILE) or os.path.getsize(MODEL_FILE) == 0:
        print(f"[WARNING] {MODEL_FILE} missing or empty. Downloading...")
        download_file(MODEL_URL, MODEL_FILE)

    # Check Voices File
    if not os.path.exists(VOICES_FILE) or os.path.getsize(VOICES_FILE) == 0:
        print(f"[WARNING] {VOICES_FILE} missing or empty. Downloading...")
        download_file(VOICES_URL, VOICES_FILE)

# Run check immediately
check_and_install_models()

# Initialize Kokoro
try:
    print("[INFO] Loading Kokoro Model...")
    kokoro = Kokoro(MODEL_FILE, VOICES_FILE)
    print("[OK] Local Kokoro TTS Ready.")
except Exception as e:
    print(f"[ERROR] Critical Error loading Kokoro: {e}")
    kokoro = None

# ... [Keep your existing helper functions below] ...

def get_voice_id(character_name, provider, lang="en-us"):
    clean_name = (character_name or "system").split(" ")[0].lower()
    if lang.startswith("es") and "Local" in provider:
        return SPANISH_KOKORO_VOICES.get(clean_name, "em_alex")
    try:
        filename = f"src/characters/{clean_name}.json"
        with open(filename, "r") as f:
            data = json.load(f)
        if "Local" in provider:
            return data.get("kokoro_voice", "af_bella")
        return data.get("elevenlabs_voice", "JBFqnCBsd6RMkjVDRZzb")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return "em_alex" if lang.startswith("es") else "af_bella"

def get_transition_sound():
    """Load a random transition sound from music/transitions/ folder.
    
    Returns:
        AudioSegment or None if no transition sounds available
    """
    from pathlib import Path
    import random
    
    transitions_dir = Path("src/music/transitions")
    if not transitions_dir.exists():
        voice_logger.debug("Transitions directory not found")
        return None
    
    transition_files = list(transitions_dir.glob("*.wav")) + list(transitions_dir.glob("*.mp3")) + list(transitions_dir.glob("*.ogg"))
    if not transition_files:
        voice_logger.debug("No transition sound files found")
        return None
    
    try:
        transition_path = random.choice(transition_files)
        transition = AudioSegment.from_file(str(transition_path))
        voice_logger.debug(f"Loaded transition: {transition_path.name}")
        return transition
    except Exception as e:
        voice_logger.warning(f"Failed to load transition sound: {str(e)}")
        return None
    
# Kokoro cuts or fails past ~510 tokens; keep spoken chunks well under that.
TTS_CHUNK_CHARS = 280
# Overlap eats the start/end of each line; keep it tiny.
DIALOGUE_CROSSFADE_MS = 40
_kokoro_lock = threading.Lock()
last_unspoken_lines = []


def _pause_segment(ms=400):
    return AudioSegment.silent(duration=ms)


def prepare_tts_text(text):
    """One spoken line: no newlines, dashes Kokoro often skips."""
    cleaned = (text or "").replace("\r", " ").replace("\n", " ")
    cleaned = cleaned.replace("—", ", ").replace("–", ", ").replace("…", ".")
    cleaned = re.sub(r"\bN\.?\s*°\s*", "número ", cleaned, flags=re.I)
    cleaned = cleaned.replace("%", " por ciento")
    cleaned = re.sub(r"[*_`#]+", " ", cleaned)
    cleaned = re.sub(r"\[(?:pausa|m[uú]sica)[^\]]*\]", " ", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip()


def split_tts_chunks(text, max_chars=TTS_CHUNK_CHARS):
    """Break a long paragraph so Kokoro reads all of it, not only the first sentence."""
    cleaned = prepare_tts_text(text)
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    pieces = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks = []
    current = ""
    for piece in pieces:
        piece = (piece or "").strip()
        if not piece:
            continue
        parts = [piece] if len(piece) <= max_chars else _split_long_clause(piece, max_chars)
        for part in parts:
            if current and len(current) + 1 + len(part) > max_chars:
                chunks.append(current)
                current = part
            else:
                current = (current + " " + part).strip()
    if current:
        chunks.append(current)
    return chunks or [cleaned[:max_chars]]


def _split_long_clause(text, max_chars):
    bits = re.split(r"(?<=[,;:])\s+", text)
    out = []
    current = ""
    for bit in bits:
        bit = (bit or "").strip()
        if not bit:
            continue
        if len(bit) > max_chars:
            if current:
                out.append(current)
                current = ""
            out.extend(_hard_wrap(bit, max_chars))
            continue
        if current and len(current) + 1 + len(bit) > max_chars:
            out.append(current)
            current = bit
        else:
            current = (current + " " + bit).strip()
    if current:
        out.append(current)
    return out


def _hard_wrap(text, max_chars):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return lines


def _kokoro_to_segment(text, voice_id, kokoro_lang):
    with _kokoro_lock:
        samples, sample_rate = kokoro.create(text, voice=voice_id, speed=1.0, lang=kokoro_lang)
    if samples is None:
        raise RuntimeError("Kokoro returned no audio")
    filename = f"temp_chunk_{time.time_ns()}.wav"
    sf.write(filename, samples, sample_rate)
    segment = AudioSegment.from_wav(filename)
    os.remove(filename)
    return segment


def render_audio_line(line_index, line_data, provider, lang="es"):
    """Render a single line of audio. Used for parallel processing.
    
    Args:
        line_index: Index of the line in the script
        line_data: Dict with 'speaker' and 'text' fields
        provider: Voice provider string
        lang: Spoken language for TTS (es or en-us)
    
    Returns:
        Tuple of (line_index, audio_segment) or (line_index, None) on error
    """
    # Validate line is a dict
    if not isinstance(line_data, dict):
        voice_logger.warning(f"Line {line_index}: expected dict, got {type(line_data)}")
        print(f"[WARNING] Skipping line {line_index}: expected dict, got {type(line_data)}")
        return (line_index, None)

    speaker = line_data.get("speaker", "System")
    text = prepare_tts_text(line_data.get("text", ""))

    if not text:
        voice_logger.warning(f"Line {line_index}: no text content, pause")
        return (line_index, _pause_segment())

    raw_voice = line_data.get("voice_id")
    if isinstance(raw_voice, str) and raw_voice.strip():
        voice_id = raw_voice.strip()
    else:
        voice_id = get_voice_id(speaker, provider, lang=lang)
    kokoro_lang = "es" if str(lang).startswith("es") else "en-us"
    print(f"   [{speaker}/{voice_id}] {text[:50]}...")
    voice_logger.debug(f"Line {line_index} - {speaker} (voice_id={voice_id}, lang={kokoro_lang}): {text[:100]}...")

    filename = f"temp_{line_index}_{time.time()}.wav"

    try:
        start_time = time.time()

        if "Local" in provider:
            if kokoro is None:
                raise RuntimeError("Kokoro no está cargado. Espera a que termine de iniciar.")
            chunks = split_tts_chunks(text)
            voice_logger.info(f"Line {line_index}: {len(chunks)} TTS chunk(s), {len(text)} chars")
            parts = []
            for chunk in chunks:
                parts.append(_kokoro_to_segment(chunk, voice_id, kokoro_lang))
            if not parts:
                return (line_index, None)
            segment = parts[0]
            for extra in parts[1:]:
                segment += extra
            duration_ms = (time.time() - start_time) * 1000
            log_audio_rendering(speaker, filename, duration_ms)
            voice_logger.debug(f"Kokoro rendered {speaker}: {len(segment)} ms from {len(chunks)} chunks")
            return (line_index, segment)

        if ElevenLabs is None or save is None:
            raise RuntimeError("ElevenLabs no está disponible. Usa Local (Kokoro).")
        client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        log_elevenlabs_request(text, voice_id)
        audio_gen = client.generate(text=text, voice=voice_id, model="eleven_turbo_v2")
        save(audio_gen, filename)
        duration_ms = (time.time() - start_time) * 1000
        file_size = os.path.getsize(filename)
        log_elevenlabs_response(filename, file_size)
        log_audio_rendering(speaker, filename, duration_ms)
        voice_logger.debug(f"ElevenLabs rendered {speaker}: {file_size} bytes")
        if os.path.exists(filename):
            segment = AudioSegment.from_wav(filename)
            os.remove(filename)
            return (line_index, segment)
        return (line_index, None)

    except Exception as e:
        voice_logger.error(f"Line {line_index}: {str(e)}")
        print(f"[ERROR] Error rendering line {line_index}: {e}")
        if os.path.exists(filename):
            os.remove(filename)
        return (line_index, None)


def render_audio(script, provider="Local (Kokoro)", max_workers=4, enable_music=False, enable_jingles=False, crossfade=True, dest_path=None):
    """Render podcast script to audio with parallel processing and production effects.

    Args:
        script: List of line objects with 'speaker' and 'text' fields
        provider: Voice provider ('Local (Kokoro)' or 'Cloud (ElevenLabs)')
        max_workers: Maximum number of parallel workers (default: 4)
        enable_music: Whether to add background music (default: False)
        enable_jingles: Whether to add intro/outro jingles (default: False)
        crossfade: Whether to crossfade between dialogue segments (default: True)

    Returns:
        Path to final MP3 file
    """
    print(f"[INFO] Voice: Rendering audio using {provider} (parallel mode: {max_workers} workers)...")
    voice_logger.info(f"Starting parallel audio render with {provider}, max_workers={max_workers}")
    
    if "Local" in provider and kokoro is None:
        raise Exception("Kokoro failed to load. Check logs.")
    
    # Validate script format
    if not isinstance(script, list):
        voice_logger.error(f"Script format error: expected list, got {type(script)}")
        raise Exception(f"Script must be a list, got {type(script)}")
    
    voice_logger.debug(f"Script contains {len(script)} lines")
    
    # Parallel rendering
    audio_segments = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all lines for parallel processing
        future_to_index = {
            executor.submit(render_audio_line, i, line, provider, "es"): i
            for i, line in enumerate(script)
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_index):
            line_index, segment = future.result()
            if segment is not None:
                audio_segments[line_index] = segment

    missing = [i for i in range(len(script)) if i not in audio_segments]
    if missing:
        voice_logger.warning(f"Retrying {len(missing)} lines that Kokoro skipped")
        for _attempt in range(3):
            still = [i for i in missing if i not in audio_segments]
            if not still:
                break
            for i in still:
                _idx, segment = render_audio_line(i, script[i], provider, "es")
                if segment is not None:
                    audio_segments[i] = segment
    still_missing = [i for i in range(len(script)) if i not in audio_segments]
    global last_unspoken_lines
    last_unspoken_lines = []
    if still_missing:
        for i in still_missing:
            audio_segments[i] = _pause_segment(500)
            line = script[i] if i < len(script) and isinstance(script[i], dict) else {}
            snippet = str(line.get("text") or "").strip()[:80]
            last_unspoken_lines.append(f"{i + 1}. {snippet or '(vacía)'}")
        voice_logger.warning(
            f"Inserted pause for {len(still_missing)} lines: {last_unspoken_lines[:8]}"
        )
    
    # Combine segments in correct order
    voice_logger.info(f"Combining {len(audio_segments)} audio segments in order...")
    
    # Check if there's a sponsor ad in the script
    ad_index = None
    for i, line in enumerate(script):
        if not isinstance(line, dict):
            continue
        if "sponsor" in line.get("text", "").lower() or "brought to you by" in line.get("text", "").lower():
            ad_index = i
            voice_logger.info(f"Detected sponsor ad at index {i}")
            break
    
    if crossfade:
        # Build segments list and add transitions around ad if present
        segments_list = []
        for i in range(len(script)):
            if i in audio_segments:
                # Add transition before ad
                if i == ad_index:
                    transition_sound = get_transition_sound()
                    if transition_sound:
                        segments_list.append(transition_sound)
                        voice_logger.info("Added transition sound before sponsor ad")
                
                segments_list.append(audio_segments[i])
                
                # Add transition after ad
                if i == ad_index:
                    transition_sound = get_transition_sound()
                    if transition_sound:
                        segments_list.append(transition_sound)
                        voice_logger.info("Added transition sound after sponsor ad")
            else:
                voice_logger.warning(f"Missing audio for line {i}, skipping")
        
        combined_audio = add_crossfade_between_segments(segments_list, crossfade_ms=DIALOGUE_CROSSFADE_MS)
    else:
        # Original method with silence gaps
        combined_audio = AudioSegment.empty()
        for i in range(len(script)):
            if i in audio_segments:
                combined_audio += audio_segments[i] + AudioSegment.silent(duration=300)
            else:
                voice_logger.warning(f"Missing audio for line {i}, skipping")
    
    # Add intro/outro jingles if enabled
    if enable_jingles:
        voice_logger.info("Adding intro/outro jingles...")
        combined_audio = add_intro_outro(combined_audio)
    
    # Add background music if enabled
    if enable_music:
        voice_logger.info("Overlaying background music...")
        combined_audio = overlay_background_music(combined_audio)
    
    if combined_audio is None or len(combined_audio) < 200:
        raise Exception("No se generó audio. Revisa que Kokoro haya sintetizado las líneas del guion.")

    intro_ms = 0
    if enable_jingles:
        intro_file = Path(__file__).resolve().parent / "music" / "intro.wav"
        if intro_file.exists():
            try:
                intro_ms = len(AudioSegment.from_file(str(intro_file))) + 500
            except Exception:
                intro_ms = 0

    cues = cues_from_segments(
        script,
        audio_segments,
        intro_ms=intro_ms,
        crossfade_ms=DIALOGUE_CROSSFADE_MS if crossfade else 0,
        gap_ms=0 if crossfade else 300,
    )

    dest = Path(dest_path) if dest_path else None
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.suffix.lower() != ".mp3":
            dest = dest.with_suffix(".mp3")
        wav_path = dest.with_suffix(".wav")
        combined_audio.export(str(wav_path), format="wav")
        playable = wav_path
        try:
            combined_audio.export(str(dest), format="mp3", bitrate="64k")
            playable = dest
            voice_logger.info(f"MP3 export ok: {dest} ({len(combined_audio)} ms)")
        except Exception as e:
            voice_logger.warning(f"MP3 export failed, using WAV: {e}")
        output_file = str(playable.resolve())
        voice_logger.info(f"Standalone audio render complete: {output_file} ({len(combined_audio)} ms)")
        print(f"[OK] Audio guardado en: {output_file}")
        return output_file

    output_dir = ensure_output_dir()
    stamp = int(time.time())
    wav_path = output_dir / f"episode_{stamp}.wav"
    combined_audio.export(str(wav_path), format="wav")
    latest_wav = output_dir / "ultimo_episodio.wav"
    shutil.copyfile(wav_path, latest_wav)

    playable = wav_path
    mp3_path = output_dir / f"episode_{stamp}.mp3"
    latest_mp3 = output_dir / "ultimo_episodio.mp3"
    try:
        combined_audio.export(str(mp3_path), format="mp3", bitrate="64k")
        shutil.copyfile(mp3_path, latest_mp3)
        (PROJECT_ROOT / "final_episode.mp3").write_bytes(mp3_path.read_bytes())
        playable = mp3_path
        voice_logger.info(f"MP3 export ok: {mp3_path} ({len(combined_audio)} ms)")
    except Exception as e:
        voice_logger.warning(f"MP3 export failed, using WAV: {e}")

    output_file = str(playable.resolve())
    try:
        cue_path = output_dir / "cues.json"
        cue_path.write_text(
            json.dumps({"audio": output_file, "duration_ms": len(combined_audio), "cues": cues}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        voice_logger.warning(f"Could not write cues.json: {e}")
    voice_logger.info(f"Audio render complete: {output_file} ({len(combined_audio)} ms)")
    print(f"[OK] Audio guardado en: {output_file}")
    return output_file