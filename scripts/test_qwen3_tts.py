#!/usr/bin/env python3
"""Test Qwen3-TTS voices locally to preview speakers, languages, styles, and voice cloning.

Usage:
  python scripts/test_qwen3_tts.py                    # Preview all speakers
  python scripts/test_qwen3_tts.py --speaker Ryan     # Test one speaker with styles
  python scripts/test_qwen3_tts.py --speaker Vivian --language Chinese --instruct "用愤怒的语气说"
  python scripts/test_qwen3_tts.py --all              # Full test suite
  python scripts/test_qwen3_tts.py --text "Your custom text" --speaker Ryan
  python scripts/test_qwen3_tts.py --clone ref.wav --ref-text "Hello there" --text "New words in that voice"
  python scripts/test_qwen3_tts.py --clone ref.wav --ref-text "Hello there" --texts "Line one" "Line two" "Line three"

Output files are saved to ./tts_output/
"""

import argparse
import base64
import os
import subprocess
import sys
import tempfile

SPEAKERS = {
    "Vivian": {"desc": "Bright, slightly edgy young female voice.", "native": "Chinese"},
    "Serena": {"desc": "Warm, gentle young female voice.", "native": "Chinese"},
    "Uncle_Fu": {"desc": "Seasoned male voice with a low, mellow timbre.", "native": "Chinese"},
    "Dylan": {"desc": "Youthful Beijing male voice with a clear, natural timbre.", "native": "Chinese (Beijing Dialect)"},
    "Eric": {"desc": "Lively Chengdu male voice with a slightly husky brightness.", "native": "Chinese (Sichuan Dialect)"},
    "Ryan": {"desc": "Dynamic male voice with strong rhythmic drive.", "native": "English"},
    "Aiden": {"desc": "Sunny American male voice with a clear midrange.", "native": "English"},
    "Ono_Anna": {"desc": "Playful Japanese female voice with a light, nimble timbre.", "native": "Japanese"},
    "Sohee": {"desc": "Warm Korean female voice with rich emotion.", "native": "Korean"},
}

SAMPLE_TEXTS = {
    "English": "Welcome to ASEAN Motor Club Radio! We've got the hottest tracks and the latest news from the server.",
    "Chinese": "欢迎来到东盟汽车俱乐部电台！我们为您带来最热门的曲目和服务器最新消息。",
    "Japanese": "ASEANモータークラブラジオへようこそ！サーバーの最新ニュースと hottest トラックをお届けします。",
    "Korean": "ASEAN 모터 클럽 라디오에 오신 것을 환영합니다! 서버의 최신 뉴스와 인기 곡을 준비했습니다.",
    "German": "Willkommen bei ASEAN Motor Club Radio! Wir haben die heißesten Tracks und die neuesten Nachrichten.",
    "French": "Bienvenue sur ASEAN Motor Club Radio ! Nous avons les meilleurs morceaux et les dernières nouvelles.",
}

INSTRUCT_SAMPLES = [
    "",
    "Speak in an excited, energetic tone.",
    "Whisper quietly.",
    "Speak very slowly and dramatically.",
    "Sound angry and frustrated.",
    "Sound calm and soothing.",
]


def wav_to_mp3(wav_path: str, mp3_path: str, volume_gain_db: float = 0.0) -> str:
    """Convert WAV to MP3 via ffmpeg."""
    cmd = ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-qscale:a", "2"]
    if volume_gain_db != 0:
        cmd.extend(["-af", f"volume={10 ** (volume_gain_db / 20):.4f}"])
    cmd.append(mp3_path)
    subprocess.run(cmd, capture_output=True, check=True)
    return mp3_path


def synthesize(endpoint_url: str, token: str, text: str, speaker: str,
               language: str, instruct: str, output_path: str) -> bool:
    """Call HF CustomVoice endpoint, convert WAV->MP3, save to output_path."""
    import requests

    print(f"  [{speaker}/{language}] {instruct or '(default)'}: {text[:60]}...")

    try:
        resp = requests.post(
            endpoint_url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "inputs": text,
                "speaker": speaker,
                "language": language,
                "instruct": instruct,
            },
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()

        if "error" in result:
            print(f"    ERROR: {result['error']}")
            return False

        wav_bytes = base64.b64decode(result["audio_base64"])

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            wav_path = f.name

        try:
            wav_to_mp3(wav_path, output_path)
            size_kb = os.path.getsize(output_path) / 1024
            print(f"    -> {output_path} ({size_kb:.1f} KB)")
            return True
        finally:
            os.unlink(wav_path)

    except Exception as e:
        print(f"    FAILED: {e}")
        return False


