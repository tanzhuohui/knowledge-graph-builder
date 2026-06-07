#!/usr/bin/env python3
"""主流程脚本：文档 -> 分块 -> 抽取 -> 对齐 -> 建图 -> 推理 -> 导出
支持增量更新：仅处理新增/修改的文档，复用已有图谱数据。
支持双向同步：从 Wiki Markdown 页面的修改反馈回图谱。
"""

import os
import sys
import json
import glob
import time
import copy

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.chunker import DocumentChunker
from src.extractor import EntityExtractor
from src.resolver import EntityResolver
from src.graph_builder import GraphBuilder
from src.inferencer import GraphInferencer
from src.visualizer import GraphVisualizer
from src.wiki_builder import WikiBuilder
from src.wiki_linter import WikiLinter
from src.wiki_sync import WikiSync
from src.incremental_tracker import IncrementalTracker
from src.vector_store import VectorStore


def _chunk_suffix(filepath):
    """返回 chunk 文件后缀"""
    base = os.path.basename(filepath)
    for ext in (".md", ".txt", ".csv"):
        if base.endswith(ext):
            return base[: -len(ext)] + "_chunks.json"
    return base + "_chunks.json"


def load_existing_graph():
    """尝试从已有图文件加载图谱"""
    graphs_dir = os.path.join(BASE_DIR, "data", "graphs")
    import networkx as nx

    for filename, fmt in [
        ("knowledge_graph.graphml", "graphml"),
        ("knowledge_graph.gexf", "gexf"),
        ("knowledge_graph.json", "json"),
    ]:
        filepath = os.path.join(graphs_dir, filename)
        if os.path.exists(filepath):
            try:
                if fmt == "graphml":
                    G = nx.read_graphml(filepath)
                elif fmt == "gexf":
                    G = nx.read_gexf(filepath)
                else:
                    G = nx.node_link_graph(json.load(open(filepath, encoding="utf-8")), directed=True)

                # 恢复 types 为 set
                for node, attrs in G.nodes(data=True):
                    t = attrs.get("types", "")
                    if isinstance(t, str) and t:
                        attrs["types"] = set(x.strip() for x in t.split(",") if x.strip())
                    elif not isinstance(t, set):
                        attrs["types"] = set()

                return G
            except Exception as e:
                print(f"  Warning: Failed to load {filepath}: {e}")
                continue

    return None


