# Knowledge Graph Builder - 开发进度记录

> 最后更新: 2026-06-06
> 当前版本: v1.5.0

---

## 1. 核心功能完成情况 (Core Features)

### 1.1 数据处理管线 (Pipeline)
- [x] **分块处理**: 支持 Fixed、Sliding Window 策略，新增 CSV 按行分块 (`src/chunker.py`)
- [x] **信息抽取**: 支持 LMStudio / Ollama 本地模型 (`src/extractor.py`)
- [x] **实体对齐**: Levenshtein + LLM 混合消歧 (`src/resolver.py`)
- [x] **图构建**: NetworkX 有向图构建 (`src/graph_builder.py`)
- [x] **推理分析**: PageRank, 社区发现, 传递推理 (`src/inferencer.py`)
- [x] **维基编译**: 生成 Markdown Wiki 供人类阅读，支持溯源 Frontmatter 和按来源分组索引 (`src/wiki_builder.py`)
- [x] **自愈合 Lint**: 检测孤儿节点、矛盾关系 (`src/wiki_linter.py`)

### 1.2 新增功能 (v1.2.0)
- [x] **CSV 文档支持**: 自动识别 `.csv` 文件，按行分块并转为文本描述 (`src/chunker.py`, `scripts/run_extraction.py`)
- [x] **溯源功能**: 实体页面添加 `source:` Frontmatter，索引按来源文档分组 (`src/wiki_builder.py`)

### 1.3 新增功能 (v1.3.0)
- [x] **增量更新**: 基于 SHA256 快照，仅处理新增/修改文档 (`src/incremental_tracker.py`)
- [x] **双向同步**: Wiki Markdown 编辑反馈回图谱 (`src/wiki_sync.py`, `scripts/sync_wiki_to_graph.py`)

### 1.5 新增功能 (v1.5.0)
- [x] **Office 文档支持**: 自动识别 `.docx`/`.xlsx`/`.pptx`，分别按段落、行、幻灯片分块提取文本 (`src/chunker.py`, `scripts/run_extraction.py`)
- [x] **多模态支持**: 支持 `.png`/`.jpg`/`.webp`/`.bmp`/`.gif` 图片文件，通过视觉模型 (Qwen-VL) 自动解析截图和架构图中的实体与关系 (`src/chunker.py`, `src/extractor.py`, `config/llm_config.yaml`)

### 1.4 插件与扩展
- [x] **飞书同步**: 自动拉取飞书知识库并转 Markdown (`scripts/sync_feishu.py`)
- [x] **独立推理**: 支持对已有图谱运行分析脚本 (`scripts/run_inference.py`)
- [x] **可视化脚本**: Bash 脚本一键打开图谱 (`scripts/visualize.sh`)
- [x] **Jupyter 支持**: 探索性分析 Notebook (`notebooks/explore_graph.ipynb`)
- [x] **递归目录支持**: 自动扫描 `data/raw/` 下所有子目录

---

## 2. 配置与环境

- **LLM 后端**: LMStudio / DashScope (OpenAI 兼容)
- **文本模型**: `qwen3.7-max`
- **视觉模型**: `qwen-vl-max` (通过 `vision_model` 配置)
- **API 地址**: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **主要依赖**: `networkx`, `pyyaml`, `requests`, `python-Levenshtein`, `lxml`, `python-docx`, `openpyxl`, `python-pptx`

---

## 3. 已知问题与修复记录 (Known Issues & Fixes)

| 问题描述 | 状态 | 解决方案/备注 |
|------|------|------|
| **GraphML 导出报错** | 已修复 | NetworkX 不支持 set/list 属性。已修改代码在导出前转为字符串。 |
| **Wiki 生成卡顿/无效实体** | 已优化 | 增加了垃圾实体过滤 (`_is_junk_entity`)，自动跳过 "404 Not Found" 等无效实体。 |
| **飞书图片解析** | 局限 | 当前 gemma-4-e4b-it 为纯文本模型，无法理解图片内容。仅下载图片并引用。 |
| **401 鉴权错误** | 偶发 | LMStudio API Key 配置问题，需确保 `config/llm_config.yaml` 中的 Key 有效。 |

---

## 4. 待办事项 (Next Steps)

### 4.1 高优先级
- [x] **增量更新**: 已实现。默认仅处理新增/修改文档，复用已有三元组。支持 `--full` 强制全量重建。详见 `src/incremental_tracker.py`。
- [x] **双向同步**: 已实现 Wiki → Graph 反馈。用户在 Obsidian 中编辑实体页面（增删关系、修改置信度/类型），同步后自动更新图谱。详见 `src/wiki_sync.py` 和 `scripts/sync_wiki_to_graph.py`。
- [x] **多模态支持**: 引入视觉模型 (如 Qwen-VL) 以解析文档截图和架构图。详见 `src/chunker.py` (图片分块), `src/extractor.py` (视觉 LLM 调用), `config/llm_config.yaml` (`vision_model` 配置)。

### 4.2 优化项
- [ ] **性能提升**: Wiki 编译阶段是串行的，可改为并发请求 LLM。
- [x] **Web UI**: 基于 Flask + D3.js 的轻量级 Web 界面，支持浏览、搜索、编辑图谱和双向同步。详见 `scripts/serve_webui.py`。

---

## 5. 重要文件索引

- `DESIGN.md`: 详细设计文档与参考文献
- `scripts/run_extraction.py`: 主流程入口
- `scripts/sync_feishu.py`: 飞书同步脚本
- `config/llm_config.yaml`: LLM 配置
- `config/feishu_config.yaml`: 飞书配置
