#!/bin/bash
# 可视化启动脚本：打开知识图谱文件

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GRAPHS_DIR="$BASE_DIR/data/graphs"

echo "=========================================="
echo "  Knowledge Graph Visualizer"
echo "=========================================="

GRAPHML_FILE="$GRAPHS_DIR/knowledge_graph.graphml"
GEXF_FILE="$GRAPHS_DIR/knowledge_graph.gexf"
JSON_FILE="$GRAPHS_DIR/knowledge_graph.json"

if [ ! -f "$GRAPHML_FILE" ] && [ ! -f "$GEXF_FILE" ]; then
    echo "No graph files found in $GRAPHS_DIR"
    echo "Run scripts/run_extraction.py first to build the graph."
    exit 1
fi

echo ""
echo "Available graph files:"
[ -f "$GRAPHML_FILE" ] && echo "  1. GraphML: $GRAPHML_FILE"
[ -f "$GEXF_FILE" ] && echo "  2. GEXF:    $GEXF_FILE"
[ -f "$JSON_FILE" ] && echo "  3. JSON:    $JSON_FILE"

echo ""
echo "Open with:"
echo "  - Gephi:       File -> Open -> select .graphml or .gexf"
echo "  - yEd:         File -> Open -> select .graphml"
echo "  - Neo4j:       Use apoc.load.graphml() to import"
echo ""

if command -v xdg-open &> /dev/null; then
    if [ -f "$GRAPHML_FILE" ]; then
        echo "Opening GraphML file..."
        xdg-open "$GRAPHML_FILE"
    fi
elif command -v open &> /dev/null; then
    if [ -f "$GRAPHML_FILE" ]; then
        echo "Opening GraphML file..."
        open "$GRAPHML_FILE"
    fi
else
    echo "Auto-open not supported. Please open manually."
fi

echo ""
echo "=========================================="
