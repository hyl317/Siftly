[English](#english) | [中文](#chinese)

---

<a id="english"></a>

# Siftly

A desktop app for AI-powered video highlight discovery and DaVinci Resolve integration, built on the [Twelve Labs](https://www.twelvelabs.io/) video understanding platform.

Siftly lets you upload videos, search them with natural language, auto-detect highlights, and export curated timelines directly into DaVinci Resolve — no manual clip relinking required.

## Features

### Upload & Preprocessing
- Browse folders or drag-and-drop video files
- Auto-transcodes videos >720p for faster upload
- Splits large files (>1.8 GB) automatically
- Parallel uploads with progress tracking and duplicate detection
- Shows target index name per upload

### Gallery
- Thumbnail grid of all indexed videos with duration badges
- Right-click to reveal in Finder or delete from index
- Auto-generated thumbnails via ffmpeg
- Missing file detection (warns if local file moved/deleted)

### Search
- Natural language search across all indexed videos (visual + audio)
- Relevance scoring via cosine similarity of Twelve Labs embeddings
- Color-coded results (green/orange/red) with threshold filtering
- Click any result to jump to that clip in the built-in player

### Highlights
Three discovery modes:
- **Auto-detect** — AI analyzes each video and returns the most interesting moments with titles, categories, and confidence scores
- **Categories** — One-click search by preset categories (scenery, food, action, people, wildlife, funny, emotional, music, travel)
- **Custom Search** — Free-form text queries (e.g. "dog playing in water")

Selection tools:
- Select all, or filter by score threshold (Score >= N)
- Normalized scoring — best match is always 100%

### DaVinci Resolve Integration
- One-click project creation from selected highlights
- Configure frame rate, resolution (1080p / 4K / 8K / custom), and working folders
- Auto-imports source media and builds timeline via Resolve's scripting API
- Reads current Resolve project defaults for working folder paths
- Also supports standalone OTIO file export

### Video Player
- Built-in playback with clip range markers on the seek slider
- Volume control with mute toggle
- Chat with AI about video content (streaming responses)
- One-click summary and gist generation (title, topics, hashtags)

## Prerequisites

- **Python** >= 3.8
- **ffmpeg** and **ffprobe** installed and on PATH
- A [Twelve Labs API key](https://dashboard.twelvelabs.io/)
- **DaVinci Resolve** (optional, for direct project creation — must be running)

## Installation

```bash
git clone https://github.com/hyl317/Siftly.git
cd Siftly

# Create a virtual environment (conda or venv)
conda create -n siftly python=3.11
conda activate siftly

# Install dependencies
pip install -r requirements.txt
```

## Setup

```bash
cp .env.example .env
```

Edit `.env` and add your Twelve Labs API key:

```
TWELVE_LABS_API_KEY=your_key_here
```

The index ID will be set automatically through the Settings dialog on first launch.

## Usage

```bash
python run.py
```

On first launch, the Settings dialog will prompt for your API key and let you select or create an index.

**Typical workflow:**

1. **Upload** — Select a folder of videos, check the ones you want, and upload
2. **Gallery** — Browse uploaded videos, click to view details and chat with AI
3. **Search** — Find specific moments across all videos with natural language
4. **Highlights** — Discover the best clips automatically or by category
5. **Export** — Select highlights and create a DaVinci Resolve project, or export as OTIO

## Tech Stack

- **GUI**: PySide6 (Qt6)
- **AI**: Twelve Labs API (Marengo 3.0 + Pegasus 1.2)
- **Video**: ffmpeg/ffprobe, OpenTimelineIO
- **NLE**: DaVinci Resolve Scripting API
- **Architecture**: Multi-threaded workers (QThread) for non-blocking UI

## Project Structure

```
Siftly/
├── run.py                  # Entry point
├── requirements.txt
├── .env.example
├── app/
│   ├── main_window.py      # Main window, navigation, index management
│   ├── config.py           # Settings, constants, env loading
│   ├── video_map.py        # Persistent video_id <-> local path mapping
│   ├── style.qss           # Dark theme stylesheet
│   ├── models/
│   │   └── data.py         # Data classes (LocalVideo, IndexedVideo, etc.)
│   ├── views/
│   │   ├── folder_browser.py    # File selection + drag-and-drop
│   │   ├── upload_panel.py      # Upload queue with progress cards
│   │   ├── gallery_view.py      # Video thumbnail grid
│   │   ├── video_detail.py      # Player + chat + summary tabs
│   │   ├── search_view.py       # Text search with results tree
│   │   ├── highlights_view.py   # Highlight discovery + export
│   │   ├── davinci_dialog.py    # DaVinci project creation dialog
│   │   ├── settings_dialog.py   # API key + index configuration
│   │   └── chat_widget.py       # Streaming AI chat
│   ├── services/
│   │   ├── api_client.py        # Twelve Labs client singleton
│   │   ├── upload_worker.py     # Prep + upload workers
│   │   ├── search_worker.py     # Search with embedding scoring
│   │   ├── highlights_worker.py # Auto-detect + search highlights
│   │   ├── analysis_worker.py   # Summary/gist/chat workers
│   │   ├── otio_export.py       # OTIO timeline generation
│   │   └── davinci_resolve.py   # Resolve scripting API wrapper
│   ├── widgets/
│   │   ├── highlight_card.py    # Highlight result card
│   │   ├── progress_card.py     # Upload progress card
│   │   └── video_thumbnail.py   # Gallery thumbnail widget
│   └── utils/
│       ├── video_prep.py        # Transcode, split, validate
│       ├── thumbnails.py        # Thumbnail extraction + ffprobe
│       └── file_scanner.py      # Local folder scanning
```

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal and noncommercial use. For commercial licensing, please contact the author.

---

<a id="chinese"></a>

# Siftly

一款基于 [Twelve Labs](https://www.twelvelabs.io/) 视频理解平台的桌面应用，用于 AI 驱动的视频精彩片段发现与 DaVinci Resolve 集成。

Siftly 支持上传视频、自然语言搜索、自动发现精彩片段，并将精选时间线直接导出到 DaVinci Resolve——无需手动重新链接素材。

## 功能

### 上传与预处理
- 浏览文件夹或拖放视频文件
- 自动将 >720p 的视频转码以加速上传
- 自动拆分大文件（>1.8 GB）
- 并行上传，带进度追踪和重复检测
- 每个上传任务显示目标索引名称

### 素材库
- 所有已索引视频的缩略图网格，显示时长
- 右键菜单：在 Finder 中显示 / 从索引删除
- 通过 ffmpeg 自动生成缩略图
- 本地文件缺失检测（文件被移动或删除时发出警告）

### 搜索
- 跨所有已索引视频的自然语言搜索（视觉 + 音频）
- 基于 Twelve Labs 嵌入向量余弦相似度的相关性评分
- 颜色标注的搜索结果（绿/橙/红），支持阈值筛选
- 点击任意结果即可在内置播放器中跳转到对应片段

### 精彩片段
三种发现模式：
- **自动检测** — AI 分析每个视频，返回最有趣的片段，包含标题、分类和置信度评分
- **分类搜索** — 按预设分类一键搜索（风景、美食、动作、人物、野生动物、搞笑、情感、音乐、旅行）
- **自定义搜索** — 自由文本查询（如"狗在水里玩耍"）

选择工具：
- 全选，或按分数阈值筛选（分数 >= N）
- 归一化评分——最佳匹配始终为 100%

### DaVinci Resolve 集成
- 从选定的精彩片段一键创建项目
- 配置帧率、分辨率（1080p / 4K / 8K / 自定义）和工作文件夹
- 通过 Resolve 脚本 API 自动导入源媒体并构建时间线
- 自动读取当前 Resolve 项目的工作文件夹默认路径
- 同时支持独立的 OTIO 文件导出

### 视频播放器
- 内置播放功能，搜索滑块上带有片段范围标记
- 音量控制与静音切换
- 与 AI 就视频内容进行对话（流式响应）
- 一键生成摘要和简介（标题、主题、标签）

## 前置要求

- **Python** >= 3.8
- **ffmpeg** 和 **ffprobe** 已安装并在 PATH 中
- [Twelve Labs API 密钥](https://dashboard.twelvelabs.io/)
- **DaVinci Resolve**（可选，用于直接创建项目——需要在运行状态）

## 安装

```bash
git clone https://github.com/hyl317/Siftly.git
cd Siftly

# 创建虚拟环境（conda 或 venv）
conda create -n siftly python=3.11
conda activate siftly

# 安装依赖
pip install -r requirements.txt
```

## 配置

```bash
cp .env.example .env
```

编辑 `.env` 文件，添加你的 Twelve Labs API 密钥：

```
TWELVE_LABS_API_KEY=your_key_here
```

索引 ID 将在首次启动时通过设置对话框自动设置。

## 使用

```bash
python run.py
```

首次启动时，设置对话框会提示输入 API 密钥并选择或创建索引。

**典型工作流程：**

1. **上传** — 选择视频文件夹，勾选需要的文件，上传
2. **素材库** — 浏览已上传的视频，点击查看详情并与 AI 对话
3. **搜索** — 使用自然语言在所有视频中查找特定片段
4. **精彩片段** — 自动发现最佳片段或按分类搜索
5. **导出** — 选择精彩片段，创建 DaVinci Resolve 项目或导出为 OTIO 文件

## 技术栈

- **GUI**：PySide6 (Qt6)
- **AI**：Twelve Labs API（Marengo 3.0 + Pegasus 1.2）
- **视频**：ffmpeg/ffprobe、OpenTimelineIO
- **非线性编辑**：DaVinci Resolve Scripting API
- **架构**：多线程工作器（QThread），确保 UI 不阻塞

## 项目结构

```
Siftly/
├── run.py                  # 入口文件
├── requirements.txt
├── .env.example
├── app/
│   ├── main_window.py      # 主窗口、导航、索引管理
│   ├── config.py           # 设置、常量、环境变量加载
│   ├── video_map.py        # 持久化 video_id <-> 本地路径映射
│   ├── style.qss           # 深色主题样式表
│   ├── models/
│   │   └── data.py         # 数据类（LocalVideo、IndexedVideo 等）
│   ├── views/
│   │   ├── folder_browser.py    # 文件选择 + 拖放
│   │   ├── upload_panel.py      # 上传队列及进度卡片
│   │   ├── gallery_view.py      # 视频缩略图网格
│   │   ├── video_detail.py      # 播放器 + 对话 + 摘要标签页
│   │   ├── search_view.py       # 文本搜索与结果树
│   │   ├── highlights_view.py   # 精彩片段发现 + 导出
│   │   ├── davinci_dialog.py    # DaVinci 项目创建对话框
│   │   ├── settings_dialog.py   # API 密钥 + 索引配置
│   │   └── chat_widget.py       # 流式 AI 对话
│   ├── services/
│   │   ├── api_client.py        # Twelve Labs 客户端单例
│   │   ├── upload_worker.py     # 预处理 + 上传工作器
│   │   ├── search_worker.py     # 搜索及嵌入向量评分
│   │   ├── highlights_worker.py # 自动检测 + 搜索精彩片段
│   │   ├── analysis_worker.py   # 摘要/简介/对话工作器
│   │   ├── otio_export.py       # OTIO 时间线生成
│   │   └── davinci_resolve.py   # Resolve 脚本 API 封装
│   ├── widgets/
│   │   ├── highlight_card.py    # 精彩片段结果卡片
│   │   ├── progress_card.py     # 上传进度卡片
│   │   └── video_thumbnail.py   # 素材库缩略图组件
│   └── utils/
│       ├── video_prep.py        # 转码、拆分、验证
│       ├── thumbnails.py        # 缩略图提取 + ffprobe
│       └── file_scanner.py      # 本地文件夹扫描
```

## 许可证

MIT
