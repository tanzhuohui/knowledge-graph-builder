#!/usr/bin/env python3
"""独立同步脚本：从 Wiki Markdown 页面的修改反馈回知识图谱"""

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.graph_builder import GraphBuilder
from src.wiki_sync import WikiSync


def load_graph():
    """从已有图文件加载图谱"""
    graphs_dir = os.path.join(BASE_DIR, "data", "graphs")

    for filename, fmt in [
        ("knowledge_graph.json", "json"),
        ("knowledge_graph.graphml", "graphml"),
        ("knowledge_graph.gexf", "gexf"),
    ]:
        filepath = os.path.join(graphs_dir, filename)
        if os.path.exists(filepath):
            print(f"  Loading graph from {filepath}")
            builder = GraphBuilder()
            if fmt == "graphml":
                import networkx as nx
                builder.graph = nx.read_graphml(filepath)
                # 恢复 types 为 set
                for node, attrs in builder.graph.nodes(data=True):
                    t = attrs.get("types", "")
                    if isinstance(t, str) and t:
                        attrs["types"] = set(t.split(", "))
            elif fmt == "json":
                import networkx as nx
                builder.graph = nx.node_link_graph(json.load(open(filepath)), directed=True)
            elif fmt == "gexf":
                import networkx as nx
                builder.graph = nx.read_gexf(filepath)
                for node, attrs in builder.graph.nodes(data=True):
                    t = attrs.get("types", "")
                    if isinstance(t, str) and t:
                        attrs["types"] = set(t.split(", "))
            return builder.graph

    print("  No existing graph found. Run run_extraction.py first.")
    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Wiki → Graph 双向同步")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更，不实际修改图谱")
    parser.add_argument("--entity", type=str, help="仅同步指定实体（文件名或实体名）")
    args = parser.parse_args()

    print("=" * 60)
    print("  Wiki → Graph Sync")
    print("=" * 60)

    wiki_dir = os.path.join(BASE_DIR, "data", "wiki")
    if not os.path.exists(os.path.join(wiki_dir, "entities")):
        print("  No wiki found. Run run_extraction.py first.")
        return

    graph = load_graph()
    if graph is None:
        return

    syncer = WikiSync(graph, wiki_dir)

    if args.entity:
        # 单个实体同步
        entities_dir = os.path.join(wiki_dir, "entities")
        # 尝试直接匹配文件名
        filepath = os.path.join(entities_dir, args.entity)
        if not filepath.endswith(".md"):
            filepath += ".md"
        if not os.path.exists(filepath):
            print(f"  Entity page not found: {args.entity}")
            return

        parsed = syncer.parse_entity_page(filepath)
        changes = syncer.diff_entity(parsed["title"], filepath=filepath)

        if changes and syncer._has_changes(changes):
            result = syncer.apply_changes(changes, dry_run=args.dry_run)
            mode = "[Dry Run] " if args.dry_run else ""
            print(f"\n  {mode}Changes for {result['entity']}:")
            for a in result["actions"]:
                print(f"    - {a}")
        else:
            print(f"  No changes detected for {parsed['title']}")
    else:
        # 全量同步
        results = syncer.sync_all(dry_run=args.dry_run)

    # 保存更新后的图谱
    if not args.dry_run:
        graphs_dir = os.path.join(BASE_DIR, "data", "graphs")
        builder = GraphBuilder()
        builder.graph = graph

        graphml_path = os.path.join(graphs_dir, "knowledge_graph.graphml")
        gexf_path = os.path.join(graphs_dir, "knowledge_graph.gexf")
        json_path = os.path.join(graphs_dir, "knowledge_graph.json")

        builder.save_graphml(graphml_path)
        builder.save_gexf(gexf_path)

        # JSON 导出
        import networkx as nx
        json_data = nx.node_link_data(graph)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  Graph saved (updated by wiki sync)")

    print(f"\n{'=' * 60}")
    print("  Done.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
