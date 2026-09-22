"""Generate a two-speaker local Qwen debate with real Qwen3-TTS audio.

This is an isolated operator smoke test, not a Maya Provider or paid call.
Its output directory must be outside the repository's tracked tree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


def _local_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("LLM endpoint must be a loopback HTTP server")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("LLM endpoint must not contain credentials or query parameters")
    if parsed.path not in {"", "/"}:
        raise ValueError("LLM endpoint must be the local server root")
    return raw.rstrip("/") + "/v1/chat/completions"


def _speech(
    client: httpx.Client,
    endpoint: str,
    model: str,
    role: str,
    prompt: str,
    *,
    opening: bool = False,
) -> str:
    response = client.post(
        endpoint,
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"你扮演{role}，参加国风人文课堂辩论。"
                        "只返回简体中文发言正文，约60到100字；提出观点和理由；"
                        + (
                            "这是首轮，尚无对方发言；不得假设、转述或回应对方观点。"
                            if opening
                            else "回应给定对方发言的具体观点，不虚构其余观点。"
                        )
                        + "不虚构引文，不自称AI。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 220,
            "temperature": 0.7,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("local LLM returned an invalid choice list")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip() or len(content) > 2000:
        raise ValueError("local LLM returned no bounded speech text")
    if "<think>" in content.lower() or "</think>" in content.lower():
        raise ValueError("local LLM returned reasoning instead of speech")
    return content.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-url", default="http://127.0.0.1:1236")
    parser.add_argument("--llm-model", required=True)
    parser.add_argument("--tts-model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--topic", default="如何在公共决策中兼顾个人自由与共同责任？")
    args = parser.parse_args()
    endpoint = _local_url(args.llm_url)
    if not args.tts_model_dir.is_dir() or not (args.tts_model_dir / "model.safetensors").is_file():
        raise SystemExit("Qwen3-TTS model weights are incomplete")
    if args.output_dir.exists():
        raise SystemExit("output directory already exists; choose a new run directory")
    if args.output_dir.resolve().is_relative_to(Path(__file__).resolve().parent.parent):
        raise SystemExit("generated media must stay outside the repository")
    if not torch.cuda.is_available():
        raise SystemExit("local smoke test requires a CUDA GPU")

    with httpx.Client(timeout=180.0, trust_env=False) as client:
        first = _speech(
            client,
            endpoint,
            args.llm_model,
            "老子",
            f"辩题：{args.topic}\n请先发言。",
            opening=True,
        )
        second = _speech(
            client,
            endpoint,
            args.llm_model,
            "柏拉图",
            f"辩题：{args.topic}\n老子说：{first}\n请回应。",
        )

    tts = Qwen3TTSModel.from_pretrained(
        str(args.tts_model_dir),
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="eager",
    )
    entries = (
        ("laozi", "debate", "老子", "Uncle_Fu", first),
        ("plato", "debate", "柏拉图", "Dylan", second),
        (
            "woman",
            "sample",
            "女声试听",
            "Serena",
            "自由与责任并非敌人，倾听不同意见，才有共同生活的空间。",
        ),
    )
    args.output_dir.mkdir(parents=True)
    turns = []
    for name, kind, character, speaker, speech in entries:
        wavs, sample_rate = tts.generate_custom_voice(
            text=speech, language="Chinese", speaker=speaker
        )
        if len(wavs) != 1 or sample_rate <= 0:
            raise RuntimeError("Qwen3-TTS returned invalid audio")
        audio_file = f"{name}.wav"
        target = args.output_dir / audio_file
        sf.write(target, wavs[0], sample_rate, subtype="PCM_16")
        info = sf.info(target)
        if info.duration < 0.3 or info.channels != 1:
            raise RuntimeError("Qwen3-TTS output failed audio validation")
        turns.append(
            {
                "character": character,
                "kind": kind,
                "speaker_id": speaker,
                "speech": speech,
                "audio_file": audio_file,
                "duration_seconds": round(info.duration, 3),
            }
        )
        print(f"{character}: {speaker}, {info.duration:.1f}s, {audio_file}")
    manifest = {"topic": args.topic, "turns": turns}
    temporary = args.output_dir / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output_dir / "manifest.json")


if __name__ == "__main__":
    main()
