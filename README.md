[English](#english) | [中文](#chinese)

---

<a id="english"></a>

# Siftly

A desktop tool that uses the [Twelve Labs](https://www.twelvelabs.io/) video understanding API to find highlights in your footage, then generates a DaVinci Resolve project ready to edit.

## Features

### DaVinci Resolve Integration
- Pick your clips, hit export, get a Resolve project with media pool and timeline already set up
- Frame rate, resolution, working folders — all configurable
- OTIO export also available if you don't use Resolve

### Upload
- **LOG footage support** — auto-detects camera LOG profiles (S-Log3, C-Log2, V-Log, etc.) and applies a LUT before indexing for better search results
- Drag-and-drop files or browse folders
- Auto-transcodes >720p, auto-splits >1.8 GB
- Parallel uploads with progress tracking

### Highlights
Three ways to find clips:
- **Auto-detect** — let the AI pick the best moments, returns titles, categories, and confidence scores
- **Categories** — one-click presets (scenery, food, action, people, wildlife, etc.)
- **Custom** — type anything (e.g. "bird singing in a tree")

### Search
- Natural language search across all uploaded videos (visual + audio)
- Relevance scoring via Twelve Labs embeddings

### Player
- Built-in player with AI chat about video content
- One-click summary generation (title, topics, hashtags)

## Requirements

- **Python** >= 3.8
- **ffmpeg** / **ffprobe**
- [Twelve Labs API key](https://dashboard.twelvelabs.io/)
- **DaVinci Resolve Studio** (optional, needs to be running for project creation — the free version does not include the scripting API)

## Install

```bash
git clone https://github.com/hyl317/Siftly.git
cd Siftly
conda create -n siftly python=3.11
conda activate siftly
pip install -r requirements.txt
```

## Setup

```bash
cp .env.example .env
```

Put your Twelve Labs API key in `.env`:

```
TWELVE_LABS_API_KEY=your_key_here
```

First launch will ask you to pick or create an index.

## Run

```bash
python run.py
```

**Workflow:**

1. **Upload** — pick a folder, check the files you want, upload
2. **Gallery** — browse uploaded videos, click to chat with AI about them
3. **Search** — type what you're looking for
4. **Highlights** — auto-detect or search by category
5. **Export** — select clips, generate a Resolve project or OTIO file

## Tech Stack

- **GUI**: PySide6 (Qt6)
- **AI**: Twelve Labs API (Marengo 3.0 + Pegasus 1.2)
- **Video**: ffmpeg/ffprobe, OpenTimelineIO
- **NLE**: DaVinci Resolve Scripting API

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal and noncommercial use. Commercial licensing available on request.

---

<a id="chinese"></a>

# Siftly

桌面工具，用 [Twelve Labs](https://www.twelvelabs.io/) 的视频理解 API 从素材里挑片段，然后直接生成达芬奇项目，打开就能剪。

## 功能

### 达芬奇集成
- 选好片段后一键生成 DaVinci Resolve 项目（帧率、分辨率、工作目录都能配）
- 源素材自动导入媒体池，时间线自动排好
- 也能导出 OTIO 文件单独用

### 上传
- **支持 LOG 素材** — 自动识别相机的 LOG 格式（S-Log3、C-Log2、V-Log 等），上传前挂 LUT 转 Rec.709，搜索效果更好
- 拖文件夹或拖文件都行
- 超过 720p 自动转码，超过 1.8 GB 自动拆分
- 多文件并行上传

### 找片段
三种方式：
- **自动** — 丢进去让 AI 自己挑，会返回标题、分类、置信度
- **按分类** — 风景、美食、运动、人物、野生动物之类的预设标签一键搜
- **自定义** — 随便打字搜，比如"鸟在树上唱歌"

### 搜索
- 用自然语言搜所有已上传的视频，画面和声音都能搜到
- 用 Twelve Labs embedding 算相似度打分

### 播放器
- 内置播放器，可以跟 AI 聊视频内容
- 一键生成摘要（标题、话题、标签）

## 需要什么

- **Python** >= 3.8
- **ffmpeg** / **ffprobe**
- [Twelve Labs API key](https://dashboard.twelvelabs.io/)
- **DaVinci Resolve Studio**（可选，要用达芬奇集成的话需要开着——免费版不支持脚本 API）

## 装起来

```bash
git clone https://github.com/hyl317/Siftly.git
cd Siftly
conda create -n siftly python=3.11
conda activate siftly
pip install -r requirements.txt
```

## 配置

```bash
cp .env.example .env
```

把 Twelve Labs API key 填进 `.env`：

```
TWELVE_LABS_API_KEY=your_key_here
```

第一次打开会弹设置窗口，选一个 index 就行。

## 跑起来

```bash
python run.py
```

**大致流程：**

1. **上传** — 选文件夹，勾上要的视频，上传
2. **素材库** — 看缩略图，点进去可以跟 AI 聊
3. **搜索** — 打字搜片段
4. **找片段** — 让 AI 自动挑或者按分类找
5. **导出** — 选好片段，生成达芬奇项目或者导出 OTIO

## 技术栈

- **GUI**：PySide6 (Qt6)
- **AI**：Twelve Labs API（Marengo 3.0 + Pegasus 1.2）
- **视频处理**：ffmpeg/ffprobe、OpenTimelineIO
- **NLE**：DaVinci Resolve Scripting API

## 许可证

[PolyForm Noncommercial 1.0.0](LICENSE) — 个人和非商业用途免费。商业用途请联系作者。
