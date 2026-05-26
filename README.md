# LLM Knowledge Graph Builder

> 项目版本: v1.4.1 | 最后更新: 2026-05-26

基于大语言模型的知识图谱构建工具。从文档中自动抽取实体和关系，构建结构化知识图谱，并自动编译为可读的 Markdown Wiki。支持**增量更新**和**双向同步**（Obsidian ↔ Graph）。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 LLM

编辑 `config/llm_config.yaml`，设置你的 LLM 连接信息：

```yaml
llm:
  provider: "lmstudio"
  model: "gemma-4-e4b-it"
  base_url: "http://192.168.3.70:1234/v1"
```

### 3. 运行

```bash
# 增量模式 (默认，首次自动全量)
python scripts/run_extraction.py

# 强制全量重建
python scripts/run_extraction.py --full

# 包含 Wiki 双向同步
python scripts/run_extraction.py --sync-wiki

# 仅同步 Wiki 编辑
python scripts/run_extraction.py --wiki-only
```

### 4. 查看结果

**机器可读图谱** 位于 `data/graphs/`：
- **GraphML** (.graphml) → Gephi / yEd / Neo4j
- **GEXF** (.gexf) → Gephi
- **JSON** (.json) → 自定义可视化

**人类可读 Wiki** 位于 `data/wiki/`：
- **index.md** → 知识库目录，支持 Obsidian/Logseq WikiLinks
- **entities/*.md** → 每个实体的独立页面，含关系溯源

## 项目结构

```
knowledge-graph-builder/
├── config/
│   ├── llm_config.yaml          # LLM 连接配置
│   ├── schema.json              # 实体/关系类型定义
│   └── chunking_config.yaml     # 分块参数
├── src/
│   ├── chunker.py               # 文档分块
│   ├── extractor.py             # LLM 实体关系抽取
│   ├── graph_builder.py         # NetworkX 图构建
│   ├── resolver.py              # 实体对齐与消歧
│   ├── inferencer.py            # 图推理分析
│   ├── querier.py               # 图查询接口
│   ├── visualizer.py            # 可视化导出
│   ├── wiki_builder.py          # 维基编译器 (Graph → Markdown)
│   ├── wiki_linter.py           # 自愈合检查器
│   ├── wiki_sync.py             # [NEW] 双向同步 (Wiki → Graph)
│   └── incremental_tracker.py   # [NEW] 增量更新追踪器
├── data/
│   ├── raw/                     # 放入原始文档 (.md / .txt / .csv)
│   ├── chunks/                  # 分块输出
│   ├── triples/                 # 抽取的三元组
│   │   └── incremental_state.json  # 增量状态快照
│   ├── graphs/                  # 最终图谱文件
│   └── wiki/                    # 人类可读知识库 (Markdown)
├── scripts/
│   ├── run_extraction.py        # 主流程入口 (支持增量 + 双向同步)
│   ├── run_inference.py         # 独立推理脚本
│   ├── sync_wiki_to_graph.py    # [NEW] Wiki 同步脚本
│   ├── serve_webui.py           # [NEW] Web UI 服务器
│   ├── run_rag_search.py        # [NEW] 混合搜索 (向量+图谱)
│   ├── visualize.sh             # 可视化启动脚本
│   └── sync_feishu.py           # 飞书知识库同步插件
├── notebooks/
│   └── explore_graph.ipynb      # Jupyter 探索分析
├── tests/
│   └── test_extractor.py        # 单元测试
├── requirements.txt
└── README.md
```

## 支持的 LLM

| Provider | 配置示例 |
|----------|---------|
| LMStudio (本地) | `base_url: http://192.168.3.70:1234/v1` |
| Ollama (本地) | `base_url: http://localhost:11434` |
| OpenAI 兼容 API | `base_url: https://api.openai.com` |
| 任意 OpenAI 兼容端点 | 修改 base_url 和 model 即可 |

## Markdown Wiki (Karpathy 风格)

本项目在图谱构建后，会自动将知识编译为 **人类可读的 Markdown Wiki**：

- **每个实体一个页面**: 包含溯源 Frontmatter（`source:` 字段）、摘要、关系列表
- **按来源分组索引**: `index.md` 按原始文档来源分组，方便追溯出处
- **WikiLinks 导航**: `[[实体名]]` 格式，兼容 Obsidian / Logseq
- **自愈合 Lint**: 自动检测孤儿实体、矛盾关系、低置信度边
- **零基础设施**: 纯文本文件，可用 Git 版本控制

### 实体页面示例
```markdown
---
title: 大模型
source: sample.md
---

# 大模型
**类型**: CONCEPT
> ...
```

### 索引结构
```markdown
## 来源: sample.md
- [[大模型|大模型]]
- ...

## 来源: rk3588-npu-guide.md
- [[RK3588 NPU|RK3588 NPU]]
- ...
```

## 增量更新

默认启用增量模式，仅处理新增或修改的文档：

```bash
# 首次运行 — 全量抽取，建立文件快照
python scripts/run_extraction.py

# 后续运行 — 仅处理变更文件，复用已有三元组
python scripts/run_extraction.py

# 强制全量重建 (忽略快照)
python scripts/run_extraction.py --full
```

**工作原理：**
1. 每个文件计算 SHA256 哈希并记录
2. 运行时对比哈希，识别新增/修改/删除/未变四类状态
3. 仅对变更文件调用 LLM，未变文件直接复用
4. 状态保存在 `data/triples/incremental_state.json`

## Web UI 浏览与编辑

启动轻量级 Web 界面浏览和编辑知识图谱：

```bash
# 启动 Web UI (默认 http://127.0.0.1:5050)
python scripts/serve_webui.py

# 允许局域网访问
python scripts/serve_webui.py --host 0.0.0.0 --port 5050
```

### 功能

- **📊 概览**: 图谱统计（节点数、边数、密度、平均度数）
- **📄 详情/编辑**: 
  - 查看实体的出向/入向关系及置信度
  - 添加/删除关系
  - 修改实体类型和置信度
  - 同步 Wiki 编辑（双向同步）
  - 删除实体
- **🔗 图谱**: 基于 D3.js 的力导向图可视化，支持拖拽和缩放
- **🔎 混合搜索**: 向量搜索文档分块 + 图谱实体匹配
- **🔍 搜索**: 按名称搜索实体，按类型过滤

## WWiki 双向同步 (Wiki ↔ Graph)

在 Obsidian 中编辑 Wiki 实体页面后，可将变更同步回知识图谱：

### 支持的操作

| Wiki 编辑行为 | 图谱变更 |
|-------------|---------|
| 添加 `- **关系名** → [[目标实体]] (置信度: 0.9)` | 新增出向边 |
| 添加 `- **关系名** ← [[来源实体]] (置信度: 0.8)` | 新增入向边 |
| 删除已有关系行 | 删除对应边 |
| 修改置信度数值 | 更新边置信度 |
| 修改 `**类型**` 字段 | 更新节点类型 |

### 使用方式

```bash
# 方式 1: 在主流程中同时同步
python scripts/run_extraction.py --sync-wiki

# 方式 2: 仅同步 Wiki（不跑抽取管线）
python scripts/run_extraction.py --wiki-only

# 方式 3: 独立运行同步脚本
python scripts/sync_wiki_to_graph.py

# 方式 4: 仅同步指定实体
python scripts/sync_wiki_to_graph.py --entity "RK3588"

# 预览变更但不实际修改图谱
python scripts/sync_wiki_to_graph.py --dry-run
```

## CSV 文档支持

本项目支持直接处理 CSV 格式文档，自动将其转换为知识图谱：

- **自动识别**: 将 `.csv` 文件放入 `data/raw/` 目录即可自动处理
- **按行分块**: CSV 每行转为一个文本块，格式为 `行 N: 列名=值, ...`
- **完整流程**: CSV → 分块 → LLM 抽取三元组 → 图谱构建 → Wiki 生成

### CSV 处理示例
```csv
人物,公司,职位,地点
张三,腾讯,工程师,深圳
李四,阿里巴巴,产品经理,杭州
```

处理后的 chunk 格式：
```
行 1: 人物=张三, 公司=腾讯, 职位=工程师, 地点=深圳
```

### 使用方法
```bash
# 1. 将 CSV 文件放入 raw 目录
cp your_data.csv data/raw/

# 2. 运行完整流程
python scripts/run_extraction.py
```

## 飞书知识库同步

本项目内置了飞书同步插件，支持自动将飞书知识库转为 Markdown 并下载图片：

1. **获取凭证**：在飞书开放平台创建应用，获取 `App ID` 和 `App Secret`。
2. **配置权限**：添加 `wiki:wiki:readonly`, `docx:document:readonly`, `drive:drive:readonly`。
3. **填写配置**：编辑 `config/feishu_config.yaml`，填入 ID 和 `space_id`。
4. **执行同步**：运行 `python scripts/sync_feishu.py`，完成后直接运行主流程即可。

## 自定义 Schema

编辑 `config/schema.json` 添加或删除实体/关系类型：

```json
{
  "entities": [
    {"type": "HARDWARE", "label": "硬件平台", "description": "芯片、开发板等"},
    {"type": "MODEL", "label": "模型", "description": "AI/ML 模型"}
  ],
  "relations": [
    {"type": "RUNS_ON", "label": "运行于", "valid_subject": ["MODEL"], "valid_object": ["HARDWARE"]}
  ]
}
```

## RAG 混合搜索

向量检索 + 图谱遍历的混合搜索，解决文档过长时 LLM context window 不足的问题。

### 抽取时启用 RAG 增强

在抽取阶段，为每个 chunk 查找 top-3 语义相似的 chunk 作为补充上下文：

```bash
python scripts/run_extraction.py --rag
```

### 独立混合搜索

```bash
# 交互式搜索
python scripts/run_rag_search.py -i

# 一次查询（向量 + 图谱）
python scripts/run_rag_search.py "NPU RK3588" -k 5 --graph

# 查找图谱路径
python scripts/run_rag_search.py "llama.cpp → RK3588" --graph

# 重建向量索引
python scripts/run_rag_search.py --rebuild
```

### 后端方案

| 方案 | 依赖 | 精度 |
|------|------|------|
| TF-IDF (默认) | numpy, scipy | 中等 |
| API Embedding | LLM provider embedding API | 高 |

## 独立推理

```bash
# 完整分析
python scripts/run_inference.py --insights

# 查找两实体间路径
python scripts/run_inference.py --find-paths "Elon Musk" "Tesla"

# 仅计算中心性
python scripts/run_inference.py --centrality
```

## 单元测试

```bash
python -m pytest tests/ -v
```
