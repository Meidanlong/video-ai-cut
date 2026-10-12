# video-ai-cut

用豆包（火山方舟）**视频理解 + 音频理解**识别视频内容，在**关键点自动剪辑**，并一键合成**短视频成品**（降噪 + 背景音乐 + 可自定义字体的字幕）。

## 原理

视频不能直接整段喂给大模型，本质是"抽帧成图 + 音频转文字"再交给多模态模型理解。本项目提供完整链路：

```
视频 ──> 豆包视频理解(服务端抽帧+转写) ──> 剪辑决策单(带时间码 JSON)
        └──> ffmpeg 抽音轨 ──> 豆包音频理解 ──> 带时间戳字幕(SRT)
视频 + 决策单 + 字幕 + BGM ──> ffmpeg(降噪+裁剪+混音+烧字幕) ──> 短视频成片
```

## 脚本

| 文件 | 作用 |
|---|---|
| `run_video_understand.py` | 上传视频，豆包识别内容，输出概述 + 分段时间线 + 剪辑决策点 |
| `compact_understand.py` | 复用已上传 file_id，按"快节奏"标准细粒度识别可删除段 |
| `understand_roles.py` | **理解层角色标注**：结合 ASR 语音字幕 + 画面，把视频逐段标注为「核心结果/关键动作/铺垫说明/冗余语音/冗余空白/废镜头」 |
| `roles_to_plan.py` | 角色标注 → **分层剪辑决策**：删冗余(冗余语音/空白/废镜头)、保核心(核心结果/关键动作/铺垫)，并强制保护「结果句」语音不被删除区间吃掉 |
| `check_cut.py` | **关键信息校验门**：核对结果/输赢句是否都在保留段内，缺失即报错退出 1 |
| `fix_plan.py` | 字幕保护兜底：有语音的段落不删，只删无言停顿 |
| `audio_to_srt.py` | 抽音轨上传，豆包"音频理解"转写为带时间戳的 SRT 字幕 |
| `srt_to_ass.py` | SRT → 带设计样式的 ASS 字幕（自定义字体/字号/颜色/描边），支持超宽折行、左右安全边距 |
| `cut_video.py` | 按剪辑决策单裁剪成片（优化版：场景切点吸附 + 音频 afade 平滑 + 可选静默检测） |
| `final_cut.py` | **成品合成**：字幕烧录 + 降噪(afftdn) + 按决策单裁剪 + BGM 混音，一步出片 |
| `video_ai_cut_pipeline.py` | 本地 ffmpeg+ASR → 豆包决策的完整管线骨架（备用） |

## 理解层分层剪辑（推荐流程）

剪辑是否准，取决于 AI 是否真的「读懂」视频，而不是脚本兜底。正确顺序：

```
角色标注(understand_roles.py)
  └─ 豆包结合 ASR 语音字幕 + 画面，把每段标成：
       核心结果(报结果/输赢/金额) / 关键动作 / 铺垫说明
       / 冗余语音(查规则/重复解说) / 冗余空白 / 废镜头
        │
        ▼
分层决策(roles_to_plan.py)
  └─ 删：冗余语音 / 冗余空白 / 废镜头
  └─ 保：核心结果 / 关键动作 / 铺垫说明
  └─ 强制保护「结果句」语音（ASR 关键词），删除区间不切到报结果
        │
        ▼
校验(check_cut.py) —— 结果/输赢句缺失即报错
        │
        ▼
出片(final_cut.py)
```

**核心原则**：紧凑是要素，但优先级低于「重要环节（结果/高光）必须完整」；反过来，重要环节内部的拖沓（查规则、无效重复、废镜头）照样删。

## 专有名词澄清（重要）

人名、地名、景观、美食等**特殊指向专有名词**必须准确，不能将错就错。ASR 转写可能写错人名（如「韩欣彤」误作「韩雨桐」）。**流程中凡涉及专有名词，若不确定应先向用户澄清，确认正确写法后再落字幕。**

## 快速开始

```bash
# 1. 安装依赖
pip install openai imageio-ffmpeg

# 2. 配置环境变量（不要把 Key 写进代码）
export ARK_API_KEY="你的火山方舟API Key"
# 或复制 .env.example 为 .env 并填写（脚本会自动读取）

# 3a. 理解层角色标注（结合 ASR 字幕，需先转写）
python audio_to_srt.py 音轨.mp3 out_video_understand/transcript.srt
python understand_roles.py <file_id>
python roles_to_plan.py
python check_cut.py out_video_understand/compact_result.json out_video_understand/transcript.srt

# 4. 一键合成短视频成品（降噪 + 裁剪 + BGM + 字幕）
python final_cut.py 你的视频.mp4 成片_成品版.mp4
```

只裁剪不加成品功能（快节奏/优化版）：

```bash
python compact_understand.py <file_id>
python cut_video.py 你的视频.mp4 成片_紧凑版.mp4
```

## final_cut.py 可选项

| 参数 | 说明 |
|---|---|
| `--fontname` | 字幕字体名（默认 `PingFang SC` 苹方，可换任意系统字体） |
| `--fontsize` | 字幕字号（默认 80，竖屏 1080 基准） |
| `--bgm-volume` | BGM 音量 0-1（默认 0.26，不压人声） |
| `--bgm 文件.mp3` | 指定 BGM 文件 |
| `--no-bgm` / `--no-noise` | 关闭背景音乐 / 降噪 |
| `--plan` | 指定剪辑决策单 |

字幕颜色/描边/位置等样式模板在 `srt_to_ass.py` 的 `STYLE_TEMPLATE` 中调整。

## 模型

- 视频理解：`doubao-seed-2-1-pro-260628`（火山方舟，支持视频输入）
- 音频理解/转写：`doubao-seed-2-0-lite-260428`（同一个 API Key，支持音频输入）

模型 ID 因账号开通情况而异，可在火山方舟控制台查看。

## 产物

- `out_video_understand/understand_result.json` —— 内容概述 + 剪辑决策点
- `out_video_understand/compact_result.json` —— 分层剪辑决策单（删除段 + 保留段）
- `out_video_understand/roles_result.json` —— 角色标注结果（逐段角色）
- `out_video_understand/transcript.srt` —— 语音转写字幕
- `*.ass` —— 设计样式的字幕（最终烧录进视频）
- 成片 `.mp4` —— 自动裁剪 + 降噪 + BGM + 字幕的短视频成品

## 安全

- API Key 通过环境变量 / `.env` 读取，**不要提交到仓库**（`.env` 已在 `.gitignore` 排除）。
- 上传到方舟的视频/音频默认仅存储 7 天。
- BGM 请使用**免版权/CC 协议**曲目，并在视频简介注明出处（例如 CC BY 需署名）。
- 识别结果来自你的私有素材，注意控制仓库内是否包含相关内容。

## 依赖

- `openai`（调用火山方舟 API）
- `imageio-ffmpeg`（预编译 ffmpeg，免编译）

> 说明：本仓库只包含流程代码，不含任何 API Key、视频素材、BGM 或私人识别结果。
