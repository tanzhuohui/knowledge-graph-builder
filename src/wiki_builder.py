import os
import re
import json
import yaml
import requests
import time
from collections import defaultdict


class WikiBuilder:
    def __init__(self, graph, output_dir, config_path=None, chunks_dir=None):
        self.graph = graph
        self.output_dir = output_dir
        self.entities_dir = os.path.join(output_dir, "entities")
        self.llm_config = self._load_llm_config(config_path)
        self.chunk_to_source = self._load_chunk_mapping(chunks_dir)

    def _load_llm_config(self, path):
        if path is None:
            path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "llm_config.yaml",
            )
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return None

    def _load_chunk_mapping(self, chunks_dir):
        """建立chunk_id到source文档的映射"""
        chunk_to_source = {}
        if chunks_dir is None:
            # 默认使用项目data/chunks目录
            chunks_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "data", "chunks"
            )
        if not os.path.exists(chunks_dir):
            return chunk_to_source
        
        for fname in os.listdir(chunks_dir):
            if fname.endswith('_chunks.json'):
                fpath = os.path.join(chunks_dir, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        for chunk in json.load(f):
                            chunk_to_source[chunk['id']] = chunk['source']
                except Exception:
                    continue
        return chunk_to_source

    def _safe_filename(self, name):
        safe = re.sub(r'[^\w\u4e00-\u9fff\s-]', '', name)
        safe = re.sub(r'\s+', '_', safe.strip())
        return safe if safe else "unknown_entity"

    def _get_entity_relations(self, entity_name):
        outgoing = []
        incoming = []
        for successor in self.graph.successors(entity_name):
            edge_data = self.graph.edges[entity_name, successor]
            outgoing.append({
                "target": successor,
                "relation": edge_data.get("relation", "RELATED_TO"),
                "confidence": edge_data.get("confidence", 0),
                "source_text": edge_data.get("source_text", ""),
                "source_chunk": edge_data.get("source_chunk", ""),
            })
        for predecessor in self.graph.predecessors(entity_name):
            edge_data = self.graph.edges[predecessor, entity_name]
            incoming.append({
                "source": predecessor,
                "relation": edge_data.get("relation", "RELATED_TO"),
                "confidence": edge_data.get("confidence", 0),
                "source_text": edge_data.get("source_text", ""),
                "source_chunk": edge_data.get("source_chunk", ""),
            })
        return outgoing, incoming

    def _get_entity_type(self, entity_name):
        attrs = self.graph.nodes[entity_name]
        types = attrs.get("types", "ENTITY")
        if isinstance(types, set):
            types = ", ".join(sorted(types))
        return types

    def _is_junk_entity(self, name):
        """Check if an entity name is likely garbage (e.g. error messages)."""
        if len(name) < 2:
            return True
        junk_keywords = ["404", "Not Found", "Error", "Failed", "Exception", "undefined", "Traceback"]
        if any(kw in name for kw in junk_keywords):
            return True
        return False

    def _llm_summary(self, entity_name, entity_type, outgoing, incoming):
        if not self.llm_config:
            return f"{entity_name} is a {entity_type} entity with {len(outgoing)} outgoing and {len(incoming)} incoming relations."

        relations_text = []
        for rel in outgoing[:5]:
            relations_text.append(f"- {entity_name} --[{rel['relation']}]--> {rel['target']}")
        for rel in incoming[:5]:
            relations_text.append(f"- {rel['source']} --[{rel['relation']}]--> {entity_name}")

        prompt = f"""请根据以下关系信息，为实体 "{entity_name}" (类型: {entity_type}) 生成一段简洁的摘要 (50-100字)。

关系列表:
{chr(10).join(relations_text)}

要求:
- 只输出摘要文本，不要其他内容
- 使用客观陈述语气
- 如果信息不足以形成完整描述，简要说明该实体在知识图谱中的位置
"""
        try:
            provider = self.llm_config["llm"].get("provider", "ollama")
            if provider == "lmstudio":
                return self._call_lmstudio(prompt)
            return self._call_ollama(prompt)
        except Exception:
            return f"{entity_name} is a {entity_type} entity connected to {len(outgoing) + len(incoming)} other entities."

    def _call_lmstudio(self, prompt):
        base_url = self.llm_config["llm"]["base_url"].rstrip("/")
        api_key = self.llm_config["llm"].get("api_key", "")
        model = self.llm_config["llm"]["model"]
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
            	"model": model, 
            	"messages": [{"role": "user", "content": prompt}], 
            	"temperature": 0.3,
            	"chat_template_kwargs":{"enable_thinking":False},
            },
            timeout=60,
        )
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _call_ollama(self, prompt):
        model = self.llm_config["llm"]["model"]
        base_url = self.llm_config["llm"]["base_url"]
        resp = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        return resp.json().get("response", "").strip()

    def _get_entity_sources(self, entity_name):
        """获取实体的所有来源文档"""
        sources = set()
        # 从出向关系获取来源
        for successor in self.graph.successors(entity_name):
            edge_data = self.graph.edges[entity_name, successor]
            source_chunk = edge_data.get("source_chunk", "")
            if source_chunk:
                # 优先从映射表查找
                if source_chunk in self.chunk_to_source:
                    sources.add(self.chunk_to_source[source_chunk])
                else:
                    # 备用：从 chunk_id 解析来源文档名（格式：文件名_chunk_N）
                    parts = source_chunk.rsplit('_chunk_', 1)
                    if len(parts) == 2:
                        sources.add(parts[0])
                    else:
                        # 尝试 row_ 格式（CSV）
                        parts = source_chunk.rsplit('_row_', 1)
                        if len(parts) == 2:
                            sources.add(parts[0])
        # 从入向关系获取来源
        for predecessor in self.graph.predecessors(entity_name):
            edge_data = self.graph.edges[predecessor, entity_name]
            source_chunk = edge_data.get("source_chunk", "")
            if source_chunk:
                if source_chunk in self.chunk_to_source:
                    sources.add(self.chunk_to_source[source_chunk])
                else:
                    parts = source_chunk.rsplit('_chunk_', 1)
                    if len(parts) == 2:
                        sources.add(parts[0])
                    else:
                        parts = source_chunk.rsplit('_row_', 1)
                        if len(parts) == 2:
                            sources.add(parts[0])
        return sorted(sources)

    def _generate_entity_page(self, entity_name):
        entity_type = self._get_entity_type(entity_name)
        outgoing, incoming = self._get_entity_relations(entity_name)
        sources = self._get_entity_sources(entity_name)
        summary = self._llm_summary(entity_name, entity_type, outgoing, incoming)

        # 构建Frontmatter
        frontmatter_lines = ["---"]
        frontmatter_lines.append(f"title: {entity_name}")
        if sources:
            main_source = sources[0]
            frontmatter_lines.append(f"source: {main_source}")
            if len(sources) > 1:
                frontmatter_lines.append("sources:")
                for s in sources[1:]:
                    frontmatter_lines.append(f"  - {s}")
        frontmatter_lines.append("---\n")

        lines = frontmatter_lines + [
            f"# {entity_name}",
            f"",
            f"**类型**: {entity_type}",
            f"",
            f"> {summary}",
            f"",
            f"## 出向关系 (Outgoing)",
            f"",
        ]

        if outgoing:
            for rel in sorted(outgoing, key=lambda x: -x.get("confidence", 0)):
                target_link = f"[[{rel['target']}]]"
                lines.append(f"- **{rel['relation']}** → {target_link} (置信度: {rel['confidence']:.2f})")
                if rel.get("source_text"):
                    snippet = rel["source_text"][:80]
                    lines.append(f"  - *原文: \"{snippet}...\"*")
        else:
            lines.append("- 无出向关系")

        lines.extend([
            f"",
            f"## 入向关系 (Incoming)",
            f"",
        ])

        if incoming:
            for rel in sorted(incoming, key=lambda x: -x.get("confidence", 0)):
                source_link = f"[[{rel['source']}]]"
                lines.append(f"- **{rel['relation']}** ← {source_link} (置信度: {rel['confidence']:.2f})")
                if rel.get("source_text"):
                    snippet = rel["source_text"][:80]
                    lines.append(f"  - *原文: \"{snippet}...\"*")
        else:
            lines.append("- 无入向关系")

        lines.extend([
            f"",
            f"## 统计",
            f"",
            f"- 出向连接数: {len(outgoing)}",
            f"- 入向连接数: {len(incoming)}",
            f"- 总连接数: {len(outgoing) + len(incoming)}",
            f"",
        ])

        return "\n".join(lines)

    def _generate_index(self, entity_pages):
        """生成按来源分组的知识库索引"""
        # 建立来源到实体的映射
        source_to_entities = defaultdict(list)
        
        for page_info in entity_pages:
            entity_name = page_info["name"]
            sources = self._get_entity_sources_by_name(entity_name)
            main_source = sources[0] if sources else "未知来源"
            source_to_entities[main_source].append(page_info)

        lines = [
            "# Knowledge Base Index",
            f"",
            f"**Generated by**: LLM Knowledge Graph Builder",
            f"**Total entities**: {len(entity_pages)}",
            f"",
            f"## 使用说明",
            f"- 本索引按**来源文档**分组，方便追溯原始出处",
            f"- 点击实体链接可查看详情、关系网络和原文引用",
            f"- 实体页面顶部Frontmatter标注了来源文档",
            f"- 在Obsidian中可使用`source:`属性进行筛选和排序",
            f"",
        ]

        # 按来源分组输出
        for source in sorted(source_to_entities.keys()):
            pages = source_to_entities[source]
            lines.append(f"## 来源: {source}")
            lines.append("")
            for page_info in sorted(pages, key=lambda x: x["name"]):
                filename = page_info["filename"]
                lines.append(f"- [[{filename}|{page_info['name']}]]")
            lines.append("")

        lines.extend([
            f"## Usage",
            f"",
            f"- Open individual entity pages via the links above",
            f"- Relations are marked with [[WikiLinks]] for navigation",
            f"- Compatible with Obsidian, Logseq, and other Markdown wikis",
            f"",
        ])

        return "\n".join(lines)

    def _get_entity_sources_by_name(self, entity_name):
        """通过实体名获取来源文档列表"""
        sources = set()
        # 从出向关系获取
        if entity_name in self.graph:
            for successor in self.graph.successors(entity_name):
                edge_data = self.graph.edges[entity_name, successor]
                source_chunk = edge_data.get("source_chunk", "")
                if source_chunk:
                    # 优先从映射表查找
                    if source_chunk in self.chunk_to_source:
                        sources.add(self.chunk_to_source[source_chunk])
                    else:
                        # 备用：从 chunk_id 解析来源文档名
                        parts = source_chunk.rsplit('_chunk_', 1)
                        if len(parts) == 2:
                            sources.add(parts[0])
                        else:
                            parts = source_chunk.rsplit('_row_', 1)
                            if len(parts) == 2:
                                sources.add(parts[0])
            # 从入向关系获取
            for predecessor in self.graph.predecessors(entity_name):
                edge_data = self.graph.edges[predecessor, entity_name]
                source_chunk = edge_data.get("source_chunk", "")
                if source_chunk:
                    if source_chunk in self.chunk_to_source:
                        sources.add(self.chunk_to_source[source_chunk])
                    else:
                        parts = source_chunk.rsplit('_chunk_', 1)
                        if len(parts) == 2:
                            sources.add(parts[0])
                        else:
                            parts = source_chunk.rsplit('_row_', 1)
                            if len(parts) == 2:
                                sources.add(parts[0])
        return sorted(sources)

    def compile(self):
        os.makedirs(self.entities_dir, exist_ok=True)
        entity_pages = []
        nodes = list(self.graph.nodes())

        # Filter junk entities
        valid_nodes = [n for n in nodes if not self._is_junk_entity(n)]
        skipped = len(nodes) - len(valid_nodes)
        print(f"  Compiling {len(valid_nodes)} valid entities (skipped {skipped} junk)...")

        for i, entity_name in enumerate(valid_nodes):
            if i % 10 == 0:
                print(f"    Processing entity {i+1}/{len(valid_nodes)}: {entity_name[:40]}")

            page_content = self._generate_entity_page(entity_name)
            filename = self._safe_filename(entity_name)
            filepath = os.path.join(self.entities_dir, f"{filename}.md")

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(page_content)

            entity_type = self._get_entity_type(entity_name)
            entity_pages.append({
                "name": entity_name,
                "filename": filename,
                "type": entity_type,
                "filepath": filepath,
            })

            time.sleep(0.1)

        print(f"  Generating index.md...")
        index_content = self._generate_index(entity_pages)
        index_path = os.path.join(self.output_dir, "index.md")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_content)

        stats_path = os.path.join(self.output_dir, "wiki_stats.json")
        stats = {
            "total_entities": len(entity_pages),
            "types": list(set(p["type"] for p in entity_pages)),
            "files": [p["filepath"] for p in entity_pages],
        }
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)

        print(f"  Wiki compiled to: {self.output_dir}")
        print(f"  Total pages: {len(entity_pages)}")
        return self.output_dir