def save_graph(graph, graphs_dir):
    """保存图谱到多种格式"""
    os.makedirs(graphs_dir, exist_ok=True)

    builder = GraphBuilder()
    builder.graph = graph

    graphml_path = os.path.join(graphs_dir, "knowledge_graph.graphml")
    gexf_path = os.path.join(graphs_dir, "knowledge_graph.gexf")
    json_path = os.path.join(graphs_dir, "knowledge_graph.json")

    builder.save_graphml(graphml_path)
    builder.save_gexf(gexf_path)

    import networkx as nx
    json_data = nx.node_link_data(graph)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False, default=str)

    return graphml_path, gexf_path, json_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="知识图谱构建管线")
    parser.add_argument("--full", action="store_true", help="强制全量重建，忽略已有缓存")
    parser.add_argument("--sync-wiki", action="store_true", help="同步 Wiki 页面的修改到图谱（双向同步）")
    parser.add_argument("--wiki-only", action="store_true", help="仅同步 Wiki，跳过文档抽取管线")
    parser.add_argument("--rag", action="store_true", help="启用向量检索增强抽取（RAG上下文补充）")
    args = parser.parse_args()

    print("=" * 60)
    print("  LLM Knowledge Graph Builder")
    print("=" * 60)

    raw_dir = os.path.join(BASE_DIR, "data", "raw")
    chunks_dir = os.path.join(BASE_DIR, "data", "chunks")
    triples_dir = os.path.join(BASE_DIR, "data", "triples")
    graphs_dir = os.path.join(BASE_DIR, "data", "graphs")
    wiki_dir = os.path.join(BASE_DIR, "data", "wiki")

    for d in [chunks_dir, triples_dir, graphs_dir]:
        os.makedirs(d, exist_ok=True)

    # ---- 双向同步（Wiki → Graph）----
    if args.sync_wiki or args.wiki_only:
        print("\n[Sync] Checking wiki modifications → graph...")
        entities_dir = os.path.join(wiki_dir, "entities")
        if os.path.exists(entities_dir):
            existing_graph = load_existing_graph()
            if existing_graph is not None:
                syncer = WikiSync(existing_graph, wiki_dir)
                sync_results = syncer.sync_all(dry_run=False)
                if sync_results:
                    print(f"  Applied {len(sync_results)} wiki change(s)")
                    save_graph(existing_graph, graphs_dir)
                    if args.wiki_only:
                        print("  Wiki sync complete. Exiting (--wiki-only).")
                        return
            else:
                print("  No existing graph to sync into. Skipping wiki sync.")
        else:
            print("  No wiki found. Skipping wiki sync.")

    if args.wiki_only:
        return

    state_path = os.path.join(triples_dir, "incremental_state.json")
    tracker = IncrementalTracker(state_path)

    # 收集所有文档
    md_files = glob.glob(os.path.join(raw_dir, "**/*.md"), recursive=True)
    txt_files = glob.glob(os.path.join(raw_dir, "**/*.txt"), recursive=True)
    csv_files = glob.glob(os.path.join(raw_dir, "**/*.csv"), recursive=True)
    all_files = md_files + txt_files + csv_files

    if not all_files:
        print("  No documents found in data/raw/")
        print("  Place .md or .txt files there and run again.")
        return

    # ---- 增量判断 ----
    new_files, modified_files, deleted_files, unchanged_files = tracker.scan(all_files)

    if args.full or tracker.is_first_run():
        print("\n>>> 全量模式：处理所有文档")
        files_to_process = all_files
        incremental_mode = False
    else:
        incremental_mode = True
        files_to_process = new_files + modified_files

        print("\n>>> 增量模式：")
        for fp in new_files:
            print(f"  [+新增] {os.path.basename(fp)}")
        for fp in modified_files:
            print(f"  [~修改] {os.path.basename(fp)}")
        for abs_fp in deleted_files:
            print(f"  [-删除] {os.path.basename(tracker.state['files'][abs_fp]['path'])}")
        if unchanged_files:
            print(f"  [=不变] {len(unchanged_files)} 个文件")

        if not files_to_process and not deleted_files:
            print("  无文档变更")

    # ---- Step 1: Chunking ----
    print("\n[1/8] Chunking documents...")
    chunker = DocumentChunker()
    new_chunks = []

    for filepath in files_to_process:
        print(f"  Chunking: {os.path.basename(filepath)}")
        chunks = chunker.chunk_file(filepath)
        new_chunks.extend(chunks)

        chunk_path = os.path.join(chunks_dir, _chunk_suffix(filepath))
        with open(chunk_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)

    if incremental_mode and unchanged_files:
        for filepath in unchanged_files:
            chunk_path = os.path.join(chunks_dir, _chunk_suffix(filepath))
            if os.path.exists(chunk_path):
                with open(chunk_path, "r", encoding="utf-8") as f:
                    old_chunks = json.load(f)
                    new_chunks.extend(old_chunks)

    print(f"  Total chunks (active): {len(new_chunks)}")

    # ---- RAG: 构建向量索引（可选）----
    vector_store = None
    if args.rag and new_chunks:
        from src.vector_store import VectorStore
        vs_path = os.path.join(BASE_DIR, "data", "chunks", "vector_index.json")
        vector_store = VectorStore.load(vs_path)
        if vector_store.needs_rebuild(new_chunks):
            print("\n[RAG] Building vector index for chunk semantic search...")
            vector_store = VectorStore()
            vector_store.build_index(new_chunks)
            vector_store.save(vs_path)
            print(f"  [RAG] Vector index saved ({len(new_chunks)} chunks)")
        else:
            print(f"\n[RAG] Using cached vector index ({len(vector_store.chunks)} chunks)")
            vector_store.chunks = new_chunks
    elif args.rag:
        print("\n[RAG] No chunks to index, skipping vector store")

    # ---- Step 2: Extract triples ----
    print("\n[2/8] Extracting entity-relation triples...")

    all_triples = []

    if incremental_mode and not args.full and not tracker.is_first_run():
        existing_path = os.path.join(triples_dir, "all_triples.json")
        if os.path.exists(existing_path):
            with open(existing_path, "r", encoding="utf-8") as f:
                all_triples = json.load(f)
            print(f"  Loaded {len(all_triples)} existing triples")

        # 删除已删除文件对应的三元组
        for abs_fp in deleted_files:
            indices = tracker.get_deleted_triple_indices(abs_fp)
            if indices:
                for idx in sorted(indices, reverse=True):
                    if 0 <= idx < len(all_triples):
                        all_triples.pop(idx)
                print(f"  Removed {len(indices)} triples from deleted file")
            tracker.unregister_file(abs_fp)

        # 删除被修改文件的旧三元组
        for filepath in modified_files:
            abs_fp = os.path.abspath(filepath)
            indices = tracker.get_deleted_triple_indices(abs_fp)
            if indices:
                for idx in sorted(indices, reverse=True):
                    if 0 <= idx < len(all_triples):
                        all_triples.pop(idx)
                print(f"  Removed {len(indices)} old triples from modified file")
            tracker.unregister_file(abs_fp)

        # 仅对新 chunks 做 LLM 抽取
        if new_chunks:
            extractor = EntityExtractor()
            base_idx = len(all_triples)
            new_triples = []

            for i, chunk in enumerate(new_chunks):
                print(f"  Extracting chunk {i+1}/{len(new_chunks)}: {chunk['id']}")
                related_contexts = None
                if vector_store:
                    related_contexts = vector_store.query(chunk["text"], k=3)
                    related_contexts = [rc for rc in related_contexts if rc["chunk"]["id"] != chunk["id"]]
                    if related_contexts:
                        print(f"    → RAG: {len(related_contexts)} similar chunk(s)")
                try:
                    triples = extractor.extract(chunk["text"], chunk["id"], related_contexts)
                    for t in triples:
                        t["_idx"] = base_idx + len(new_triples)
                    new_triples.extend(triples)
                except Exception as e:
                    print(f"  ERROR on chunk {chunk['id']}: {e}")

            all_triples.extend(new_triples)
            print(f"  New triples extracted: {len(new_triples)}")
        else:
            print("  No new chunks to extract")
    else:
        extractor = EntityExtractor()
        for i, chunk in enumerate(new_chunks):
            print(f"  Extracting chunk {i+1}/{len(new_chunks)}: {chunk['id']}")
            related_contexts = None
            if vector_store:
                related_contexts = vector_store.query(chunk["text"], k=3)
                related_contexts = [rc for rc in related_contexts if rc["chunk"]["id"] != chunk["id"]]
                if related_contexts:
                    print(f"    → RAG: {len(related_contexts)} similar chunk(s)")
            try:
                triples = extractor.extract(chunk["text"], chunk["id"], related_contexts)
                all_triples.extend(triples)
            except Exception as e:
                print(f"  ERROR on chunk {chunk['id']}: {e}")

    # 保存全量三元组
    triples_output = os.path.join(triples_dir, "all_triples.json")
    with open(triples_output, "w", encoding="utf-8") as f:
        clean_triples = []
        for t in all_triples:
            ct = {k: v for k, v in t.items() if k != "_idx"}
            clean_triples.append(ct)
        json.dump(clean_triples, f, indent=2, ensure_ascii=False)

    print(f"  Total triples: {len(all_triples)}")

    if not all_triples:
        print("  No triples extracted. Check LLM connectivity and try again.")
        return

    # ---- Step 3: Entity resolution ----
    print("\n[3/8] Resolving entities...")
    resolver = EntityResolver()
    resolved_triples = resolver.resolve(all_triples)

    resolved_output = os.path.join(triples_dir, "resolved_triples.json")
    with open(resolved_output, "w", encoding="utf-8") as f:
        json.dump(resolved_triples, f, indent=2, ensure_ascii=False)
    print(f"  Resolved triples saved")

    # ---- Step 4: Build graph ----
    print("\n[4/8] Building knowledge graph...")
    builder = GraphBuilder()
    builder.build_from_triples(resolved_triples)
    stats = builder.get_stats()
    print(f"  Nodes: {stats['nodes']}, Edges: {stats['edges']}, Density: {stats['density']}")

    graphml_path, gexf_path, json_path = save_graph(builder.graph, graphs_dir)

    # ---- Step 5: Inference ----
    print("\n[5/8] Running graph inference...")
    inferencer = GraphInferencer(builder.graph)
    insights = inferencer.get_key_insights()

    print(f"  Key entities (by PageRank):")
    for item in insights.get("key_entities", [])[:5]:
        print(f"    - {item['entity']} (PageRank: {item['pagerank']})")
    print(f"  Communities found: {insights.get('community_count', 0)}")

    inferred_triples = inferencer.find_transitive_relations()
    inferred_output = os.path.join(triples_dir, "inferred_triples.json")
    with open(inferred_output, "w", encoding="utf-8") as f:
        json.dump(inferred_triples, f, indent=2, ensure_ascii=False)
    print(f"  Inferred triples: {len(inferred_triples)}")

    insights_path = os.path.join(graphs_dir, "insights.json")
    with open(insights_path, "w", encoding="utf-8") as f:
        json.dump(insights, f, indent=2, ensure_ascii=False, default=str)

    # ---- Step 6: Visualization ----
    print("\n[6/8] Exporting visualization files...")
    visualizer = GraphVisualizer(builder.graph)
    visualizer.export_graphml(graphml_path)
    visualizer.export_gexf(gexf_path)
    visualizer.export_json(json_path)

    summary = visualizer.summary()
    print(f"\n  Graph Summary:")
    print(f"    Nodes: {summary['total_nodes']}")
    print(f"    Edges: {summary['total_edges']}")
    print(f"    Density: {summary['density']}")
    print(f"    Connected: {summary['is_connected']}")

    # ---- Step 7: Wiki ----
    print("\n[7/8] Compiling Markdown Knowledge Base...")
    wiki_builder = WikiBuilder(builder.graph, wiki_dir)
    wiki_builder.compile()

    # ---- Step 8: Wiki Lint ----
    print("\n[8/8] Running wiki lint checks...")
    linter = WikiLinter(builder.graph, wiki_dir)
    lint_report = linter.lint()
    linter.save_report()

    # ---- 更新增量状态 ----
    chunk_to_file = {}
    for chunk in new_chunks:
        chunk_to_file[chunk["id"]] = chunk.get("source", "")

    file_triple_indices = {}
    for idx, t in enumerate(all_triples):
        src_chunk = t.get("source_chunk", "")
        src_file = chunk_to_file.get(src_chunk, "")
        if src_file:
            file_triple_indices.setdefault(src_file, []).append(idx)

    target_files = all_files if not incremental_mode else files_to_process
    for filepath in target_files:
        file_chunks = [c for c in new_chunks if c.get("source") == os.path.basename(filepath)]
        chunk_ids = [c["id"] for c in file_chunks]
        triple_indices = file_triple_indices.get(os.path.basename(filepath), [])
        tracker.register_file(filepath, chunk_ids, triple_indices)

    tracker.save()
    mode_label = "增量" if incremental_mode else "全量"
    print(f"\n  [{mode_label}模式] 增量状态已保存")

    print(f"\n{'=' * 60}")
    print("  Done! Output files:")
    print(f"    GraphML: {graphml_path}")
    print(f"    GEXF:    {gexf_path}")
    print(f"    JSON:    {json_path}")
    print(f"    Insights:{insights_path}")
    print(f"    Wiki:    {wiki_dir}/")
    print(f"    Lint:    {wiki_dir}/lint_report.json")
    print(f"  Open GraphML/GEXF in Gephi or Neo4j Browser for visualization.")
    print(f"  Open {wiki_dir}/index.md in Obsidian/VS Code for browsing.")
    print(f"  Run 'python scripts/sync_wiki_to_graph.py' to sync wiki edits back.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
