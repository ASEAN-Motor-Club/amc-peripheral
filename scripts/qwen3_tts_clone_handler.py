"""HuggingFace Inference Endpoint handler for Qwen3-TTS Voice Clone.

Deploy this as a custom Inference Endpoint on HuggingFace with:
  - Model: Qwen/Qwen3-TTS-12Hz-1.7B-Base
  - GPU: A10G small (24GB) or T4 (16GB)

The endpoint accepts POST requests with JSON body:
  {
    "inputs": "Text to synthesize",
    "ref_audio_base64": "<base64-encoded WAV/MP3>",
    "ref_text": "Transcript of the reference audio",
    "language": "English"
  }

Returns JSON: {"audio_base64": "<base64-encoded WAV>"}

Install dependencies:
  pip install qwen-tts soundfile
"""

import base64
import io
import logging
import tempfile
from typing import Any

import torch

log = logging.getLogger(__name__)


class EndpointHandler:
    def __init__(self, path: str = ""):
        from qwen_tts import Qwen3TTSModel

        log.info("Loading Qwen3-TTS Base model...")
        try:
            self.model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
                device_map="cuda:0",
                dtype=torch.bfloat16,
                attn_implementation="flash_attention_2",
            )
        except ImportError:
            log.warning("flash-attn not available, falling back to sdpa")
            self.model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
                device_map="cuda:0",
                dtype=torch.bfloat16,
                attn_implementation="sdpa",
            )
        log.info("Qwen3-TTS Base model loaded.")

    def __call__(self, data: Any) -> dict:
        """Handle inference request.

        Input data format:
          {
            "inputs": str (text to synthesize),
            "ref_audio_base64": str (base64-encoded reference audio),
            "ref_text": str (transcript of reference audio),
            "language": str (target language),
          }

        Returns:
          {"audio_base64": str} — base64-encoded WAV audio
        """
        import soundfile as sf

        text = data.get("inputs", "")
        if not text:
            return {"error": "Missing 'inputs' field"}

        ref_audio_b64 = data.get("ref_audio_base64", "")
        ref_text = data.get("ref_text", "")
        language = data.get("language", "English")

        if not ref_audio_b64:
            return {"error": "Missing 'ref_audio_base64' field (base64-encoded reference audio)"}

        if not ref_text:
            return {"error": "Missing 'ref_text' field (transcript of reference audio)"}

        # Decode reference audio to a temp file
        ref_audio_bytes = base64.b64decode(ref_audio_b64)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(ref_audio_bytes)
            ref_audio_path = f.name

        try:
            log.info(f"Voice cloning: language={language}, text={text[:80]}...")

            wavs, sr = self.model.generate_voice_clone(
                text=text,
                language=language,
                ref_audio=ref_audio_path,
                ref_text=ref_text,
            )

            # Encode to WAV bytes
            buf = io.BytesIO()
            sf.write(buf, wavs[0], sr, format="WAV")
            wav_bytes = buf.getvalue()

            return {"audio_base64": base64.b64encode(wav_bytes).decode("ascii")}
        finally:
            import os
            os.unlink(ref_audio_path)
