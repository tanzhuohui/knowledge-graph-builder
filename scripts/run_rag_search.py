#!/usr/bin/env python3
"""混合搜索脚本：向量搜索文档分块 + 图谱遍历"""

import os
import sys
import json
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.vector_store import VectorStore
from src.graph_builder import GraphBuilder
from src.inferencer import GraphInferencer


def load_llm_config():
    import yaml
    path = os.path.join(BASE_DIR, "config", "llm_config.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def load_graph():
    import networkx as nx
    gml = os.path.join(BASE_DIR, "data", "graphs", "knowledge_graph.graphml")
    if os.path.exists(gml):
        return nx.read_graphml(gml)
    return None


def load_all_chunks():
    chunks_dir = os.path.join(BASE_DIR, "data", "chunks")
    all_chunks = []
    for fname in os.listdir(chunks_dir):
        if fname.endswith("_chunks.json"):
            fp = os.path.join(chunks_dir, fname)
            with open(fp, encoding="utf-8") as f:
                try:
                    all_chunks.extend(json.load(f))
                except Exception:
                    pass
    return all_chunks


def build_vector_store():
    """构建/加载向量索引"""
    vs_path = os.path.join(BASE_DIR, "data", "chunks", "vector_index.json")
    chunks = load_all_chunks()

    vs = VectorStore.load(vs_path)
    if vs.needs_rebuild(chunks) or len(vs.chunks) == 0:
        print(f"  Building vector index for {len(chunks)} chunks ...")
        vs = VectorStore()
        vs.build_index(chunks)
        vs.save(vs_path)
    else:
        print(f"  Using cached vector index ({len(vs.chunks)} chunks)")
    return vs


def main():
    import argparse

    parser = argparse.ArgumentParser(description="混合搜索：向量 + 图谱")
    parser.add_argument("query", nargs="?", help="搜索关键词")
    parser.add_argument("-k", type=int, default=5, help="向量搜索返回数 (default: 5)")
    parser.add_argument("--graph", action="store_true", help="同时搜索图谱")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互式搜索")
    parser.add_argument("--rebuild", action="store_true", help="强制重建向量索引")
    args = parser.parse_args()

    print("=" * 60)
    print("  Hybrid Search: Vector + Knowledge Graph")
    print("=" * 60)

    graph = load_graph() if args.graph else None
    vs = None

    if args.rebuild:
        vs = VectorStore()
        chunks = load_all_chunks()
        if chunks:
            vs.build_index(chunks)
            vs_path = os.path.join(BASE_DIR, "data", "chunks", "vector_index.json")
            vs.save(vs_path)
            print(f"  Rebuilt index: {len(chunks)} chunks\n")
        else:
            print("  No chunks found. Run extraction first.\n")

    def do_search(query):
        nonlocal vs
        results = []

        # 1. 向量搜索
        if vs is None:
            vs_path = os.path.join(BASE_DIR, "data", "chunks", "vector_index.json")
            vs = VectorStore.load(vs_path)
            if vs.chunks is None or len(vs.chunks) == 0:
                vs = build_vector_store()

        if vs.vectors is not None and len(vs.chunks) > 0:
            vector_results = vs.query(query, k=args.k)
            if vector_results:
                results.append(("📄 向量搜索结果 (Chunks)", [
                    (r["chunk"]["source"], r["chunk"]["text"][:200], r["score"])
                    for r in vector_results
                ]))

        # 2. 图谱搜索
        if graph is not None:
            ql = query.lower()
            matched_nodes = []
            for n in graph.nodes():
                if ql in n.lower():
                    matched_nodes.append(n)
                    if len(matched_nodes) >= 10:
                        break

            if matched_nodes:
                node_rows = []
                for n in matched_nodes:
                    attrs = graph.nodes[n]
                    t = attrs.get("types", "")
                    if isinstance(t, set):
                        t = ", ".join(sorted(t))
                    node_rows.append((n, t, graph.degree(n)))
                results.append(("🔗 图谱匹配实体", node_rows))

            # 路径搜索（如果 query 含 "A → B" 格式）
            if "→" in query or ">" in query:
                parts = query.replace(">", "→").split("→")
                if len(parts) == 2:
                    src, dst = parts[0].strip(), parts[1].strip()
                    inferencer = GraphInferencer(graph)
                    paths = inferencer.find_paths(src, dst, max_depth=3)
                    if paths:
                        path_rows = []
                        for p in paths:
                            chain = " → ".join(
                                f"{e['from']} --[{e['relation']}]--> {e['to']}"
                                for e in p["edges"]
                            )
                            path_rows.append((chain,))
                        results.append(("🔗 图谱路径", path_rows))

        return results

    # ---- Interactive mode ----
    if args.interactive:
        print("\nEnter search queries (Ctrl+D to exit)\n")
        while True:
            try:
                q = input("query> ").strip()
                if not q:
                    continue
                results = do_search(q)
                for section_name, rows in results:
                    print(f"\n  {section_name}:")
                    for row in rows[:5]:
                        if len(row) == 3:
                            print(f"    [{row[2]:.3f}] {row[0]} — {row[1][:80]}")
                        elif len(row) == 2:
                            print(f"    {row[0]} ({row[1]})")
                        else:
                            print(f"    {row[0]}")
                if not results:
                    print("  (no results)")
            except (EOFError, KeyboardInterrupt):
                print()
                break
        return

    # ---- Single query mode ----
    if not args.query:
        parser.print_help()
        return

    results = do_search(args.query)
    for section_name, rows in results:
        print(f"\n  {section_name}:")
        for row in rows[:5]:
            if len(row) == 3:
                print(f"    [{row[2]:.3f}] {row[0]} — {row[1][:80]}")
            elif len(row) == 2:
                print(f"    {row[0]} ({row[1]})")
            else:
                print(f"    {row[0]}")
    if not results:
        print("  (no results)")

    print()


if __name__ == "__main__":
    main()
