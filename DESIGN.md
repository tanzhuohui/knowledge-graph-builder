# LLM Knowledge Graph Builder — 项目设计文档

> 融合知识图谱推理与 Karpathy LLM Wiki 理念的混合型知识库系统

---

## 一、设计思路

### 1.1 核心理念

本项目解决的核心问题是：**如何从非结构化文档中提取、组织并持久化知识？**

传统方案有两条路线：
- **RAG (检索增强生成)**：将文档分块 → 向量化 → 存入向量数据库 → 查询时检索相似片段
- **知识图谱 (KG)**：从文档中抽取实体和关系 → 构建图结构 → 支持图遍历与推理

每条路线都有其局限性：
- RAG 的向量检索基于"语义相似度"，容易遗漏精确的结构化关系，且每次查询都要重新推理
- 知识图谱是"黑盒"数据格式（JSON/GraphML），人类难以直接阅读和审计

### 1.2 Karpathy 的启示

2026 年 4 月，Andrej Karpathy 提出了 **"LLM Wiki"** 概念：
- 不用向量数据库，而是让 LLM 将原始文档**编译**为结构化的 Markdown Wiki
- 知识以人类可读的 `.md` 文件存储，支持 Git 版本控制
- LLM 定期运行 "Lint" 检查，自动发现矛盾并修复（自愈合）
- 核心隐喻：**知识应像代码一样被"编译"，而不是像数据一样被"检索"**

### 1.3 融合方案

本项目将 **知识图谱的推理能力** 与 **Karpathy Wiki 的可读性** 结合，并支持**增量更新**和**双向同步**：

```
原始文档 (含飞书/本地文件)
    │
    ▼
[信息抽取] LLM 从文本中提取三元组 (实体→关系→实体)
    │
    ▼
[图谱构建] NetworkX 构建有向图，支持图论分析
    │
    ▼
[推理增强] PageRank、社区发现、传递推理
    │
    ▼
[Wiki 编译] 将图谱"反编译"为 Markdown Wiki (Karpathy 风格)
    │
    ▼
[自愈合 Lint] 检测矛盾、孤儿节点、低置信度边并自动修复
    │
    ▼
[双向同步] Wiki 编辑 → 解析变更 → 反馈回图谱 (新增/删除关系、修改置信度)
    │
    ▼
输出: 机器可读图谱 + 人类可读 Wiki (Obsidian 双向同步)
```

**增量更新机制：**
```
首次运行 ──▶ 全量抽取 ──▶ 建立文件快照 (SHA256)
                                   │
后续运行 ──▶ 对比快照 ──▶ 仅处理新增/修改/删除的文件 ──▶ 合并三元组
```

**为什么两者都要？**
| 维度 | 知识图谱 | Markdown Wiki |
|------|---------|--------------|
| **用途** | 算法分析、图论计算 | 人类阅读、知识管理 |
| **查询** | Cypher、图遍历 | Obsidian WikiLinks、全文搜索 |
| **分析** | PageRank、中心度、社区发现 | 不适用 |
| **可读性** | 低 (JSON/GraphML) | 高 (纯文本 Markdown) |
| **维护** | 增量更新 (仅处理变更) | 双向同步 (Wiki ↔ Graph) |

---

## 二、项目实现

### 2.1 项目结构

