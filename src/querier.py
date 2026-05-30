import os
import json
import networkx as nx


class GraphQuerier:
    def __init__(self, graph_path=None):
        self.graph = None
        if graph_path:
            self.load_graphml(graph_path)

    def load_graphml(self, filepath):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Graph file not found: {filepath}")
        self.graph = nx.read_graphml(filepath)
        return self.graph

    def set_graph(self, graph):
        self.graph = graph

    def find_entity(self, entity_name):
        if not self.graph.has_node(entity_name):
            return None
        attrs = self.graph.nodes[entity_name]
        return {"name": entity_name, "attributes": attrs}

    def find_entities_by_type(self, entity_type):
        results = []
        for node, attrs in self.graph.nodes(data=True):
            types = attrs.get("types", "")
            if isinstance(types, str):
                types = {types}
            if entity_type in types:
                results.append({"name": node, "attributes": attrs})
        return results

    def find_connections(self, entity_name, depth=2):
        if not self.graph.has_node(entity_name):
            return []
        try:
            neighbors = nx.single_source_shortest_path_length(
                self.graph, entity_name, cutoff=depth
            )
            results = []
            for node, dist in neighbors.items():
                if node == entity_name:
                    continue
                edges = self.graph.edges[node]
                results.append({
                    "entity": node,
                    "distance": dist,
                    "attributes": edges,
                })
            return results
        except nx.NetworkXError:
            return []

    def find_relations(self, subject=None, relation=None, obj=None):
        results = []
        for u, v, attrs in self.graph.edges(data=True):
            edge_relation = attrs.get("relation", "")
            if subject and u != subject:
                continue
            if obj and v != obj:
                continue
            if relation and edge_relation != relation:
                continue
            results.append({
                "subject": u,
                "relation": edge_relation,
                "object": v,
                "confidence": attrs.get("confidence", 0),
                "source_text": attrs.get("source_text", ""),
            })
        return results

    def find_common_connections(self, entity_a, entity_b, max_depth=3):
        if not self.graph.has_node(entity_a) or not self.graph.has_node(entity_b):
            return []
        try:
            paths = list(
                nx.all_simple_paths(self.graph, entity_a, entity_b, cutoff=max_depth)
            )
            results = []
            for path in paths:
                edges = []
                for i in range(len(path) - 1):
                    edge_data = self.graph.edges[path[i], path[i+1]]
                    edges.append({
                        "from": path[i],
                        "to": path[i+1],
                        "relation": edge_data.get("relation", ""),
                    })
                results.append({"path": path, "edges": edges, "length": len(path) - 1})
            return results
        except nx.NetworkXError:
            return []

    def get_all_relation_types(self):
        types = set()
        for _, _, attrs in self.graph.edges(data=True):
            relation = attrs.get("relation", "")
            if relation:
                types.add(relation)
        return sorted(types)

    def get_all_entity_types(self):
        types = set()
        for _, attrs in self.graph.nodes(data=True):
            node_types = attrs.get("types", "")
            if isinstance(node_types, str):
                node_types = {node_types}
            types.update(node_types)
        return sorted(types)

    def get_entity_count_by_type(self):
        counts = {}
        for _, attrs in self.graph.nodes(data=True):
            node_types = attrs.get("types", "")
            if isinstance(node_types, str):
                node_types = {node_types}
            for t in node_types:
                counts[t] = counts.get(t, 0) + 1
        return counts

    def get_relation_count_by_type(self):
        counts = {}
        for _, _, attrs in self.graph.edges(data=True):
            relation = attrs.get("relation", "")
            counts[relation] = counts.get(relation, 0) + 1
        return counts

    def cypher_style_export(self):
        lines = []
        for node, attrs in self.graph.nodes(data=True):
            safe_name = node.replace("'", "\\'")
            types = attrs.get("types", "Entity")
            if isinstance(types, set):
                types = "_".join(types)
            lines.append(f"CREATE (n:{types} {{name: '{safe_name}'}})")

        for u, v, attrs in self.graph.edges(data=True):
            relation = attrs.get("relation", "RELATED_TO")
            safe_u = u.replace("'", "\\'")
            safe_v = v.replace("'", "\\'")
            lines.append(
                f"MATCH (a {{name: '{safe_u}'}}), (b {{name: '{safe_v}'}}) "
                f"CREATE (a)-[:{relation}]->(b)"
            )

        return "\n".join(lines)

    def export_json(self, filepath):
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        data = {
            "nodes": [
                {"id": n, **attrs} for n, attrs in self.graph.nodes(data=True)
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
        return filepath
