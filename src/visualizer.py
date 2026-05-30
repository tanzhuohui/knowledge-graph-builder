import networkx as nx
import os
import json


class GraphVisualizer:
    def __init__(self, graph):
        self.graph = graph

    def export_graphml(self, filepath):
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        
        # Fix: GraphML only supports scalar values. Convert sets/lists to strings.
        for _, attrs in self.graph.nodes(data=True):
            if "types" in attrs and isinstance(attrs["types"], (set, list)):
                attrs["types"] = ", ".join(sorted(list(attrs["types"])))
                
        nx.write_graphml(self.graph, filepath)
        print(f"  Exported GraphML: {filepath}")
        return filepath

    def export_gexf(self, filepath):
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        nx.write_gexf(self.graph, filepath)
        print(f"  Exported GEXF: {filepath}")
        return filepath

    def export_json(self, filepath):
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        data = {
            "nodes": [
                {"id": n, **attrs}
                for n, attrs in self.graph.nodes(data=True)
            ],
            "edges": [
                {"source": u, "target": v, **attrs}
                for u, v, attrs in self.graph.edges(data=True)
            ],
        }
        for node in data["nodes"]:
            if "types" in node and isinstance(node["types"], set):
                node["types"] = list(node["types"])
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  Exported JSON: {filepath}")
        return filepath

    def summary(self):
        stats = {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "density": round(nx.density(self.graph), 4),
            "is_connected": nx.is_weakly_connected(self.graph) if self.graph.number_of_nodes() > 0 else False,
        }

        if self.graph.number_of_nodes() > 0:
            degrees = [d for _, d in self.graph.degree()]
            stats["avg_degree"] = round(sum(degrees) / len(degrees), 2)
            stats["max_degree"] = max(degrees)
            stats["min_degree"] = min(degrees)

        return stats