```
knowledge-graph-builder/
├── config/
│   ├── llm_config.yaml          # LLM 连接配置 (provider, model, base_url)
│   ├── schema.json              # 实体/关系类型定义 (ontology)
│   ├── chunking_config.yaml     # 文档分块参数
│   └── feishu_config.yaml       # 飞书插件凭证配置
│
├── src/
│   ├── chunker.py               # 文档分块 (fixed / sliding_window / csv)
│   ├── extractor.py             # LLM 实体关系抽取 (lmstudio / ollama)
│   ├── graph_builder.py         # NetworkX 有向图构建
│   ├── resolver.py              # 实体对齐与消歧 (Levenshtein + LLM)
│   ├── inferencer.py            # 图推理 (PageRank、社区、传递推理)
│   ├── querier.py               # 图查询接口 (路径查找、Cypher 导出)
│   ├── visualizer.py            # 可视化导出 (GraphML/GEXF/JSON)
│   ├── wiki_builder.py          # 维基编译器 (Graph → Markdown)
│   ├── wiki_linter.py           # 自愈合检查器
│   ├── wiki_sync.py             # [NEW] 双向同步 (Wiki → Graph)
│   └── incremental_tracker.py   # [NEW] 增量更新追踪器
│
├── data/
│   ├── raw/                     # 原始文档 (.md / .txt / .csv / feishu_images)
│   ├── chunks/                  # 分块后的文本
│   ├── triples/                 # 抽取的三元组 (JSON)
│   │   └── incremental_state.json  # [NEW] 增量状态快照
│   ├── graphs/                  # 导出的图文件
│   └── wiki/                    # 人类可读知识库 (Markdown)
│
├── scripts/
│   ├── run_extraction.py        # 主流程入口 (支持增量 + 双向同步)
│   ├── run_inference.py         # 独立推理脚本
│   ├── sync_wiki_to_graph.py    # [NEW] Wiki 同步脚本 (独立运行)
│   ├── serve_webui.py           # [NEW] Web UI 服务器 (Flask + D3.js)
│   ├── visualize.sh             # 可视化启动脚本
│   └── sync_feishu.py           # 飞书知识库同步插件
│
├── notebooks/
│   └── explore_graph.ipynb      # Jupyter 探索分析
├── tests/
│   └── test_extractor.py        # 单元测试
├── requirements.txt
└── README.md
```

### 2.2 核心模块

#### 2.2.1 文档分块 (`chunker.py`)

- **固定长度分块**：按段落聚合，控制 chunk_size (默认 1500 词)
- **滑动窗口分块**：保留 overlap (默认 250 词)，避免切断语义
- **CSV 分块**：按行分块，每行转为 `行 N: 列名=值, ...` 格式
- 输出格式：`{"id", "source", "index", "text", "word_count"}`
- 支持文件类型：`.md`, `.txt`, `.csv`

#### 2.2.2 实体关系抽取 (`extractor.py`)

- 支持 **LMStudio** 和 **Ollama** 两种本地 LLM provider
- 使用结构化 Prompt 引导 LLM 输出 JSON 数组
- 输出格式：`{"subject", "subject_type", "relation", "object", "object_type", "confidence", "source_text"}`
- 内置重试机制 (exponential backoff) 和置信度过滤

#### 2.2.3 实体对齐 (`resolver.py`)

- **第一层**：Levenshtein 相似度 (阈值 0.85)，合并拼写变体
- **第二层**：LLM 判断，处理语义等价但字面不同的实体
- 维护 `entity_map` 映射别名到规范名称

#### 2.2.4 图构建 (`graph_builder.py`)

- 使用 `networkx.DiGraph` 构建有向图
- 边属性：`relation`, `confidence`, `source_text`, `source_chunk`
- 节点属性：`types` (集合，支持多类型)
- 支持 GraphML、GEXF 和 JSON 导出

#### 2.2.5 推理分析 (`inferencer.py`)

- **路径发现**：`find_paths(source, target, max_depth)`
- **传递推理**：A→B→C ⇒ 推断 A→C (confidence=0.5)
- **中心性计算**：Degree, PageRank, Betweenness
- **社区发现**：Girvan-Newman 模块度最大化

#### 2.2.6 维基编译器 (`wiki_builder.py`)

- 遍历图节点，为每个实体生成独立的 Markdown 页面
- 页面结构：
  ```markdown
  ---
  title: 实体名称
  source: 主要来源文档
  sources:
    - 其他来源1
    - 其他来源2
  ---

  # 实体名称

  > [LLM 生成的摘要]

  ## 出向关系
  - **WORKS_FOR** → [[公司名]] (置信度: 0.95)

  ## 入向关系
  - **CREATED** ← [[创始人]] (置信度: 0.90)

  ## 统计
  - 出向连接数 / 入向连接数 / 总连接数
  ```
- **溯源功能**：通过 `chunk_to_source` 映射自动获取实体来源文档，写入 Frontmatter
- 生成 `index.md` 作为知识库目录，**按来源文档分组**（而非实体类型），方便追溯原始出处
- 使用 `[[WikiLinks]]` 格式，兼容 Obsidian / Logseq

#### 2.2.7 自愈合 Linter (`wiki_linter.py`)

