#!/usr/bin/env python3
"""独立推理脚本：加载已有图谱，执行推理分析"""

import os
import sys
import json
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.inferencer import GraphInferencer
from src.querier import GraphQuerier


def main():
    parser = argparse.ArgumentParser(description="Run graph inference analysis")
    parser.add_argument(
        "--graph", "-g",
        default=os.path.join(BASE_DIR, "data", "graphs", "knowledge_graph.graphml"),
        help="Path to GraphML file",
    )
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory")
    parser.add_argument("--find-paths", nargs=2, metavar=("SOURCE", "TARGET"), help="Find paths between two entities")
    parser.add_argument("--centrality", action="store_true", help="Compute centrality metrics")
    parser.add_argument("--communities", action="store_true", help="Find communities")
    parser.add_argument("--transitive", action="store_true", help="Find transitive relations")
    parser.add_argument("--insights", action="store_true", help="Run full analysis")
    args = parser.parse_args()

    output_dir = args.output_dir or os.path.join(BASE_DIR, "data", "graphs")
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(args.graph):
        print(f"Error: Graph file not found: {args.graph}")
        print("Run run_extraction.py first to build the graph.")
        sys.exit(1)

    print("=" * 60)
    print("  Graph Inference Engine")
    print("=" * 60)

    querier = GraphQuerier(args.graph)
    inferencer = GraphInferencer(querier.graph)

    print(f"\nLoaded graph: {args.graph}")
    print(f"  Nodes: {querier.graph.number_of_nodes()}")
    print(f"  Edges: {querier.graph.number_of_edges()}")

    if args.find_paths:
        source, target = args.find_paths
        print(f"\nFinding paths: {source} -> {target}")
        paths = inferencer.find_paths(source, target)
        if paths:
            for i, p in enumerate(paths):
                print(f"  Path {i+1}: {' -> '.join(p['path'])}")
        else:
            print("  No paths found")

    if args.centrality or args.insights:
        print("\n[1/3] Computing centrality...")
        centrality = inferencer.compute_centrality()
        cent_path = os.path.join(output_dir, "centrality.json")
        with open(cent_path, "w", encoding="utf-8") as f:
            json.dump(centrality, f, indent=2, ensure_ascii=False)
        print(f"  Top 5 entities by PageRank:")
        for item in centrality[:5]:
            print(f"    - {item['entity']} (PR: {item['pagerank']}, Degree: {item['degree']})")

    if args.communities or args.insights:
        print("\n[2/3] Finding communities...")
        communities = inferencer.find_communities()
        comm_path = os.path.join(output_dir, "communities.json")
        with open(comm_path, "w", encoding="utf-8") as f:
            json.dump(communities, f, indent=2, ensure_ascii=False)
        print(f"  Communities found: {len(communities)}")
        for c in communities:
            print(f"    Community {c['community_id']}: {c['size']} members")

    if args.transitive or args.insights:
        print("\n[3/3] Finding transitive relations...")
        inferred = inferencer.find_transitive_relations()
        inf_path = os.path.join(output_dir, "inferred_triples.json")
        with open(inf_path, "w", encoding="utf-8") as f:
            json.dump(inferred, f, indent=2, ensure_ascii=False)
        print(f"  Inferred triples: {len(inferred)}")

    if args.insights:
        insights = inferencer.get_key_insights()
        insights_path = os.path.join(output_dir, "insights.json")
        with open(insights_path, "w", encoding="utf-8") as f:
            json.dump(insights, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  Insights saved to: {insights_path}")

    print(f"\n{'=' * 60}")
    print("  Done!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
