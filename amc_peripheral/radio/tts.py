"""Synthesizes speech from the input string of text or ssml.
Make sure to be working in a virtual environment.

Note: ssml must be well-formed according to:
    https://www.w3.org/TR/speech-synthesis/
"""

import logging
from contextlib import contextmanager

log = logging.getLogger(__name__)

# Google Cloud TTS client — lazy to avoid import failures when only MiMo is used
_client = None


def _get_client():
    global _client
    if _client is None:
        from google.cloud import texttospeech

        _client = texttospeech.TextToSpeechClient()
    return _client


# MiMo v2 TTS — known voices and styles
# https://platform.xiaomimimo.com/#/docs/usage-guide/speech-synthesis
MIMO_VOICES: dict[str, str] = {
    "mimo_default": "Default (auto language detection)",
    "default_en": "English female voice",
    "default_zh": "Chinese female voice",
}

MIMO_STYLES: list[str] = [
    # Emotional
    "Happy",
    "Sad",
    "Angry",
    "Excited",
    "Calm",
    "Dramatic",
    # Delivery
    "Whisper",
    "Speed up",
    "Slow down",
    # Accents & dialects
    "British accent",
    "Posh British",
    "London accent",
    "English accent",
    "Taiwanese accent",
    "Northeastern dialect",
    "Sichuan dialect",
    "Cantonese",
    # Role-playing
    "Sun Wukong",
    "Lin Daiyu",
    # Singing
    "Sing",
]


def tts(
    text,
    voice_language_code="en-GB",
    voice_name="en-GB-Chirp3-HD-Leda",
    use_markup=False,
    volume_gain_db=6.0,
):
    from google.cloud import texttospeech

    if use_markup:
        synthesis_input = texttospeech.SynthesisInput(markup=text)
    else:
        synthesis_input = texttospeech.SynthesisInput(text=text)

    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_language_code, name=voice_name
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3, volume_gain_db=volume_gain_db
    )

    response = _get_client().synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content  # bytes


def tts_ssml(
    text,
    voice_language_code="en-GB",
    voice_name="en-GB-Chirp3-HD-Leda",
    volume_gain_db=6.0,
):
    from google.cloud import texttospeech

    synthesis_input = texttospeech.SynthesisInput(ssml=text)

    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_language_code, name=voice_name
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3, volume_gain_db=volume_gain_db
    )

    response = _get_client().synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content  # bytes


def tts_multi(turns, voice_language_code="en-US", volume_gain_db=6.0):
    from google.cloud import texttospeech

    multi_speaker_markup = texttospeech.MultiSpeakerMarkup(
        turns=[
            texttospeech.MultiSpeakerMarkup.Turn(
                text=text,
                speaker=speaker,
            )
            for text, speaker in turns
        ]
    )

    synthesis_input = texttospeech.SynthesisInput(
        multi_speaker_markup=multi_speaker_markup
    )

    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_language_code, name="en-US-Studio-MultiSpeaker"
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3, volume_gain_db=volume_gain_db
    )

    response = _get_client().synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content  # bytes


def tts_gemini_multi(
    turns: list[tuple[str, str]],
    speaker_voices: dict[str, str],
    prompt: str = "",
    voice_language_code: str = "en-GB",
    model_name: str = "gemini-2.5-flash-tts",
    volume_gain_db: float = 6.0,
):
    """Synthesize multi-speaker audio using Gemini TTS with structured text input.

    Args:
        turns: List of (text, speaker_alias) tuples representing dialogue turns.
        speaker_voices: Mapping of speaker alias to Gemini voice ID
            (e.g. {"Host": "Kore", "Guest": "Charon"}).
        prompt: Style prompt controlling delivery
            (e.g. "Say this as a lively radio talk show").
        voice_language_code: BCP-47 language code.
        model_name: Gemini TTS model to use.
        volume_gain_db: Volume gain in dB.

    Returns:
        Audio content as bytes (MP3).
    """
    from google.cloud import texttospeech

    multi_speaker_markup = texttospeech.MultiSpeakerMarkup(
        turns=[
            texttospeech.MultiSpeakerMarkup.Turn(
                text=text,
                speaker=speaker,
            )
            for text, speaker in turns
        ]
    )

    synthesis_input = texttospeech.SynthesisInput(
        multi_speaker_markup=multi_speaker_markup,
        prompt=prompt,
    )

    multi_speaker_voice_config = texttospeech.MultiSpeakerVoiceConfig(
        speaker_voice_configs=[
            texttospeech.MultispeakerPrebuiltVoice(
                speaker_alias=alias,
                speaker_id=voice_id,
            )
            for alias, voice_id in speaker_voices.items()
        ]
    )

    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_language_code,
        model_name=model_name,
        multi_speaker_voice_config=multi_speaker_voice_config,
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        volume_gain_db=volume_gain_db,
    )

    response = _get_client().synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content  # bytes


