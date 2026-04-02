"""HuggingFace Inference Endpoint handler for Qwen3-TTS.

Deploy this as a custom Inference Endpoint on HuggingFace with:
  - Model: Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
  - GPU: A10G small (24GB) or T4 (16GB)
  - Container: Python 3.12 + PyTorch

The endpoint expects POST requests with JSON body:
  {
    "text": "Hello world",
    "speaker": "Ryan",
    "language": "English",
    "instruct": "Speak excitedly"
  }

And returns WAV audio bytes with Content-Type: audio/wav.

Install dependencies (in HF endpoint container):
  pip install qwen-tts soundfile
  pip install flash-attn --no-build-isolation
"""

import base64
import io
import logging
from typing import Any

import torch

log = logging.getLogger(__name__)

SPEAKERS = {
    "Vivian": "Bright, slightly edgy young female voice.",
    "Serena": "Warm, gentle young female voice.",
    "Uncle_Fu": "Seasoned male voice with a low, mellow timbre.",
    "Dylan": "Youthful Beijing male voice with a clear, natural timbre.",
    "Eric": "Lively Chengdu male voice with a slightly husky brightness.",
    "Ryan": "Dynamic male voice with strong rhythmic drive.",
    "Aiden": "Sunny American male voice with a clear midrange.",
    "Ono_Anna": "Playful Japanese female voice with a light, nimble timbre.",
    "Sohee": "Warm Korean female voice with rich emotion.",
}


class EndpointHandler:
    def __init__(self, path: str = ""):
        from qwen_tts import Qwen3TTSModel

        log.info("Loading Qwen3-TTS model...")
        try:
            attn_impl = "flash_attention_2"
            self.model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                device_map="cuda:0",
                dtype=torch.bfloat16,
                attn_implementation=attn_impl,
            )
        except ImportError:
            log.warning("flash-attn not available, falling back to sdpa")
            self.model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                device_map="cuda:0",
                dtype=torch.bfloat16,
                attn_implementation="sdpa",
            )
        log.info("Qwen3-TTS model loaded.")

    def __call__(self, data: Any) -> dict:
        """Handle inference request.

        Input data format:
          {"text": str, "speaker": str, "language": str, "instruct": str}

        Returns:
          {"audio_base64": str} — base64-encoded WAV audio
        """
        import soundfile as sf

        text = data.get("inputs") or data.get("text", "")
        if not text:
            return {"error": "Missing 'inputs' or 'text' field"}

        speaker = data.get("speaker", "Ryan")
        language = data.get("language", "English")
        instruct = data.get("instruct", "")

        if speaker not in SPEAKERS:
            return {"error": f"Unknown speaker '{speaker}'. Valid: {list(SPEAKERS.keys())}"}

        log.info(f"Synthesizing: speaker={speaker}, language={language}, text={text[:80]}...")

        wavs, sr = self.model.generate_custom_voice(
            text=text,
            language=language,
            speaker=speaker,
            instruct=instruct,
        )

        # Encode to WAV bytes
        buf = io.BytesIO()
        sf.write(buf, wavs[0], sr, format="WAV")
        wav_bytes = buf.getvalue()

        return {"audio_base64": base64.b64encode(wav_bytes).decode("ascii")}
