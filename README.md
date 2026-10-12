# video-ai-cut

用豆包（火山方舟）**视频理解**识别视频内容，并在**关键点自动剪辑**出成片的流程。

## 原理

视频不能直接整段喂给大模型，本质是"抽帧成图 + 音频转文字"再交给多模态模型理解。本项目提供两条链路：

1. **豆包视频理解 API（最快通路）**：直接上传视频，服务端自动抽帧+转写，返回带时间戳的剪辑决策点。
2. **本地 ASR 管线骨架**：ffmpeg 抽音轨 → Whisper 转写 → 豆包生成剪辑决策单（离线、省 token，备选）。

```
视频 ──> 豆包视频理解(抽帧+转写) ──> 剪辑决策单(带时间码 JSON) ──> ffmpeg 自动裁剪 ──> 成片
```

## 脚本

| 文件 | 作用 |
|---|---|
| `run_video_understand.py` | 上传视频，豆包识别内容，输出概述 + 分段时间线 + 剪辑决策点 |
| `compact_understand.py` | 复用已上传 file_id，按"快节奏"标准细粒度识别可删除段 |
| `cut_video.py` | 读取剪辑决策单，ffmpeg 删除冗余区间，自动拼接成片 |
| `video_ai_cut_pipeline.py` | 本地 ffmpeg+ASR → 豆包决策的完整管线骨架（备用） |

## 快速开始

```bash
# 1. 安装依赖
pip install openai imageio-ffmpeg

# 2. 配置环境变量（不要把 Key 写进代码）
export ARK_API_KEY="你的火山方舟API Key"
# 或复制 .env.example 为 .env 并填写（脚本会自动读取）

# 3. 识别视频内容
python run_video_understand.py 你的视频.mp4 "去口误,去静默,保留高光段"

# 4. 按剪辑决策点自动裁剪成片
python cut_video.py 你的视频.mp4 成片.mp4
```

快节奏版（复用已上传文件，重新以更激进标准分析）：

```bash
python compact_understand.py <file_id>
python cut_video.py 你的视频.mp4 成片_紧凑版.mp4
```

## 模型

- 视频理解：`doubao-seed-2-1-pro-260628`（火山方舟，支持视频输入）
- 文本决策：`doubao-1-5-pro-256k-250115`（骨架管线用）

模型 ID 因账号开通情况而异，可在火山方舟控制台查看。

## 产物

- `out_video_understand/understand_result.json` —— 内容概述 + 剪辑决策点
- `out_video_understand/compact_result.json` —— 快节奏版细粒度剪辑点
- 成片 `.mp4` —— 自动裁剪后的视频

## 安全

- API Key 通过环境变量 / `.env` 读取，**不要提交到仓库**（`.env` 已在 `.gitignore` 排除）。
- 上传到方舟的视频默认仅存储 7 天。
- 识别结果来自你的私有素材，注意控制仓库内是否包含相关内容。

## 依赖

- `openai`（调用火山方舟 API）
- `imageio-ffmpeg`（预编译 ffmpeg，免编译）
- （可选）`openai-whisper` / `faster-whisper`（本地 ASR，Python 3.14 建议用 faster-whisper）

> 说明：本仓库只包含流程代码，不含任何 API Key、视频素材或私人识别结果。