def tts_mimo(
    text: str,
    voice: str = "default_en",
    style: str | None = "British accent",
    audio_format: str = "mp3",
    user_message: str | None = None,
) -> bytes:
    """Synthesize speech using Xiaomi MiMo v2 TTS.

    Uses the OpenAI-compatible chat completions endpoint with the mimo-v2-tts
    model. The target text must be in an assistant message.

    Args:
        text: The text to synthesize.
        voice: Voice ID — "mimo_default", "default_zh", or "default_en".
        style: Optional style tag (e.g. "Happy", "Whisper", "British accent").
            Prepended as <style>...</style> to the assistant content.
            See MIMO_STYLES for known values. Pass None to disable.
        audio_format: Output format — "mp3", "wav", or "pcm16".
        user_message: Optional user message placed before the assistant message.
            Helps set context/tone (e.g. "Read the following news bulletin.").

    Returns:
        Audio content as bytes.
    """
    import base64

    from openai import OpenAI

    from amc_peripheral.settings import MIMO_API_KEY

    openai_client = OpenAI(
        api_key=MIMO_API_KEY,
        base_url="https://api.xiaomimimo.com/v1",
    )

    # Build assistant content with optional style tag
    content = text
    if style:
        content = f"<style>{style}</style>{text}"

    messages: list[dict[str, str]] = []
    if user_message:
        messages.append({"role": "user", "content": user_message})
    messages.append({"role": "assistant", "content": content})

    completion = openai_client.chat.completions.create(
        model="mimo-v2-tts",
        messages=messages,
        extra_body={
            "audio": {
                "format": audio_format,
                "voice": voice,
            },
        },
    )

    audio_data = completion.choices[0].message.audio.data
    return base64.b64decode(audio_data)


@contextmanager
def _qwen3_endpoint(endpoint_name: str, token: str):
    """Resume a paused HF Inference Endpoint, wait for it to be ready, then
    pause it after use. This keeps costs at zero between TTS calls.

    Yields nothing — use as a scope guard.
    """
    from huggingface_hub import HfApi

    api = HfApi(token=token)

    ep = api.get_inference_endpoint(name=endpoint_name)
    status = ep.status

    if status == "paused":
        log.info(f"Resuming HF endpoint '{endpoint_name}'...")
        api.resume_inference_endpoint(name=endpoint_name)

        import time

        deadline = time.time() + 300  # 5 min max wait for model load
        while time.time() < deadline:
            time.sleep(10)
            ep = api.get_inference_endpoint(name=endpoint_name)
            status = ep.status
            if status == "running":
                log.info(f"Endpoint '{endpoint_name}' is running.")
                break
        else:
            raise TimeoutError(
                f"HF endpoint '{endpoint_name}' did not become ready within 5 min "
                f"(last status: {status})"
            )

    try:
        yield
    finally:
        try:
            api.pause_inference_endpoint(name=endpoint_name)
            log.info(f"Paused HF endpoint '{endpoint_name}'.")
        except Exception:
            log.warning(f"Failed to pause HF endpoint '{endpoint_name}'.")


def tts_qwen3(
    text: str,
    speaker: str = "Ryan",
    language: str = "English",
    instruct: str = "",
    volume_gain_db: float = 6.0,
) -> bytes:
    """Synthesize speech using Qwen3-TTS via HuggingFace Inference Endpoint.

    Uses the Qwen3-TTS-12Hz-1.7B-CustomVoice model hosted on a HF Inference
    Endpoint. The endpoint returns base64-encoded WAV audio in JSON, which is
    converted to MP3 via ffmpeg before returning.

    Args:
        text: The text to synthesize.
        speaker: Speaker ID (e.g. "Ryan", "Vivian", "Aiden", "Sohee").
        language: Language name (e.g. "English", "Chinese", "Japanese").
        instruct: Optional style instruction (e.g. "Speak in an excited tone").
        volume_gain_db: Volume gain in dB (applied via ffmpeg).

    Returns:
        Audio content as bytes (MP3).
    """
    import base64
    import subprocess
    import tempfile

    import requests

    from amc_peripheral.settings import (
        QWEN3_TTS_API_TOKEN,
        QWEN3_TTS_DEFAULT_LANGUAGE,
        QWEN3_TTS_DEFAULT_SPEAKER,
        QWEN3_TTS_ENDPOINT_NAME,
        QWEN3_TTS_ENDPOINT_URL,
    )

    if not QWEN3_TTS_ENDPOINT_URL:
        raise RuntimeError("QWEN3_TTS_ENDPOINT_URL is not configured")

    with _qwen3_endpoint(QWEN3_TTS_ENDPOINT_NAME, QWEN3_TTS_API_TOKEN):
        resp = requests.post(
        QWEN3_TTS_ENDPOINT_URL,
        headers={"Authorization": f"Bearer {QWEN3_TTS_API_TOKEN}"},
        json={
            "inputs": text,
            "speaker": speaker or QWEN3_TTS_DEFAULT_SPEAKER,
            "language": language or QWEN3_TTS_DEFAULT_LANGUAGE,
            "instruct": instruct,
        },
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if "error" in result:
        raise RuntimeError(f"Qwen3-TTS error: {result['error']}")

    wav_bytes = base64.b64decode(result["audio_base64"])

    # Convert WAV to MP3 via ffmpeg with volume gain
    with (
        tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_f,
        tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3_f,
    ):
        wav_path = wav_f.name
        mp3_path = mp3_f.name
        wav_f.write(wav_bytes)

    try:
        filter_arg = f"volume={10 ** (volume_gain_db / 20):.4f}"
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-af", filter_arg, "-codec:a",
             "libmp3lame", "-qscale:a", "2", mp3_path],
            capture_output=True,
            check=True,
        )
        with open(mp3_path, "rb") as f:
            return f.read()
    finally:
        import os

        os.unlink(wav_path)
        os.unlink(mp3_path)


