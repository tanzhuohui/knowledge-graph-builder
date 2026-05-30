import networkx as nx
import json
import os


class GraphBuilder:
    def __init__(self):
        self.graph = nx.DiGraph()

    def add_triples(self, triples):
        for triple in triples:
            subject = triple.get("subject", "").strip()
            obj = triple.get("object", "").strip()
            relation = triple.get("relation", "RELATED_TO").strip()

            if not subject or not obj:
                continue

            edge_key = (subject, obj, relation)
            if not self.graph.has_edge(subject, obj):
                self.graph.add_edge(
                    subject,
                    obj,
                    relation=relation,
                    confidence=triple.get("confidence", 0.0),
                    source_text=triple.get("source_text", ""),
                    source_chunk=triple.get("source_chunk", ""),
                )
            else:
                existing_conf = self.graph.edges[subject, obj].get("confidence", 0)
                new_conf = triple.get("confidence", 0)
                if new_conf > existing_conf:
                    self.graph.edges[subject, obj].update({
                        "relation": relation,
                        "confidence": new_conf,
                        "source_text": triple.get("source_text", ""),
                        "source_chunk": triple.get("source_chunk", ""),
                    })

    def add_node_attrs(self, entity_name, entity_type):
        if self.graph.has_node(entity_name):
            current_types = self.graph.nodes[entity_name].get("types", set())
            current_types.add(entity_type)
            self.graph.nodes[entity_name]["types"] = current_types
        else:
            self.graph.add_node(entity_name, types={entity_type})

    def build_from_triples(self, triples):
        for triple in triples:
            self.add_triples([triple])
            self.add_node_attrs(triple.get("subject", ""), triple.get("subject_type", ""))
            self.add_node_attrs(triple.get("object", ""), triple.get("object_type", ""))
        return self.graph

    def get_stats(self):
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "density": round(nx.density(self.graph), 4),
        }

    def save_graphml(self, filepath):
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        
        # Fix: GraphML only supports scalar values. Convert sets/lists to strings.
        for node, attrs in self.graph.nodes(data=True):
            if "types" in attrs and isinstance(attrs["types"], (set, list)):
                attrs["types"] = ", ".join(sorted(list(attrs["types"])))
        
        nx.write_graphml(self.graph, filepath)
        print(f"  Saved GraphML: {filepath}")

    def save_gexf(self, filepath):
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        nx.write_gexf(self.graph, filepath)
        print(f"  Saved GEXF: {filepath}")

    def get_node_list(self):
        return list(self.graph.nodes(data=True))

    def get_edge_list(self):
        return list(self.graph.edges(data=True))
