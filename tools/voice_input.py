#!/usr/bin/env python3
"""
前任 Skill 语音录入工具

功能：
  1. 录音：从麦克风录制音频
  2. 转写：将音频文件转为文字（支持本地 Whisper 和云端 API）
  3. 一键：录音 + 转写，直接输出文字

用法：
    # 一键录音转写（默认5秒）
    python voice_input.py --action record-transcribe --duration 5

    # 从已有音频文件转写
    python voice_input.py --action transcribe --input audio.wav

    # 仅录音
    python voice_input.py --action record --duration 10 --output recording.wav

    # 指定转写引擎
    python voice_input.py --action transcribe --input audio.wav --engine whisper-local
    python voice_input.py --action transcribe --input audio.wav --engine whisper-api --api-key YOUR_KEY

引擎说明：
    whisper-local : 使用 faster-whisper 本地转写（需安装 faster-whisper，首次使用自动下载模型）
    whisper-api   : 使用 OpenAI Whisper API 云端转写（需提供 --api-key 或设置 OPENAI_API_KEY 环境变量）
    edge-stt      : 使用 Microsoft Edge 在线语音识别（免费，无需 API Key，默认引擎）
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import wave
from pathlib import Path
from typing import Optional


def record_audio(output_path: str, duration: int = 5, sample_rate: int = 16000) -> str:
    """从麦克风录制音频并保存为 WAV 文件"""
    try:
        import pyaudio
    except ImportError:
        print("错误：需要安装 pyaudio。运行：pip install pyaudio", file=sys.stderr)
        print("或者使用 --action transcribe 从已有音频文件转写", file=sys.stderr)
        sys.exit(1)

    chunk = 1024
    format = pyaudio.paInt16
    channels = 1

    p = pyaudio.PyAudio()

    print(f"🎙️  录音中... ({duration}秒)")

    stream = p.open(
        format=format,
        channels=channels,
        rate=sample_rate,
        input=True,
        frames_per_buffer=chunk,
    )

    frames = []
    for _ in range(0, int(sample_rate / chunk * duration)):
        data = stream.read(chunk, exception_on_overflow=False)
        frames.append(data)

    print("✅ 录音完成")

    stream.stop_stream()
    stream.close()
    p.terminate()

    # 保存为 WAV
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(p.get_sample_size(format))
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames))

    return output_path


def transcribe_edge_stt(audio_path: str, language: str = "zh-CN") -> str:
    """使用 Microsoft Edge 在线语音识别（免费，无需 API Key）"""
    try:
        import speech_recognition as sr
    except ImportError:
        # 尝试安装
        import subprocess
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "SpeechRecognition",
            "--quiet",
        ])
        import speech_recognition as sr

    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_path) as source:
        audio_data = recognizer.record(source)

    try:
        text = recognizer.recognize_google(audio_data, language=language)
        return text
    except sr.UnknownValueError:
        return "[无法识别语音内容]"
    except sr.RequestError as e:
        return f"[语音识别服务错误: {e}]"


def transcribe_whisper_local(audio_path: str, model_size: str = "base") -> str:
    """使用 faster-whisper 本地转写"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("正在安装 faster-whisper...", file=sys.stderr)
        import subprocess
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "faster-whisper",
            "--quiet",
        ])
        from faster_whisper import WhisperModel

    print(f"加载 Whisper 模型 ({model_size})...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    print("转写中...")
    segments, info = model.transcribe(audio_path, language="zh", beam_size=5)

    text = "".join(segment.text for segment in segments).strip()
    return text if text else "[无法识别语音内容]"


def transcribe_whisper_api(audio_path: str, api_key: Optional[str] = None) -> str:
    """使用 OpenAI Whisper API 云端转写"""
    import os

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        return "[错误：未提供 API Key。使用 --api-key 或设置 OPENAI_API_KEY 环境变量]"

    try:
        from openai import OpenAI
    except ImportError:
        import subprocess
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "openai", "--quiet",
        ])
        from openai import OpenAI

    client = OpenAI(api_key=key)

    with open(audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="zh",
        )

    return transcript.text if transcript.text else "[无法识别语音内容]"


def transcribe(audio_path: str, engine: str = "edge-stt", **kwargs) -> dict:
    """统一的转写入口，返回结构化结果"""
    engines = {
        "edge-stt": transcribe_edge_stt,
        "whisper-local": transcribe_whisper_local,
        "whisper-api": transcribe_whisper_api,
    }

    if engine not in engines:
        print(f"错误：未知引擎 '{engine}'。可选：{', '.join(engines.keys())}", file=sys.stderr)
        sys.exit(1)

    transcribe_fn = engines[engine]

    # 根据引擎传递不同参数
    if engine == "whisper-local":
        text = transcribe_fn(audio_path, model_size=kwargs.get("model_size", "base"))
    elif engine == "whisper-api":
        text = transcribe_fn(audio_path, api_key=kwargs.get("api_key"))
    else:
        text = transcribe_fn(audio_path)

    result = {
        "text": text,
        "engine": engine,
        "audio_path": str(audio_path),
        "status": "success" if not text.startswith("[") else "error",
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="前任 Skill 语音录入工具")
    parser.add_argument(
        "--action",
        required=True,
        choices=["record", "transcribe", "record-transcribe"],
        help="操作类型",
    )
    parser.add_argument("--input", help="输入音频文件路径（transcribe 时使用）")
    parser.add_argument("--output", help="输出音频文件路径（record 时使用）")
    parser.add_argument("--duration", type=int, default=5, help="录音时长（秒，默认5）")
    parser.add_argument(
        "--engine",
        default="edge-stt",
        choices=["edge-stt", "whisper-local", "whisper-api"],
        help="转写引擎（默认 edge-stt）",
    )
    parser.add_argument("--api-key", help="OpenAI API Key（whisper-api 引擎使用）")
    parser.add_argument("--model-size", default="base", help="Whisper 模型大小（whisper-local 引擎使用）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")

    args = parser.parse_args()

    if args.action == "record":
        output = args.output or "recording.wav"
        record_audio(output, args.duration)
        if args.json:
            print(json.dumps({"audio_path": output, "duration": args.duration}, ensure_ascii=False))
        else:
            print(f"录音已保存到：{output}")

    elif args.action == "transcribe":
        if not args.input:
            print("错误：transcribe 操作需要 --input 参数", file=sys.stderr)
            sys.exit(1)
        result = transcribe(
            args.input,
            engine=args.engine,
            api_key=args.api_key,
            model_size=args.model_size,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"转写结果：{result['text']}")

    elif args.action == "record-transcribe":
        # 录音到临时文件，然后转写
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            record_audio(tmp_path, args.duration)
            result = transcribe(
                tmp_path,
                engine=args.engine,
                api_key=args.api_key,
                model_size=args.model_size,
            )
            result["duration"] = args.duration
        finally:
            # 清理临时文件
            Path(tmp_path).unlink(missing_ok=True)

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            status_icon = "✅" if result["status"] == "success" else "❌"
            print(f"{status_icon} 语音转写：{result['text']}")


if __name__ == "__main__":
    main()
