# Ex Skill — 前任数字人格生成器

从微信聊天记录重建前任的数字人格，支持语音录入和音色输出。

## 功能特性

- 🔍 **聊天记录分析**：从微信/iMessage 聊天记录自动提取人格特征
- 👤 **Persona 生成**：基于真实数据分析，生成可交互的数字人格
- 🎙️ **语音录入**：支持麦克风录音→文字转写（多种STT引擎）
- 🔊 **音色输出**：注册TA的音色，让回复用TA的声音说出来
- 📈 **持续进化**：追加记录、对话纠正、版本管理

## 快速开始

### 创建前任 Persona

```
/create-ex
```

按引导录入基础信息 → 导入聊天记录 → 自动分析 → 生成预览 → 确认创建

### 语音功能

```bash
# 语音录入（录音 + 转写）
python tools/voice_input.py --action record-transcribe --duration 5 --json

# 注册音色
python tools/voice_output.py --action register --slug xiaomei --sample voice.wav --base-dir ./exes

# 语音合成
python tools/voice_output.py --action synthesize --slug xiaomei --text "呵呵" --output reply.mp3 --base-dir ./exes

# 查看可用音色
python tools/voice_output.py --action list-voices
```

## 项目结构

```
ex-skill/
├── SKILL.md              # 主 Skill 文件
├── docs/
│   └── PRD.md            # 产品需求文档
├── prompts/
│   ├── intake.md         # 基础信息录入
│   ├── chat_analyzer.md  # 聊天记录分析
│   ├── persona_analyzer.md
│   ├── persona_builder.md
│   ├── merger.md
│   └── correction_handler.md
├── tools/
│   ├── wechat_decryptor.py  # 微信数据库解密
│   ├── wechat_parser.py     # 聊天记录解析
│   ├── skill_writer.py      # Skill 文件写入
│   ├── version_manager.py   # 版本管理
│   ├── voice_input.py       # 🆕 语音录入
│   └── voice_output.py      # 🆕 音色输出
└── exes/                    # 生成的 Persona 存放处
    └── {slug}/
        ├── SKILL.md
        ├── persona.md
        ├── meta.json
        ├── versions/
        └── knowledge/
            ├── chats/
            ├── photos/
            └── voice/        # 🆕 音色配置
```

## 依赖

- Python 3.10+
- edge-tts（语音合成，免费）
- soundfile + numpy（音频分析）
- SpeechRecognition（语音识别，可选）
- faster-whisper（本地STT，可选）
- openai（云端Whisper API，可选）

## 许可

MIT License
