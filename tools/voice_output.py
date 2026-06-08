#!/usr/bin/env python3
"""
前任 Skill 音色输出工具

功能：
  1. 音色注册：录入语音样本 → 提取音色特征 → 保存音色配置
  2. 语音合成：文字 → 用注册的音色合成语音（TTS）
  3. 列出可用音色：查看已注册的音色和内置音色

用法：
    # 注册新音色（从音频样本）
    python voice_output.py --action register --slug chu_ge --sample voice_sample.wav

    # 使用已注册音色合成语音
    python voice_output.py --action synthesize --slug chu_ge --text "庆哥 在干嘛" --output output.mp3

    # 使用内置音色合成
    python voice_output.py --action synthesize --voice zh-CN-XiaoxiaoNeural --text "呵呵" --output output.mp3

    # 列出所有可用音色
    python voice_output.py --action list-voices

    # 列出已注册的音色
    python voice_output.py --action list-registered

音色系统说明：
    由于真正的声音克隆（Voice Cloning）需要大型 GPU 和训练时间，
    本工具采用"音色映射"方案：

    1. 注册时分析语音样本的声学特征（基频、语速、能量等）
    2. 从内置音色库中匹配最接近的音色
    3. 用匹配的音色 + 调整参数来模拟 TA 的声音

    内置音色基于 edge-tts（微软 Edge TTS），提供多种中文女声/男声。

    如需真正的声音克隆，可扩展接入：
    - Coqui TTS (开源，本地运行)
    - ElevenLabs API (商业，效果最好)
    - ChatTTS (开源，中文效果好)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


# ─── 内置音色库 ────────────────────────────────────────────

BUILTIN_VOICES = {
    # 中文女声
    "zh-CN-XiaoxiaoNeural": {"gender": "Female", "style": "活泼开朗", "age": "young"},
    "zh-CN-XiaoyiNeural": {"gender": "Female", "style": "温柔甜美", "age": "young"},
    "zh-CN-XiaohanNeural": {"gender": "Female", "style": "知性优雅", "age": "middle"},
    "zh-CN-XiaomengNeural": {"gender": "Female", "style": "可爱俏皮", "age": "young"},
    "zh-CN-XiaochenNeural": {"gender": "Female", "style": "温柔亲切", "age": "young"},
    "zh-CN-XiaoshuangNeural": {"gender": "Female", "style": "童声甜美", "age": "child"},
    "zh-CN-XiaoruiNeural": {"gender": "Female", "style": "沉稳大气", "age": "middle"},
    "zh-CN-XiaozhenNeural": {"gender": "Female", "style": "新闻播音", "age": "middle"},
    # 中文男声
    "zh-CN-YunjianNeural": {"gender": "Male", "style": "阳光帅气", "age": "young"},
    "zh-CN-YunxiNeural": {"gender": "Male", "style": "温暖磁性", "age": "young"},
    "zh-CN-YunxiaNeural": {"gender": "Male", "style": "少年清新", "age": "child"},
    "zh-CN-YunyangNeural": {"gender": "Male", "style": "新闻播音", "age": "middle"},
    # 中文台湾
    "zh-TW-HsiaoChenNeural": {"gender": "Female", "style": "台湾甜妹", "age": "young"},
    "zh-TW-YunJheNeural": {"gender": "Male", "style": "台湾暖男", "age": "young"},
}

# 声学特征到音色的映射规则
FEATURE_VOICE_MAP = {
    "Female_you": "zh-CN-XiaoxiaoNeural",      # 年轻女声默认
    "Female_sweet": "zh-CN-XiaoyiNeural",       # 甜美女声
    "Female_calm": "zh-CN-XiaoruiNeural",       # 沉稳女声
    "Female_cute": "zh-CN-XiaomengNeural",      # 可爱女声
    "Female_elegant": "zh-CN-XiaohanNeural",    # 优雅女声
    "Male_young": "zh-CN-YunjianNeural",         # 年轻男声默认
    "Male_warm": "zh-CN-YunxiNeural",            # 温暖男声
    "Male_calm": "zh-CN-YunyangNeural",          # 沉稳男声
}


def analyze_voice_sample(sample_path: str) -> dict:
    """分析语音样本的声学特征"""
    import numpy as np

    try:
        import soundfile as sf
    except ImportError:
        print("错误：需要安装 soundfile。运行：pip install soundfile", file=sys.stderr)
        sys.exit(1)

    data, sr = sf.read(sample_path)

    # 如果是立体声，转为单声道
    if len(data.shape) > 1:
        data = data.mean(axis=1)

    # 计算基本声学特征
    rms = np.sqrt(np.mean(data ** 2))  # 均方根能量
    peak = np.max(np.abs(data))  # 峰值

    # 简单的基频估计（自相关法）
    def estimate_f0(signal, sample_rate, frame_size=2048):
        """简单的基频估计"""
        frame = signal[:frame_size] if len(signal) >= frame_size else signal
        correlation = np.correlate(frame, frame, mode="full")
        correlation = correlation[len(correlation) // 2:]

        # 找第一个峰值
        d = np.diff(correlation)
        start = np.where(d > 0)[0]
        if len(start) == 0:
            return 0
        start = start[0]
        peak_idx = start + np.argmax(correlation[start:])
        if peak_idx > 0:
            return sample_rate / peak_idx
        return 0

    f0 = estimate_f0(data, sr)

    # 计算语速（零交叉率近似）
    zero_crossings = np.sum(np.diff(np.sign(data)) != 0)
    duration = len(data) / sr
    zcr = zero_crossings / (2 * duration) if duration > 0 else 0

    # 基频判断性别
    gender = "Female" if f0 > 160 else "Male"

    # 能量判断风格
    energy_level = "high" if rms > 0.1 else "medium" if rms > 0.03 else "low"

    # 语速判断
    speech_rate = "fast" if zcr > 2000 else "medium" if zcr > 1000 else "slow"

    features = {
        "gender": gender,
        "f0": round(f0, 1),
        "rms_energy": round(float(rms), 4),
        "peak_amplitude": round(float(peak), 4),
        "zero_crossing_rate": round(float(zcr), 1),
        "duration_seconds": round(duration, 2),
        "energy_level": energy_level,
        "speech_rate": speech_rate,
        "estimated_age": "young",  # 简化处理
    }

    return features


def match_voice(features: dict) -> str:
    """根据声学特征匹配最接近的内置音色"""
    gender = features.get("gender", "Female")
    energy = features.get("energy_level", "medium")
    rate = features.get("speech_rate", "medium")

    # 构建匹配键
    if gender == "Female":
        if energy == "high" or rate == "fast":
            return FEATURE_VOICE_MAP["Female_you"]     # 活泼
        elif energy == "low" and rate == "slow":
            return FEATURE_VOICE_MAP["Female_calm"]    # 沉稳
        else:
            return FEATURE_VOICE_MAP["Female_sweet"]   # 默认温柔
    else:
        if energy == "high" or rate == "fast":
            return FEATURE_VOICE_MAP["Male_young"]     # 阳光
        elif energy == "low" and rate == "slow":
            return FEATURE_VOICE_MAP["Male_calm"]      # 沉稳
        else:
            return FEATURE_VOICE_MAP["Male_warm"]      # 温暖


def register_voice(slug: str, sample_path: str, base_dir: str = "./exes",
                   voice_override: Optional[str] = None,
                   style_override: Optional[str] = None) -> dict:
    """注册音色：分析样本 → 匹配音色 → 保存配置"""

    base = Path(base_dir)
    voice_dir = base / slug / "knowledge" / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    # 分析语音样本
    features = analyze_voice_sample(sample_path)

    # 匹配音色
    if voice_override:
        matched_voice = voice_override
    else:
        matched_voice = match_voice(features)

    # 获取音色信息
    voice_info = BUILTIN_VOICES.get(matched_voice, {"gender": "Unknown", "style": "自定义", "age": "unknown"})

    # 构建音色配置
    voice_config = {
        "slug": slug,
        "registered_at": datetime.now().isoformat(),
        "source_sample": str(sample_path),
        "features": features,
        "matched_voice": matched_voice,
        "voice_info": voice_info,
        "style": style_override or voice_info.get("style", "默认"),
        "rate": "+0%",
        "pitch": "+0Hz",
        "volume": "+0%",
    }

    # 根据特征微调参数
    if features["speech_rate"] == "fast":
        voice_config["rate"] = "+15%"
    elif features["speech_rate"] == "slow":
        voice_config["rate"] = "-10%"

    # 保存配置
    config_path = voice_dir / "voice_config.json"
    config_path.write_text(json.dumps(voice_config, ensure_ascii=False, indent=2), encoding="utf-8")

    # 复制样本到知识库
    import shutil
    sample_dest = voice_dir / "sample" + Path(sample_path).suffix
    shutil.copy2(sample_path, sample_dest)

    return voice_config


async def synthesize_speech(
    text: str,
    output_path: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
    style: Optional[str] = None,
) -> str:
    """使用 edge-tts 合成语音"""
    try:
        import edge_tts
    except ImportError:
        print("错误：需要安装 edge-tts。运行：pip install edge-tts", file=sys.stderr)
        sys.exit(1)

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
    )

    await communicate.save(output_path)
    return output_path


def synthesize(
    text: str,
    output_path: str,
    slug: Optional[str] = None,
    voice: Optional[str] = None,
    base_dir: str = "./exes",
) -> dict:
    """统一的语音合成入口"""

    # 优先使用 slug 查找已注册音色
    if slug and not voice:
        config_path = Path(base_dir) / slug / "knowledge" / "voice" / "voice_config.json"
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            voice = config["matched_voice"]
            rate = config.get("rate", "+0%")
            pitch = config.get("pitch", "+0Hz")
            volume = config.get("volume", "+0%")
            style = config.get("style")
        else:
            print(f"⚠️ 未找到 {slug} 的音色配置，使用默认音色", file=sys.stderr)
            voice = voice or "zh-CN-XiaoxiaoNeural"
            rate, pitch, volume, style = "+0%", "+0Hz", "+0%", None
    else:
        voice = voice or "zh-CN-XiaoxiaoNeural"
        rate, pitch, volume, style = "+0%", "+0Hz", "+0%", None

    # 运行异步合成
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            synthesize_speech(text, output_path, voice, rate, pitch, volume, style)
        )
    finally:
        loop.close()

    result = {
        "text": text,
        "output_path": output_path,
        "voice": voice,
        "rate": rate,
        "pitch": pitch,
        "status": "success",
    }

    return result


def list_voices(gender: Optional[str] = None) -> list:
    """列出所有内置音色"""
    voices = []
    for name, info in BUILTIN_VOICES.items():
        if gender and info["gender"].lower() != gender.lower():
            continue
        voices.append({"name": name, **info})
    return voices


def list_registered(base_dir: str = "./exes") -> list:
    """列出所有已注册的音色"""
    base = Path(base_dir)
    registered = []

    if not base.exists():
        return registered

    for slug_dir in sorted(base.iterdir()):
        if not slug_dir.is_dir():
            continue
        config_path = slug_dir / "knowledge" / "voice" / "voice_config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                registered.append(config)
            except Exception:
                continue

    return registered


def main() -> None:
    parser = argparse.ArgumentParser(description="前任 Skill 音色输出工具")
    parser.add_argument(
        "--action",
        required=True,
        choices=["register", "synthesize", "list-voices", "list-registered"],
        help="操作类型",
    )
    parser.add_argument("--slug", help="前任 slug（用于查找音色配置）")
    parser.add_argument("--sample", help="语音样本文件路径（register 时使用）")
    parser.add_argument("--text", help="要合成的文字（synthesize 时使用）")
    parser.add_argument("--output", help="输出文件路径（默认：output.mp3）")
    parser.add_argument("--voice", help="指定音色名称（覆盖已注册音色）")
    parser.add_argument("--style", help="指定风格描述（register 时使用）")
    parser.add_argument("--base-dir", default="./exes", help="前任 Skill 根目录")
    parser.add_argument("--gender", choices=["Female", "Male"], help="筛选性别（list-voices 时使用）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")

    args = parser.parse_args()

    if args.action == "register":
        if not args.slug:
            print("错误：register 操作需要 --slug 参数", file=sys.stderr)
            sys.exit(1)
        if not args.sample:
            print("错误：register 操作需要 --sample 参数（语音样本文件）", file=sys.stderr)
            sys.exit(1)

        config = register_voice(
            slug=args.slug,
            sample_path=args.sample,
            base_dir=args.base_dir,
            voice_override=args.voice,
            style_override=args.style,
        )

        if args.json:
            print(json.dumps(config, ensure_ascii=False, indent=2))
        else:
            print(f"✅ 音色注册完成！")
            print(f"   匹配音色：{config['matched_voice']}")
            print(f"   音色风格：{config.get('voice_info', {}).get('style', '未知')}")
            print(f"   检测性别：{config['features']['gender']}")
            print(f"   基频估计：{config['features']['f0']} Hz")
            print(f"   语速等级：{config['features']['speech_rate']}")

    elif args.action == "synthesize":
        if not args.text:
            print("错误：synthesize 操作需要 --text 参数", file=sys.stderr)
            sys.exit(1)

        output = args.output or "output.mp3"
        result = synthesize(
            text=args.text,
            output_path=output,
            slug=args.slug,
            voice=args.voice,
            base_dir=args.base_dir,
        )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"✅ 语音合成完成：{output}")
            print(f"   音色：{result['voice']}")
            print(f"   文字：{result['text']}")

    elif args.action == "list-voices":
        voices = list_voices(gender=args.gender)
        if args.json:
            print(json.dumps(voices, ensure_ascii=False, indent=2))
        else:
            print(f"可用内置音色 ({len(voices)} 个)：\n")
            for v in voices:
                print(f"  {v['name']}")
                print(f"    性别: {v['gender']}  风格: {v['style']}  年龄: {v['age']}")
                print()

    elif args.action == "list-registered":
        registered = list_registered(base_dir=args.base_dir)
        if args.json:
            print(json.dumps(registered, ensure_ascii=False, indent=2))
        else:
            if not registered:
                print("暂无已注册的音色")
            else:
                print(f"已注册音色 ({len(registered)} 个)：\n")
                for r in registered:
                    print(f"  [{r['slug']}]")
                    print(f"    匹配音色: {r['matched_voice']}")
                    print(f"    风格: {r.get('style', '未知')}")
                    print(f"    注册时间: {r.get('registered_at', '未知')}")
                    print()


if __name__ == "__main__":
    main()
