"""Synthesizes speech from the input string of text or ssml.
Make sure to be working in a virtual environment.

Note: ssml must be well-formed according to:
    https://www.w3.org/TR/speech-synthesis/
"""
import os
from google.cloud import texttospeech
from amc_peripheral.settings import STATIC_PATH

# Instantiates a client
client = texttospeech.TextToSpeechClient()

def tts(text, voice_language_code="en-GB", voice_name="en-GB-Chirp3-HD-Leda", use_markup=False, volume_gain_db=6.0):

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
        audio_encoding=texttospeech.AudioEncoding.MP3,
        volume_gain_db=volume_gain_db
    )

    # Perform the text-to-speech request on the text input with the selected
    # voice parameters and audio file type
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content #bytes

def tts_ssml(text, voice_language_code="en-GB", voice_name="en-GB-Chirp3-HD-Leda", volume_gain_db=6.0):

    # Set the text input to be synthesized
    synthesis_input = texttospeech.SynthesisInput(ssml=text)


    # Build the voice request, select the language code ("en-US") and the ssml
    # voice gender ("neutral")
    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_language_code, name=voice_name
    )

    # Select the type of audio file you want returned
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        volume_gain_db=volume_gain_db
    )

    # Perform the text-to-speech request on the text input with the selected
    # voice parameters and audio file type
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content #bytes

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
        audio_encoding=texttospeech.AudioEncoding.MP3,
        volume_gain_db=volume_gain_db
    )

    # Perform the text-to-speech request on the text input with the selected
    # voice parameters and audio file type
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    return response.audio_content #bytes

