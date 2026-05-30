import networkx as nx
from collections import defaultdict


class GraphInferencer:
    def __init__(self, graph):
        self.graph = graph

    def find_paths(self, source, target, max_depth=3):
        try:
            paths = list(
                nx.all_simple_paths(self.graph, source, target, cutoff=max_depth)
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
                results.append({"path": path, "edges": edges})
            return results
        except nx.NetworkXError:
            return []

    def find_transitive_relations(self):
        inferred = []
        for node in self.graph.nodes():
            successors = list(nx.descendants(self.graph, node))
            for successor in successors:
                if not self.graph.has_edge(node, successor):
                    paths = list(
                        nx.all_simple_paths(self.graph, node, successor, cutoff=2)
                    )
                    if paths:
                        inferred.append({
                            "subject": node,
                            "relation": "INFLUENCES",
                            "object": successor,
                            "confidence": 0.5,
                            "source": "transitive_inference",
                        })
        return inferred

    def compute_centrality(self):
        try:
            degree = dict(self.graph.degree())
            pagerank = nx.pagerank(self.graph, alpha=0.85)
            betweenness = nx.betweenness_centrality(self.graph)

            results = []
            for node in self.graph.nodes():
                results.append({
                    "entity": node,
                    "degree": degree.get(node, 0),
                    "pagerank": round(pagerank.get(node, 0), 4),
                    "betweenness": round(betweenness.get(node, 0), 4),
                })

            results.sort(key=lambda x: x["pagerank"], reverse=True)
            return results
        except Exception:
            return []

    def find_communities(self):
        try:
            undirected = self.graph.to_undirected()
            communities = list(
                nx.community.greedy_modularity_communities(undirected)
            )
            return [
                {
                    "community_id": i,
                    "members": list(c),
                    "size": len(c),
                }
                for i, c in enumerate(communities)
            ]
        except Exception:
            return []

    def get_key_insights(self):
        centrality = self.compute_centrality()
        communities = self.find_communities()

        top_nodes = centrality[:5] if centrality else []
        return {
            "key_entities": top_nodes,
            "communities": communities,
            "community_count": len(communities),
        }