def synthesize_clone(endpoint_url: str, token: str, text: str,
                     ref_audio_path: str, ref_text: str,
                     language: str, output_path: str) -> bool:
    """Call HF Base model endpoint for voice cloning, convert WAV->MP3, save."""
    import requests

    print(f"  [clone/{language}] {text[:60]}...")

    try:
        with open(ref_audio_path, "rb") as f:
            ref_audio_b64 = base64.b64encode(f.read()).decode("ascii")

        resp = requests.post(
            endpoint_url,
            headers={"Authorization": f"Bearer {token}"},
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
            print(f"    ERROR: {result['error']}")
            return False

        wav_bytes = base64.b64decode(result["audio_base64"])

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            wav_path = f.name

        try:
            wav_to_mp3(wav_path, output_path)
            size_kb = os.path.getsize(output_path) / 1024
            print(f"    -> {output_path} ({size_kb:.1f} KB)")
            return True
        finally:
            os.unlink(wav_path)

    except Exception as e:
        print(f"    FAILED: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test Qwen3-TTS voices")
    parser.add_argument("--endpoint", default=os.environ.get("QWEN3_TTS_ENDPOINT_URL", ""),
                        help="CustomVoice endpoint URL (or set QWEN3_TTS_ENDPOINT_URL)")
    parser.add_argument("--token", default=os.environ.get("QWEN3_TTS_API_TOKEN", ""),
                        help="HF API token (or set QWEN3_TTS_API_TOKEN)")
    parser.add_argument("--speaker", help="Test a specific speaker")
    parser.add_argument("--language", default="English", help="Language to test")
    parser.add_argument("--instruct", default="", help="Style instruction")
    parser.add_argument("--text", help="Custom text to synthesize")
    parser.add_argument("--all", action="store_true", help="Full test suite (all speakers x styles)")
    parser.add_argument("--output-dir", default="./tts_output", help="Output directory")

    # Voice cloning options
    clone_group = parser.add_argument_group("Voice cloning")
    clone_group.add_argument("--clone", metavar="REF_AUDIO",
                             help="Reference audio file (WAV/MP3) for voice cloning")
    clone_group.add_argument("--ref-text", metavar="TRANSCRIPT",
                             help="Transcript of the reference audio")
    clone_group.add_argument("--clone-endpoint",
                             default=os.environ.get("QWEN3_TTS_CLONE_ENDPOINT_URL", ""),
                             help="Clone endpoint URL (or set QWEN3_TTS_CLONE_ENDPOINT_URL)")
    clone_group.add_argument("--texts", nargs="+", metavar="TEXT",
                             help="Multiple texts to synthesize in the cloned voice")
    clone_group.add_argument("--clone-lang", default="English",
                             help="Language for cloned output")

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # --- Voice cloning mode ---
    if args.clone:
        if not args.clone_endpoint:
            print("ERROR: Set QWEN3_TTS_CLONE_ENDPOINT_URL or pass --clone-endpoint")
            sys.exit(1)
        if not args.token:
            print("ERROR: Set QWEN3_TTS_API_TOKEN or pass --token")
            sys.exit(1)
        if not args.ref_text:
            print("ERROR: Pass --ref-text with the transcript of the reference audio")
            sys.exit(1)
        if not os.path.exists(args.clone):
            print(f"ERROR: Reference audio not found: {args.clone}")
            sys.exit(1)

        texts = args.texts or ([args.text] if args.text else [
            "Welcome to ASEAN Motor Club Radio! We've got the hottest tracks.",
            "Breaking news from the server — a new race event is starting!",
            "Thanks for tuning in. Stay safe on the roads!",
        ])

        print(f"=== Voice Cloning: {args.clone} ===")
        print(f"    Reference transcript: {args.ref_text[:80]}\n")

        for i, text in enumerate(texts):
            name = f"clone_{i}" if len(texts) > 1 else "clone"
            out = os.path.join(args.output_dir, f"{name}_{args.clone_lang}.mp3")
            synthesize_clone(
                args.clone_endpoint, args.token, text,
                args.clone, args.ref_text, args.clone_lang, out,
            )

        print(f"\nDone. {len(texts)} cloned file(s) in {args.output_dir}/")
        return

    # --- CustomVoice mode (below) ---
    if not args.endpoint:
        print("ERROR: Set QWEN3_TTS_ENDPOINT_URL or pass --endpoint")
        sys.exit(1)
    if not args.token:
        print("ERROR: Set QWEN3_TTS_API_TOKEN or pass --token")
        sys.exit(1)

    if args.text and args.speaker:
        out = os.path.join(args.output_dir, f"{args.speaker}_{args.language}.mp3")
        ok = synthesize(args.endpoint, args.token, args.text, args.speaker,
                        args.language, args.instruct, out)
        sys.exit(0 if ok else 1)

    if args.all:
        print("=== Full Test Suite: All Speakers x Styles ===\n")
        for speaker, info in SPEAKERS.items():
            lang = info["native"].split(" (")[0]
            text = SAMPLE_TEXTS.get(lang, SAMPLE_TEXTS["English"])
            for i, instruct in enumerate(INSTRUCT_SAMPLES):
                suffix = f"_style{i}" if instruct else ""
                out = os.path.join(args.output_dir, f"{speaker}_{lang}{suffix}.mp3")
                synthesize(args.endpoint, args.token, text, speaker, lang, instruct, out)
        print(f"\nDone. Files in {args.output_dir}/")
        return

    if args.speaker:
        info = SPEAKERS[args.speaker]
        lang = info["native"].split(" (")[0]
        text = args.text or SAMPLE_TEXTS.get(lang, SAMPLE_TEXTS["English"])
        print(f"=== Testing {args.speaker} ({info['desc']}) ===\n")
        for i, instruct in enumerate(INSTRUCT_SAMPLES):
            suffix = f"_style{i}" if instruct else ""
            out = os.path.join(args.output_dir, f"{args.speaker}_{lang}{suffix}.mp3")
            synthesize(args.endpoint, args.token, text, args.speaker, lang, instruct, out)
        print(f"\nDone. Files in {args.output_dir}/")
        return

    # Default: one sample per speaker
    print("=== Quick Preview: One Sample Per Speaker ===\n")
    for speaker, info in SPEAKERS.items():
        lang = info["native"].split(" (")[0]
        text = SAMPLE_TEXTS.get(lang, SAMPLE_TEXTS["English"])
        out = os.path.join(args.output_dir, f"{speaker}_{lang}.mp3")
        synthesize(args.endpoint, args.token, text, speaker, lang, "", out)

    print(f"\nDone. {len(SPEAKERS)} files saved to {args.output_dir}/")
    print("Play them to choose your favorite voice, then set QWEN3_TTS_DEFAULT_SPEAKER.")


if __name__ == "__main__":
    main()