检测并修复四类问题：
1. **孤儿实体**：度数为 0 的孤立节点 (warning)
2. **低置信度边**：confidence < 0.5 的关系 (info)
3. **矛盾关系**：同一实体对存在多种关系类型 (warning，LLM 自动裁决)
4. **缺失摘要**：Wiki 页面内容不完整 (info)

#### 2.2.8 增量更新追踪器 (`incremental_tracker.py`) — [NEW]

基于 SHA256 文件快照的增量处理机制：

**工作原理：**
1. 首次运行时记录每个文件的哈希、对应 chunk IDs、三元组索引
2. 后续运行时对比哈希，识别四类状态：新增、修改、删除、未变
3. 仅对新增/修改文件调用 LLM 抽取，未变文件复用已有数据
4. 修改文件：先删除旧三元组，再重新抽取
5. 删除文件：从全量三元组中清除对应记录
6. 状态保存在 `data/triples/incremental_state.json`

#### 2.2.9 双向同步模块 (`wiki_sync.py`) — [NEW]

从 Wiki Markdown 页面的编辑反馈回知识图谱：

**工作原理：**
1. **解析** — 读取 `data/wiki/entities/*.md` 的 Frontmatter 和关系行（正则匹配 `- **关系** → [[目标]] (置信度: N.NN)`）
2. **对比** — 与图谱中的出向/入向关系逐条对比，检测：
   - 新增关系（用户在 Wiki 中添加的关系行）
   - 删除关系（图谱中有但 Wiki 中不存在的关系）
   - 置信度变更（用户手动修改的置信度值）
   - 实体类型变更
3. **应用** — 将变更写回 NetworkX 图，标记 `wiki_updated=True`，保存为 GraphML/GEXF/JSON

**支持的编辑操作：**
| Wiki 编辑行为 | 图谱变更 |
|-------------|---------|
| 添加 `- **REL** → [[目标]] (置信度: 0.9)` | 新增出向边 |
| 添加 `- **REL** ← [[来源]] (置信度: 0.8)` | 新增入向边 |
| 删除关系行 | 删除对应边 |
| 修改置信度值 | 更新边置信度 |
| 修改 `**类型**` 字段 | 更新节点类型 |

#### 2.2.10 飞书同步插件 (`sync_feishu.py`)

针对企业知识库的自动化同步插件，支持将飞书 (Feishu/Lark) 知识库无缝转为本地 Markdown。

**设计思路：**
1. **API 优先**：通过飞书开放平台 API (`open.feishu.cn`) 获取结构化数据，而非网页抓取，保证稳定性。
2. **递归遍历**：自动从 `root_node` 开始，深度优先遍历知识库节点树。
3. **Markdown 转换**：将飞书的 Block 结构（标题、正文、列表、图片）转换为本项目可识别的 Markdown 格式。
4. **图片处理**：自动调用媒体下载 API 将图片保存至 `data/raw/feishu_images/`，并修正 Markdown 引用路径。

**支持元素：**
- **文本/公式**：完美支持文本和 LaTeX 格式公式。
- **图片**：自动下载并建立本地引用。
- **链接**：提取并保留文档内外部链接。

**注意事项：**
- 当前使用的 `gemma-4-e4b-it` 为纯文本模型，无法解析图片中的视觉信息。
- 如需完全解析图片内容，建议后续升级为多模态模型（如 Qwen-VL）。

### 2.3 主流程

```python
# scripts/run_extraction.py
[1/8] Chunking documents      → 分块处理 (增量模式仅处理变更文件)
[2/8] Extracting triples      → LLM 抽取三元组 (增量模式复用已有)
[3/8] Resolving entities      → 实体对齐消歧
[4/8] Building graph          → 构建 NetworkX 图
[5/8] Running inference       → 图推理分析
[6/8] Exporting visualization → 导出 GraphML/GEXF/JSON
[7/8] Compiling Wiki          → 生成 Markdown 知识库
[8/8] Running lint checks     → 自愈合检查与修复
[Sync] Wiki → Graph sync      → 双向同步 (可选，--sync-wiki)
```

### 2.10 向量检索与 RAG 混合层 (`vector_store.py`, `scripts/run_rag_search.py`) — [NEW]

对超出 LLM context window 的文档引入向量检索作为补充。

