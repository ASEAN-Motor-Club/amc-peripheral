"""Synthesizes speech from the input string of text or ssml.
Make sure to be working in a virtual environment.

Note: ssml must be well-formed according to:
    https://www.w3.org/TR/speech-synthesis/
"""

from google.cloud import texttospeech

# Instantiates a client
client = texttospeech.TextToSpeechClient()


def tts(
    text,
    voice_language_code="en-GB",
    voice_name="en-GB-Chirp3-HD-Leda",
    use_markup=False,
    volume_gain_db=6.0,
):
    # Set the text input to be synthesized
    if use_markup:
        synthesis_input = texttospeech.SynthesisInput(markup=text)
    else:
        synthesis_input = texttospeech.SynthesisInput(text=text)

    # Build the voice request, select the language code ("en-US") and the ssml
    # voice gender ("neutral")
    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_language_code, name=voice_name
    )

    # Select the type of audio file you want returned
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3, volume_gain_db=volume_gain_db
    )

    # Perform the text-to-speech request on the text input with the selected
    # voice parameters and audio file type
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content  # bytes


def tts_ssml(
    text,
    voice_language_code="en-GB",
    voice_name="en-GB-Chirp3-HD-Leda",
    volume_gain_db=6.0,
):
    # Set the text input to be synthesized
    synthesis_input = texttospeech.SynthesisInput(ssml=text)

    # Build the voice request, select the language code ("en-US") and the ssml
    # voice gender ("neutral")
    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_language_code, name=voice_name
    )

    # Select the type of audio file you want returned
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3, volume_gain_db=volume_gain_db
    )

    # Perform the text-to-speech request on the text input with the selected
    # voice parameters and audio file type
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content  # bytes


def tts_multi(turns, voice_language_code="en-US", volume_gain_db=6.0):
    multi_speaker_markup = texttospeech.MultiSpeakerMarkup(
        turns=[
            texttospeech.MultiSpeakerMarkup.Turn(
                text=text,
                speaker=speaker,
            )
            for text, speaker in turns
        ]
    )
    # Set the text input to be synthesized
    synthesis_input = texttospeech.SynthesisInput(
        multi_speaker_markup=multi_speaker_markup
    )

    # Build the voice request, select the language code ('en-US') and the voice
    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_language_code, name="en-US-Studio-MultiSpeaker"
    )

    # Select the type of audio file you want returned
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3, volume_gain_db=volume_gain_db
    )

    # Perform the text-to-speech request on the text input with the selected
    # voice parameters and audio file type
    response = client.synthesize_speech(
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

    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content  # bytes


def tts_mimo(
    text: str,
    voice: str = "default_en",
    style: str | None = None,
    audio_format: str = "mp3",
) -> bytes:
    """Synthesize speech using Xiaomi MiMo v2 TTS.

    Uses the OpenAI-compatible chat completions endpoint with the mimo-v2-tts
    model. The text to synthesize must be in an assistant message.

    Args:
        text: The text to synthesize.
        voice: Voice ID — "mimo_default", "default_zh", or "default_en".
        style: Optional style tag (e.g. "Happy", "Sad", "Whisper").
            Prepended as <style>...</style> to the assistant content.
        audio_format: Output format — "mp3", "wav", or "pcm16".

    Returns:
        Audio content as bytes.
    """
    import base64

    from openai import OpenAI

    from amc_peripheral.settings import MIMO_API_KEY

    client = OpenAI(
        api_key=MIMO_API_KEY,
        base_url="https://api.xiaomimimo.com/v1",
    )

    # Build assistant content with optional style tag
    content = text
    if style:
        content = f"<style>{style}</style>{text}"

    completion = client.chat.completions.create(
        model="mimo-v2-tts",
        messages=[
            {"role": "assistant", "content": content},
        ],
        extra_body={
            "audio": {
                "format": audio_format,
                "voice": voice,
            },
        },
    )

    audio_data = completion.choices[0].message.audio.data
    return base64.b64decode(audio_data)