def tts_qwen3_clone(
    text: str,
    ref_audio_path: str,
    ref_text: str,
    language: str = "English",
    volume_gain_db: float = 6.0,
) -> bytes:
    """Clone a voice from a reference audio sample and synthesize new text.

    Uses the Qwen3-TTS-12Hz-1.7B-Base model hosted on a separate HF Inference
    Endpoint. Requires a reference audio file and its transcript.

    Args:
        text: The text to synthesize in the cloned voice.
        ref_audio_path: Path to a WAV/MP3 file with the reference voice.
        ref_text: Transcript of the reference audio.
        language: Target language name (e.g. "English", "Chinese").
        volume_gain_db: Volume gain in dB (applied via ffmpeg).

    Returns:
        Audio content as bytes (MP3).
    """
    import base64
    import subprocess
    import tempfile

    import requests

    from amc_peripheral.settings import (
        QWEN3_TTS_API_TOKEN,
        QWEN3_TTS_CLONE_ENDPOINT_NAME,
        QWEN3_TTS_CLONE_ENDPOINT_URL,
    )

    if not QWEN3_TTS_CLONE_ENDPOINT_URL:
        raise RuntimeError("QWEN3_TTS_CLONE_ENDPOINT_URL is not configured")

    with _qwen3_endpoint(QWEN3_TTS_CLONE_ENDPOINT_NAME, QWEN3_TTS_API_TOKEN):
        # Read and base64-encode reference audio
        with open(ref_audio_path, "rb") as f:
            ref_audio_b64 = base64.b64encode(f.read()).decode("ascii")

        resp = requests.post(
        QWEN3_TTS_CLONE_ENDPOINT_URL,
        headers={"Authorization": f"Bearer {QWEN3_TTS_API_TOKEN}"},
        json={
            "inputs": text,
            "ref_audio_base64": ref_audio_b64,
            "ref_text": ref_text,
            "language": language,
        },
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()

    if "error" in result:
        raise RuntimeError(f"Qwen3-TTS clone error: {result['error']}")

    wav_bytes = base64.b64decode(result["audio_base64"])

    # Convert WAV to MP3 via ffmpeg with volume gain
    with (
        tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_f,
        tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3_f,
    ):
        wav_path = wav_f.name
        mp3_path = mp3_f.name
        wav_f.write(wav_bytes)

    try:
        filter_arg = f"volume={10 ** (volume_gain_db / 20):.4f}"
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-af", filter_arg, "-codec:a",
             "libmp3lame", "-qscale:a", "2", mp3_path],
            capture_output=True,
            check=True,
        )
        with open(mp3_path, "rb") as f:
            return f.read()
    finally:
        import os

        os.unlink(wav_path)
        os.unlink(mp3_path)


def tts_dispatch(
    text,
    voice_language_code="en-GB",
    voice_name="en-GB-Chirp3-HD-Leda",
    use_markup=False,
    volume_gain_db=6.0,
):
    """Route single-speaker TTS to the configured provider (TTS_PROVIDER).

    Falls back to Google Cloud TTS if the configured provider is unavailable.
    """
    from amc_peripheral.settings import TTS_PROVIDER

    if TTS_PROVIDER == "mimo":
        try:
            return tts_mimo(text)
        except Exception:
            pass  # fall through to Google
    elif TTS_PROVIDER == "qwen3":
        try:
            return tts_qwen3(text, volume_gain_db=volume_gain_db)
        except Exception:
            pass  # fall through to Google
    return tts(
        text,
        voice_language_code=voice_language_code,
        voice_name=voice_name,
        use_markup=use_markup,
        volume_gain_db=volume_gain_db,
    )