**架构：**
1. **向量索引构建**：抽取阶段将文档分块构建 TF-IDF 向量（零外部依赖），或通过 LLM Provider 的 embedding API
2. **RAG 上下文增强**：抽取每个 chunk 时，查询 top-3 语义相似 chunk 加入 LLM prompt，帮助跨文档关联
3. **混合搜索**：`scripts/run_rag_search.py` 支持向量搜索 + 图谱遍历 + 路径发现，可交互式查询

**后端方案：**
| 方案 | 依赖 | 精度 |
|------|------|------|
| TF-IDF (默认) | numpy, scipy | 中等 |
| API Embedding | LLM provider embedding API | 高 |

**使用方式：**
```bash
# 抽取时启用 RAG 增强
python scripts/run_extraction.py --rag

# 混合搜索（交互式）
python scripts/run_rag_search.py -i

# 一次查询
python scripts/run_rag_search.py "NPU RK3588" -k 5 --graph

# 重建向量索引
python scripts/run_rag_search.py --rebuild
```

### 2.11 技术栈更新

| 组件 | 选型 | 说明 |
|------|------|------|
| **LLM** | gemma-4-e4b-it (via LMStudio) | 本地部署，OpenAI 兼容 API |
| **图处理** | NetworkX 3.0+ | 轻量级 Python 图库 |
| **文本处理** | PyYAML, python-Levenshtein | 配置解析与字符串相似度 |
| **可视化** | Gephi, yEd, Obsidian | 图谱与知识库浏览 |
| **增量追踪** | SHA256 快照 | 文件级变更检测 |
| **双向同步** | Markdown 解析 + 图变更应用 | Wiki ↔ Graph 双向更新 |

---

## 三、使用方法

### 3.1 快速开始

#### 安装

```bash
cd knowledge-graph-builder
pip install -r requirements.txt
```

#### 配置 LLM

编辑 `config/llm_config.yaml`：

```yaml
llm:
  provider: "lmstudio"
  model: "gemma-4-e4b-it"
  base_url: "http://192.168.3.70:1234/v1"
  api_key: "your-api-key"
  temperature: 0
  timeout: 120

extraction:
  confidence_threshold: 0.7
  max_retries: 3
  batch_size: 10
```

#### 准备数据

将原始文档放入 `data/raw/` 目录（支持 `.md` 和 `.txt`）：

```bash
cp ~/my-research-paper.md data/raw/
```

#### 运行

```bash
# 增量模式 (默认，首次自动全量)
python scripts/run_extraction.py

# 强制全量重建
python scripts/run_extraction.py --full

# 包含 Wiki 双向同步
python scripts/run_extraction.py --sync-wiki

# 仅同步 Wiki 编辑，跳过文档抽取
python scripts/run_extraction.py --wiki-only
```

### 3.2 查看结果

#### 机器可读图谱

```
data/graphs/
├── knowledge_graph.graphml    → Gephi / yEd / Neo4j
├── knowledge_graph.gexf       → Gephi
├── knowledge_graph.json       → 自定义可视化
└── insights.json              → 分析洞察
```

#### 人类可读 Wiki

```
data/wiki/
├── index.md                   → 知识库目录 (按来源文档分组，Obsidian 打开)
├── wiki_stats.json            → 统计信息
├── lint_report.json           → 自检报告
└── entities/
    ├── Andrej_Karpathy.md     → 实体页面 (含 Frontmatter 溯源信息)
    └── Tesla.md
```

**溯源功能**：
- 每个实体页面顶部包含 YAML Frontmatter，标注来源文档（`source:` 字段）
- `index.md` 按**来源文档**分组（如 `## 来源: sample.md`），方便追溯原始出处
- 在 Obsidian 中可使用 `source:` 属性进行筛选和排序

打开 `data/wiki/index.md` 即可用 Obsidian 浏览知识库。

### 3.3 独立 Wiki 同步

在 Obsidian 中编辑实体页面后，将变更同步回图谱：

```bash
# 全量同步所有 Wiki 页面
python scripts/sync_wiki_to_graph.py

# 仅同步指定实体
python scripts/sync_wiki_to_graph.py --entity "RK3588"

# 预览变更但不实际修改图谱
python scripts/sync_wiki_to_graph.py --dry-run
```

