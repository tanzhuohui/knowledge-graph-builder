"""双向同步模块：从 Wiki Markdown 页面的修改反馈回知识图谱"""

import os
import re
import json
import copy


class WikiSync:
    """解析 Wiki 实体页面，检测用户编辑，将变更反馈到图谱"""

    RELATION_OUT_RE = re.compile(
        r"^-\s+\*\*(?P<relation>\w+)\*\*\s+→\s+\[\[(?P<target>[^\]]+)\]\]\s+\(置信度:\s*(?P<confidence>[\d.]+)\)"
    )
    RELATION_IN_RE = re.compile(
        r"^-\s+\*\*(?P<relation>\w+)\*\*\s+←\s+\[\[(?P<source>[^\]]+)\]\]\s+\(置信度:\s*(?P<confidence>[\d.]+)\)"
    )

    def __init__(self, graph, wiki_dir):
        self.graph = graph
        self.wiki_dir = wiki_dir
        self.entities_dir = os.path.join(wiki_dir, "entities")
        self.schema_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "schema.json"
        )
        self._valid_relations = self._load_valid_relations()

    def _load_valid_relations(self):
        """加载 schema 中的合法关系类型集合"""
        if not os.path.exists(self.schema_path):
            return None
        with open(self.schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        return {r["type"] for r in schema.get("relations", [])}

    # ---- 解析 ----

    def parse_entity_page(self, filepath):
        """解析单个实体页面，返回结构化数据"""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return self.parse_entity_content(content)

    def parse_entity_content(self, content):
        """从 Markdown 内容中提取实体信息"""
        result = {
            "title": None,
            "entity_type": None,
            "sources": [],
            "outgoing": [],
            "incoming": [],
        }

        lines = content.split("\n")
        in_frontmatter = False
        in_outgoing = False
        in_incoming = False

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Frontmatter
            if line == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    i += 1
                    continue
                else:
                    in_frontmatter = False
                    i += 1
                    continue

            if in_frontmatter:
                if line.startswith("title:"):
                    result["title"] = line.split(":", 1)[1].strip()
                elif line.startswith("source:"):
                    src = line.split(":", 1)[1].strip()
                    if src not in result["sources"]:
                        result["sources"].append(src)
                elif re.match(r"^\s+- .+", line):
                    # sources list item
                    src = line.strip("- ").strip()
                    if src not in result["sources"]:
                        result["sources"].append(src)
                i += 1
                continue

            # Title
            m = re.match(r"^#\s+(.+)", line)
            if m:
                result["title"] = m.group(1).strip()
                i += 1
                continue

            # Type
            m = re.match(r"^\*\*类型\*\*:\s*(.+)", line)
            if m:
                result["entity_type"] = m.group(1).strip()
                i += 1
                continue

            # Section headers
            if line == "## 出向关系 (Outgoing)":
                in_outgoing = True
                in_incoming = False
                i += 1
                continue
            if line == "## 入向关系 (Incoming)":
                in_outgoing = False
                in_incoming = True
                i += 1
                continue
            if line.startswith("## "):
                in_outgoing = False
                in_incoming = False

            # Relation lines
            if in_outgoing:
                m = self.RELATION_OUT_RE.match(line)
                if m:
                    result["outgoing"].append({
                        "relation": m.group("relation"),
                        "target": m.group("target"),
                        "confidence": float(m.group("confidence")),
                    })
            if in_incoming:
                m = self.RELATION_IN_RE.match(line)
                if m:
                    result["incoming"].append({
                        "relation": m.group("relation"),
                        "source": m.group("source"),
                        "confidence": float(m.group("confidence")),
                    })

            i += 1

        return result

    # ---- 对比 ----

    def _graph_edges_for_entity(self, entity_name):
        """从图谱中获取某实体的出向和入向关系"""
        outgoing = []
        incoming = []

        if not self.graph.has_node(entity_name):
            return outgoing, incoming

        for successor in self.graph.successors(entity_name):
            edge = self.graph.edges[entity_name, successor]
            outgoing.append({
                "relation": edge.get("relation", "RELATED_TO"),
                "target": successor,
                "confidence": edge.get("confidence", 0),
            })

        for predecessor in self.graph.predecessors(entity_name):
            edge = self.graph.edges[predecessor, entity_name]
            incoming.append({
                "relation": edge.get("relation", "RELATED_TO"),
                "source": predecessor,
                "confidence": edge.get("confidence", 0),
            })

        return outgoing, incoming

    def _edge_key(self, edge, direction):
        """为关系生成唯一键用于对比"""
        if direction == "out":
            return (edge["relation"], edge["target"])
        return (edge["relation"], edge["source"])

    def diff_entity(self, entity_name, page_content=None, filepath=None):
        """对比 Wiki 页面与图谱中的关系，返回变更集"""
        if filepath and os.path.exists(filepath):
            parsed = self.parse_entity_page(filepath)
        elif page_content:
            parsed = self.parse_entity_content(page_content)
        else:
            return None

        graph_out, graph_in = self._graph_edges_for_entity(entity_name)

        graph_out_keys = {self._edge_key(e, "out") for e in graph_out}
        graph_in_keys = {self._edge_key(e, "in") for e in graph_in}

        page_out_keys = {self._edge_key(e, "out") for e in parsed["outgoing"]}
        page_in_keys = {self._edge_key(e, "in") for e in parsed["incoming"]}

        changes = {
            "entity": entity_name,
            "added_outgoing": [],
            "removed_outgoing": [],
            "updated_outgoing": [],
            "added_incoming": [],
            "removed_incoming": [],
            "updated_incoming": [],
            "new_entity_type": None,
        }

        # 出向关系变更
        for edge in parsed["outgoing"]:
            key = self._edge_key(edge, "out")
            if key not in graph_out_keys:
                changes["added_outgoing"].append(edge)
            else:
                graph_edge = next(e for e in graph_out if self._edge_key(e, "out") == key)
                if abs(edge["confidence"] - graph_edge["confidence"]) > 0.001:
                    changes["updated_outgoing"].append(edge)

        for edge in graph_out:
            key = self._edge_key(edge, "out")
            if key not in page_out_keys:
                changes["removed_outgoing"].append(edge)

        # 入向关系变更
        for edge in parsed["incoming"]:
            key = self._edge_key(edge, "in")
            if key not in graph_in_keys:
                changes["added_incoming"].append(edge)
            else:
                graph_edge = next(e for e in graph_in if self._edge_key(e, "in") == key)
                if abs(edge["confidence"] - graph_edge["confidence"]) > 0.001:
                    changes["updated_incoming"].append(edge)

        for edge in graph_in:
            key = self._edge_key(edge, "in")
            if key not in page_in_keys:
                changes["removed_incoming"].append(edge)

        # 实体类型变更
        if parsed["entity_type"]:
            graph_types = self.graph.nodes[entity_name].get("types", set()) if self.graph.has_node(entity_name) else set()
            graph_type_str = ", ".join(sorted(graph_types)) if isinstance(graph_types, set) else str(graph_types)
            if parsed["entity_type"] != graph_type_str:
                changes["new_entity_type"] = parsed["entity_type"]

        return changes

    def diff_all_pages(self):
        """扫描所有 Wiki 页面，返回全局变更集"""
        if not os.path.exists(self.entities_dir):
            return []

        results = []
        for fname in os.listdir(self.entities_dir):
            if not fname.endswith(".md"):
                continue

            filepath = os.path.join(self.entities_dir, fname)
            parsed = self.parse_entity_page(filepath)
            entity_name = parsed["title"]

            if not entity_name:
                continue

            changes = self.diff_entity(entity_name, filepath=filepath)
            if changes and self._has_changes(changes):
                results.append(changes)

        return results

    def _has_changes(self, changes):
        """判断变更集是否包含实质变更"""
        return bool(
            changes["added_outgoing"]
            or changes["removed_outgoing"]
            or changes["updated_outgoing"]
            or changes["added_incoming"]
            or changes["removed_incoming"]
            or changes["updated_incoming"]
            or changes["new_entity_type"]
        )

    # ---- 应用变更 ----

    def apply_changes(self, changes, dry_run=False):
        """将变更集应用到图谱"""
        entity = changes["entity"]
        applied = {
            "entity": entity,
            "actions": [],
        }

        if not dry_run:
            if not self.graph.has_node(entity):
                self.graph.add_node(entity, types=set())

        # 更新实体类型
        if changes["new_entity_type"]:
            new_type = changes["new_entity_type"]
            action = f"类型变更 → {new_type}"
            applied["actions"].append(action)
            if not dry_run:
                if self.graph.has_node(entity):
                    self.graph.nodes[entity]["types"] = {new_type}
                else:
                    self.graph.add_node(entity, types={new_type})

        # 新增出向关系
        for edge in changes["added_outgoing"]:
            action = f"新增出向: {entity} --[{edge['relation']}]--> {edge['target']} (置信度: {edge['confidence']})"
            applied["actions"].append(action)
            if not dry_run:
                if not self.graph.has_node(edge["target"]):
                    self.graph.add_node(edge["target"], types=set())
                if self.graph.has_edge(entity, edge["target"]):
                    existing = self.graph.edges[entity, edge["target"]]
                    if existing.get("relation") == edge["relation"]:
                        existing["confidence"] = edge["confidence"]
                    else:
                        self.graph.edges[entity, edge["target"]].update({
                            "relation": edge["relation"],
                            "confidence": edge["confidence"],
                            "wiki_updated": True,
                        })
                else:
                    self.graph.add_edge(
                        entity, edge["target"],
                        relation=edge["relation"],
                        confidence=edge["confidence"],
                        wiki_updated=True,
                        source_text="",
                        source_chunk="",
                    )

        # 删除出向关系
        for edge in changes["removed_outgoing"]:
            action = f"删除出向: {entity} --[{edge['relation']}]--> {edge['target']}"
            applied["actions"].append(action)
            if not dry_run:
                if self.graph.has_edge(entity, edge["target"]):
                    existing = self.graph.edges[entity, edge["target"]]
                    if existing.get("relation") == edge["relation"]:
                        self.graph.remove_edge(entity, edge["target"])

        # 更新出向置信度
        for edge in changes["updated_outgoing"]:
            action = f"更新出向置信度: {entity} --[{edge['relation']}]--> {edge['target']} → {edge['confidence']}"
            applied["actions"].append(action)
            if not dry_run:
                if self.graph.has_edge(entity, edge["target"]):
                    self.graph.edges[entity, edge["target"]]["confidence"] = edge["confidence"]
                    self.graph.edges[entity, edge["target"]]["wiki_updated"] = True

        # 新增入向关系（本质是添加从 source 到 entity 的边）
        for edge in changes["added_incoming"]:
            action = f"新增入向: {edge['source']} --[{edge['relation']}]--> {entity} (置信度: {edge['confidence']})"
            applied["actions"].append(action)
            if not dry_run:
                if not self.graph.has_node(edge["source"]):
                    self.graph.add_node(edge["source"], types=set())
                if not self.graph.has_node(entity):
                    self.graph.add_node(entity, types=set())
                if self.graph.has_edge(edge["source"], entity):
                    existing = self.graph.edges[edge["source"], entity]
                    if existing.get("relation") == edge["relation"]:
                        existing["confidence"] = edge["confidence"]
                    else:
                        self.graph.edges[edge["source"], entity].update({
                            "relation": edge["relation"],
                            "confidence": edge["confidence"],
                            "wiki_updated": True,
                        })
                else:
                    self.graph.add_edge(
                        edge["source"], entity,
                        relation=edge["relation"],
                        confidence=edge["confidence"],
                        wiki_updated=True,
                        source_text="",
                        source_chunk="",
                    )

        # 删除入向关系
        for edge in changes["removed_incoming"]:
            action = f"删除入向: {edge['source']} --[{edge['relation']}]--> {entity}"
            applied["actions"].append(action)
            if not dry_run:
                if self.graph.has_edge(edge["source"], entity):
                    existing = self.graph.edges[edge["source"], entity]
                    if existing.get("relation") == edge["relation"]:
                        self.graph.remove_edge(edge["source"], entity)

        # 更新入向置信度
        for edge in changes["updated_incoming"]:
            action = f"更新入向置信度: {edge['source']} --[{edge['relation']}]--> {entity} → {edge['confidence']}"
            applied["actions"].append(action)
            if not dry_run:
                if self.graph.has_edge(edge["source"], entity):
                    self.graph.edges[edge["source"], entity]["confidence"] = edge["confidence"]
                    self.graph.edges[edge["source"], entity]["wiki_updated"] = True

        return applied

    def sync_all(self, dry_run=False):
        """全量同步：扫描所有 Wiki 页面并应用变更"""
        diffs = self.diff_all_pages()

        if not diffs:
            print("  No wiki changes detected. Graph is up to date.")
            return []

        results = []
        for changes in diffs:
            result = self.apply_changes(changes, dry_run)
            results.append(result)

        mode = "[Dry Run] " if dry_run else ""
        print(f"  {mode}Sync complete: {len(results)} entity page(s) modified")
        for r in results:
            print(f"    {r['entity']}:")
            for a in r["actions"]:
                print(f"      - {a}")

        return results