### 3.4 独立推理

```bash
# 完整分析
python scripts/run_inference.py --insights

# 查找两实体间路径
python scripts/run_inference.py --find-paths "Elon Musk" "Tesla"

# 仅计算中心性
python scripts/run_inference.py --centrality

# 仅查找社区
python scripts/run_inference.py --communities
```

### 3.5 Jupyter 探索

```bash
cd notebooks
jupyter notebook explore_graph.ipynb
```

包含：统计概览、中心性分析、社区可视化、图布局渲染、Cypher 导出。

### 3.6 单元测试

```bash
python -m pytest tests/ -v
```

覆盖：分块功能、实体相似度、同名合并、不同名区分。

### 3.7 自定义 Schema

编辑 `config/schema.json` 添加领域特定的实体和关系类型：

```json
{
  "entities": [
    {"type": "PERSON", "label": "人物", "description": "..."},
    {"type": "TECHNOLOGY", "label": "技术", "description": "..."}
  ],
  "relations": [
    {"type": "INVENTED", "label": "发明", "valid_subject": ["PERSON"], "valid_object": ["TECHNOLOGY"]}
  ]
}
```

### 3.8 飞书文档同步 (Feishu Sync)

通过飞书同步插件，可自动将云端知识库拉取到本地进行处理。

**步骤：**

1.  **获取凭证**：
    在 [飞书开放平台](https://open.feishu.cn/) 创建应用，获取 `App ID` 和 `App Secret`。
2.  **配置权限**：
    为应用添加以下权限：`wiki:wiki:readonly`, `docx:document:readonly`, `drive:drive:readonly`。
3.  **填写配置**：
    编辑 `config/feishu_config.yaml`：
    ```yaml
    feishu:
      app_id: "cli_xxxx"
      app_secret: "xxxx"
      space_id: "69xxx" # 知识库 URL 中 /wiki/space/ 后的部分
    ```
4.  **执行同步**：
    ```bash
    python scripts/sync_feishu.py
    ```
5.  **构建图谱**：
    同步后的文档将自动存入 `data/raw/`，直接运行主流程即可：
    ```bash
    python scripts/run_extraction.py
    ```

---

## 四、参考文献与出处

### 4.1 Karpathy LLM Wiki 原始出处

| 来源 | 日期 | 关键内容 |
|------|------|---------|
| **Andrej Karpathy GitHub Gist** | 2026-04-03 | 首次提出 "LLM Wiki" 概念，描述三文件夹架构 (`raw/`, `articles/`, `schema`) |
| **Karpathy Context Patterns** | 2026 | contextpatterns.com — "Context engineering is the delicate art of filling the context window" |
| **Karpathy X/Twitter** | 2026-04-03 | 描述个人研究记忆管理系统，称其为 "hacky collection of scripts" |

### 4.2 二手分析与解读

| 来源 | 日期 | 要点 |
|------|------|------|
| **VentureBeat** | 2026-04 | 标题 "Karpathy bypasses RAG"，引发行业争论 |
| **Atlan: LLM Wiki vs RAG** | 2026-04-07 | compile-time vs query-time knowledge assembly；50k-100k tokens 为分界线 |
| **Archyde: Beyond RAG** | 2026-04-04 | "编译器"隐喻；self-healing linting；SFT 终局 |
| **MindStudio: Compiler Analogy** | 2026-04-07 | 类比源代码→编译→机器码，LLM 将原始文档→编译→结构化知识 |
| **Proudfrog** | 2026-04-04 | ~100 篇文章 / 40 万词规模下的实证效果；Links beat embeddings |
| **Denser.ai** | 2026-04-16 | "Compile once, query many"；hybrid retrieval 企业落地方案 |
| **Decode The Future** | 2026-04-13 | 3-layer pattern；L1 cache 隐喻；scale ceiling 分析 |
| **NewClawTimes** | 2026-04-05 | Agent memory design；context-limit reset 问题 |

### 4.3 核心观点摘录

#### Karpathy 的核心隐喻：知识即编译代码
> Standard RAG is like cooking from scratch every time you're hungry. A compiled knowledge base is like meal prepping once and reheating.
> — MindStudio, 2026-04-07

#### 向量检索的局限性
> Vector search is a blunt instrument. It relies on semantic similarity, which often misses the precise, structural relationships required for complex engineering.
> — Archyde, 2026-04-04

#### 规模阈值
> The 50,000–100,000 token threshold is where the wiki approach stops working reliably. Beyond that, you need semantic search — there is no shortcut around information-theoretic limits of context windows.
> — Decode The Future, 2026-04-13

#### Links vs Embeddings
> You can follow a link. You cannot follow a vector.
> — Proudfrog, 2026-04-04

#### 自愈合的价值
> The LLM "lints" the files, correcting contradictions and updating summaries as the project grows. This approach solves the "Lost in the Middle" phenomenon.
> — Archyde, 2026-04-04

#### 混合方案的未来
> The strongest approach for mid-scale use cases is a hybrid: a compiled wiki for stable core knowledge, plus RAG for dynamic or overflow content.
> — Decode The Future, 2026-04-13

### 4.4 传统参考资料

| 来源 | 链接 |
|------|------|
| Microsoft GraphRAG | https://github.com/microsoft/graphrag |
| Neo4j LLM Integration | https://neo4j.com/docs/cypher-chatgpt/ |
| LangChain Knowledge Graph | https://python.langchain.com/docs/use_cases/graph/ |

---

## 五、设计决策记录

### 5.1 为什么选择 NetworkX 而非 Neo4j？

- **轻量级**：无需安装和运行外部数据库服务
- **Python 原生**：与 LLM 调用无缝集成
- **适合原型**：快速迭代，易于调试
- **可扩展**：后续可导出为 GraphML 导入 Neo4j

### 5.2 为什么保留三元组抽取而非直接生成 Wiki？

- **两阶段解耦**：抽取阶段确保事实准确性，编译阶段负责可读性
- **可追溯**：每条关系都保留 `source_chunk` 和 `source_text` 溯源
- **可复用**：图谱可用于算法分析，Wiki 用于人类阅读

### 5.3 LLM 在流程中的四次使用

| 阶段 | 用途 | 温度 |
|------|------|------|
| **抽取** | 从文本中提取三元组 | 0 |
| **消歧** | 判断实体是否同指 | 0 |
| **摘要** | 为实体生成一句话简介 | 0.3 |
| **Lint** | 裁决矛盾关系 | 0 |

### 5.4 Wiki 格式的选择

选用 Obsidian 兼容的 `[[WikiLinks]]` 格式：
- **零锁定**：纯 Markdown 文本，不依赖任何专有格式
- **生态丰富**：Obsidian / Logseq / Foam / Docusaurus 均可打开
- **版本控制友好**：`git diff` 可以直接查看知识变更

### 5.5 为什么实现双向同步？

传统知识图谱流程是单向的：文档 → 抽取 → 图谱 → Wiki。用户无法直接修改图谱。
通过双向同步：
- 用户在 Obsidian 中编辑 Wiki 页面即可调整知识（增删关系、修改置信度）
- 同步后变更自动反馈到图谱，无需重新跑 LLM 抽取
- 形成"图谱生成 Wiki → 用户编辑 Wiki → 同步回图谱"的闭环

---

## 六、局限性与改进方向

### 6.1 当前局限

1. **批量性能**：每个实体独立调用 LLM 生成摘要，大规模图谱速度较慢
2. **Wiki 编辑限制**：仅支持关系行格式编辑（添加/删除/修改置信度），不支持自然语言编辑

### 6.2 改进方向

- [ ] **异步批量**：使用 LLM batch API 并行生成 Wiki 页面
- [ ] **RAG 混合层**：对超出 context window 的文档引入向量检索作为补充
- [x] **RAG 混合层**：对超出 context window 的文档引入向量检索作为补充（TF-IDF / API Embedding 双后端）
- [x] **Web UI**：`scripts/serve_webui.py` — Flask + D3.js 轻量级界面，支持浏览、搜索、编辑、图可视化、双向同步
- [ ] **多模态增强**：集成视觉模型解析图片中的图表与手写笔记
- [ ] **多模态增强**：集成视觉模型解析图片中的图表与手写笔记
- [ ] **自然语言 Wiki 编辑**：支持用户在 Wiki 中用自然语言描述变更，自动解析为图谱操作

---

*文档版本: v1.4.1*
*最后更新: 2026-05-26*
