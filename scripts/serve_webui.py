"""Knowledge Graph Web UI — 图谱浏览与编辑界面"""

import os
import re
import json
import sys
import networkx as nx
from flask import Flask, jsonify, request, render_template_string, send_from_directory


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

GRAPHS_DIR = os.path.join(BASE_DIR, "data", "graphs")
WIKI_DIR = os.path.join(BASE_DIR, "data", "wiki")
ENTITIES_DIR = os.path.join(WIKI_DIR, "entities")
CHUNKS_DIR = os.path.join(BASE_DIR, "data", "chunks")


def load_graph():
    """加载图谱"""
    gml = os.path.join(GRAPHS_DIR, "knowledge_graph.graphml")
    js = os.path.join(GRAPHS_DIR, "knowledge_graph.json")

    if os.path.exists(gml):
        try:
            G = nx.read_graphml(gml)
            for n, attrs in G.nodes(data=True):
                t = attrs.get("types", "")
                if isinstance(t, str) and t:
                    attrs["types"] = set(x.strip() for x in t.split(",") if x.strip())
                elif not isinstance(t, set):
                    attrs["types"] = set()
            return G
        except Exception as e:
            print(f"Read graphml failed: {e}")

    if os.path.exists(js):
        try:
            return nx.node_link_graph(json.load(open(js)), directed=True)
        except Exception as e:
            print(f"Read json failed: {e}")

    return nx.DiGraph()


def load_insights():
    p = os.path.join(GRAPHS_DIR, "insights.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {"key_entities": [], "communities": [], "community_count": 0}


def load_wiki_entity(name):
    safe = re.sub(r'[^\w\u4e00-\u9fff\s-]', '', name)
    safe = re.sub(r'\s+', '_', safe.strip())
    for fname in os.listdir(ENTITIES_DIR):
        if fname.startswith(safe) and fname.endswith(".md"):
            path = os.path.join(ENTITIES_DIR, fname)
            with open(path, encoding="utf-8") as f:
                return f.read()
    return None


def stats(graph):
    n = graph.number_of_nodes()
    e = graph.number_of_edges()
    d = round(nx.density(graph), 4) if n > 0 else 0
    degs = [d for _, d in graph.degree()] if n > 0 else []
    return {
        "nodes": n,
        "edges": e,
        "density": d,
        "avg_degree": round(sum(degs) / len(degs), 2) if degs else 0,
        "max_degree": max(degs) if degs else 0,
    }


def save_graph(G):
    """保存图谱到文件"""
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    for n, attrs in G.nodes(data=True):
        t = attrs.get("types", set())
        if isinstance(t, set):
            attrs["types"] = ", ".join(sorted(t)) if t else ""
    gml = os.path.join(GRAPHS_DIR, "knowledge_graph.graphml")
    nx.write_graphml(G, gml)

    for n, attrs in G.nodes(data=True):
        t = attrs.get("types", "")
        if isinstance(t, str) and t:
            attrs["types"] = set(x.strip() for x in t.split(",") if x.strip())

    js = os.path.join(GRAPHS_DIR, "knowledge_graph.json")
    data = {
        "nodes": [{"id": n, **{k: list(v) if isinstance(v, set) else v for k, v in attrs.items()}}
                   for n, attrs in G.nodes(data=True)],
        "edges": [{"source": u, "target": v, **attrs} for u, v, attrs in G.edges(data=True)],
    }
    with open(js, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def create_app():
    from src.wiki_sync import WikiSync
    from src.vector_store import VectorStore

    G = load_graph()
    ins = load_insights()
    st = stats(G)
    all_entities = sorted(G.nodes()) if G.nodes() else []
    all_relations = sorted(set(d.get("relation", "") for _, _, d in G.edges(data=True)))

    ws = WikiSync(G, WIKI_DIR)

    app = Flask(__name__)

    # ---- Routes ----

    @app.route("/")
    def index():
        return render_template_string(INDEX_HTML)

    @app.route("/api/stats")
    def api_stats():
        return jsonify(st)

    @app.route("/api/insights")
    def api_insights():
        return jsonify(ins)

    @app.route("/api/entities")
    def api_entities():
        q = request.args.get("q", "").strip().lower()
        page = int(request.args.get("page", 1))
        per = int(request.args.get("per", 50))
        type_filter = request.args.get("type", "").strip()

        items = []
        for n in all_entities:
            if q and q not in n.lower():
                continue
            nd = G.nodes[n]
            t = nd.get("types", set())
            if isinstance(t, set):
                t = ", ".join(sorted(t)) if t else ""
            else:
                t = str(t)
            if type_filter and type_filter not in t:
                continue
            items.append({
                "name": n,
                "type": t,
                "out_degree": G.out_degree(n),
                "in_degree": G.in_degree(n),
                "total_degree": G.degree(n),
            })

        items.sort(key=lambda x: x["total_degree"], reverse=True)
        total = len(items)
        start = (page - 1) * per
        return jsonify({"entities": items[start:start + per], "total": total, "page": page, "per": per})

    @app.route("/api/entity/<path:name>")
    def api_entity(name):
        if name not in G:
            return jsonify({"error": "Entity not found"}), 404

        nd = G.nodes[name]
        t = nd.get("types", set())
        if isinstance(t, set):
            t = ", ".join(sorted(t)) if t else "ENTITY"

        outgoing = []
        for s in G.successors(name):
            e = G.edges[name, s]
            outgoing.append({
                "relation": e.get("relation", "RELATED_TO"),
                "target": s,
                "confidence": e.get("confidence", 0),
                "source_text": e.get("source_text", ""),
                "source_chunk": e.get("source_chunk", ""),
            })
        outgoing.sort(key=lambda x: -x["confidence"])

        incoming = []
        for p in G.predecessors(name):
            e = G.edges[p, name]
            incoming.append({
                "relation": e.get("relation", "RELATED_TO"),
                "source": p,
                "confidence": e.get("confidence", 0),
                "source_text": e.get("source_text", ""),
                "source_chunk": e.get("source_chunk", ""),
            })
        incoming.sort(key=lambda x: -x["confidence"])

        wiki = load_wiki_entity(name)

        return jsonify({
            "name": name,
            "type": t,
            "outgoing": outgoing,
            "incoming": incoming,
            "degree": G.degree(name),
            "wiki_content": wiki,
        })

    @app.route("/api/entity/<path:name>/update", methods=["POST"])
    def api_update_entity(name):
        data = request.get_json(force=True)
        if name not in G:
            G.add_node(name, types=set())

        if "type" in data and G.has_node(name):
            G.nodes[name]["types"] = {data["type"]}

        if "outgoing" in data:
            for s in list(G.successors(name)):
                G.remove_edge(name, s)
            for edge in data["outgoing"]:
                t = edge.get("target", "").strip()
                if not t:
                    continue
                if not G.has_node(t):
                    G.add_node(t, types=set())
                G.add_edge(name, t,
                           relation=edge.get("relation", "RELATED_TO"),
                           confidence=edge.get("confidence", 0),
                           wiki_updated=True,
                           source_text="",
                           source_chunk="")

        save_graph(G)
        return jsonify({"ok": True})

    @app.route("/api/entity/<path:name>/delete", methods=["POST"])
    def api_delete_entity(name):
        if name in G:
            G.remove_node(name)
            save_graph(G)
            return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    @app.route("/api/relations")
    def api_relations():
        return jsonify(sorted(all_relations))

    @app.route("/api/graph-data")
    def api_graph_data():
        nodes_data = []
        for n, attrs in G.nodes(data=True):
            t = attrs.get("types", set())
            if isinstance(t, set):
                t = ", ".join(sorted(t)) if t else "ENTITY"
            else:
                t = str(t) or "ENTITY"
            sz = 5 + G.degree(n) * 2
            nodes_data.append({"id": n, "type": t, "size": min(sz, 40)})

        edges_data = []
        for u, v, attrs in G.edges(data=True):
            edges_data.append({
                "source": u,
                "target": v,
                "relation": attrs.get("relation", "RELATED_TO"),
            })

        return jsonify({"nodes": nodes_data, "edges": edges_data})

    # ---- RAG Search ----
    @app.route("/api/rag-search")
    def api_rag_search():
        q = request.args.get("q", "").strip()
        k = int(request.args.get("k", 5))
        if not q:
            return jsonify({"error": "missing q"}), 400

        vs_path = os.path.join(BASE_DIR, "data", "chunks", "vector_index.json")
        vs = VectorStore.load(vs_path)

        vector_results = []
        if vs.vectors is not None and len(vs.chunks) > 0:
            hits = vs.query(q, k=k)
            for r in hits:
                vector_results.append({
                    "source": r["chunk"].get("source", ""),
                    "text": r["chunk"]["text"][:300],
                    "score": r["score"],
                })

        graph_results = []
        ql = q.lower()
        for n in G.nodes():
            if ql in n.lower():
                nd = G.nodes[n]
                t = nd.get("types", set())
                if isinstance(t, set):
                    t = ", ".join(sorted(t)) if t else "ENTITY"
                graph_results.append({
                    "name": n,
                    "type": t,
                    "degree": G.degree(n),
                })
                if len(graph_results) >= 10:
                    break

        return jsonify({
            "vector": vector_results,
            "graph": graph_results,
        })

    @app.route("/api/entity/<path:name>/sync-wiki", methods=["POST"])
    def api_sync_wiki(name):
        if name not in G:
            return jsonify({"error": "not found"}), 404

        entities_dir = os.path.join(WIKI_DIR, "entities")
        safe = re.sub(r'[^\w\u4e00-\u9fff\s-]', '', name)
        safe = re.sub(r'\s+', '_', safe.strip())
        fp = None
        for fname in os.listdir(entities_dir):
            if fname.startswith(safe) and fname.endswith(".md"):
                fp = os.path.join(entities_dir, fname)
                break

        if not fp:
            return jsonify({"error": "Wiki page not found"}), 404

        try:
            parsed = ws.parse_entity_page(fp)
            changes = ws.diff_entity(name, filepath=fp)
            if changes and ws._has_changes(changes):
                result = ws.apply_changes(changes, dry_run=False)
                save_graph(G)
                return jsonify({"ok": True, "actions": result["actions"]})
            return jsonify({"ok": True, "actions": []})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Knowledge Graph Viewer</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; }
.app { display: flex; height: 100vh; }
.sidebar { width: 320px; background: #fff; border-right: 1px solid #ddd; display: flex; flex-direction: column; overflow: hidden; }
.sidebar h2 { padding: 16px 16px 8px; font-size: 14px; color: #666; text-transform: uppercase; letter-spacing: 1px; }
.search-box { padding: 8px 16px; }
.search-box input { width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; outline: none; }
.search-box input:focus { border-color: #4a90d9; }
.entity-list { flex: 1; overflow-y: auto; }
.entity-item { padding: 8px 16px; cursor: pointer; border-bottom: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center; }
.entity-item:hover { background: #f0f6ff; }
.entity-item.active { background: #e0eeff; }
.entity-name { font-size: 14px; }
.entity-type { font-size: 11px; color: #999; }
.entity-degree { font-size: 11px; color: #888; background: #f0f0f0; padding: 2px 6px; border-radius: 4px; }
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.tabs { display: flex; background: #fff; border-bottom: 1px solid #ddd; }
.tab { padding: 10px 24px; cursor: pointer; font-size: 13px; color: #666; border-bottom: 2px solid transparent; }
.tab.active { color: #4a90d9; border-bottom-color: #4a90d9; }
.tab:hover { background: #fafafa; }
.content { flex: 1; overflow-y: auto; padding: 20px; }
.dashboard { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px,1fr)); gap: 16px; margin-bottom: 24px; }
.stat-card { background: #fff; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.stat-card h3 { font-size: 12px; color: #999; margin-bottom: 4px; }
.stat-card .value { font-size: 28px; font-weight: 700; }
.detail { display: none; }
.detail.active { display: block; }
.detail h1 { font-size: 22px; margin-bottom: 4px; }
.detail .type-badge { display: inline-block; background: #e0eeff; color: #4a90d9; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-bottom: 16px; }
.detail .wiki-preview { background: #f9f9f9; border: 1px solid #eee; border-radius: 6px; padding: 12px; margin-bottom: 16px; font-size: 13px; max-height: 200px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; }
.relation-table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
.relation-table th { text-align: left; font-size: 12px; color: #999; padding: 6px 8px; border-bottom: 2px solid #eee; }
.relation-table td { padding: 6px 8px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.relation-table tr:hover { background: #fafafa; }
.edit-btn { color: #4a90d9; cursor: pointer; font-size: 12px; padding: 2px 8px; border: 1px solid #4a90d9; border-radius: 4px; background: none; }
.edit-btn:hover { background: #4a90d9; color: #fff; }
.save-btn { background: #4a90d9; color: #fff; border: none; padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.save-btn:hover { background: #357abd; }
.delete-btn { color: #d94a4a; cursor: pointer; font-size: 12px; padding: 2px 8px; border: 1px solid #d94a4a; border-radius: 4px; background: none; }
.delete-btn:hover { background: #d94a4a; color: #fff; }
.add-row { margin: 8px 0; }
.add-row select, .add-row input { padding: 4px 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; margin-right: 4px; }
.graph-viz { display: none; }
.graph-viz.active { display: block; }
#graph-canvas { width: 100%; height: calc(100vh - 50px); background: #fff; }
.sync-btn { color: #6b6; cursor: pointer; font-size: 12px; padding: 2px 8px; border: 1px solid #6b6; border-radius: 4px; background: none; margin-left: 8px; }
.sync-btn:hover { background: #6b6; color: #fff; }
.loading { text-align: center; padding: 40px; color: #999; }
.error { color: #d94a4a; padding: 12px; }
</style>
</head>
<body>
<div class="app">
  <div class="sidebar">
    <h2>🔍 实体搜索</h2>
    <div class="search-box"><input id="search" placeholder="搜索实体..." oninput="debounceSearch()"></div>
    <div id="type-filter" style="padding:4px 16px 8px">
      <select onchange="loadEntities(1)" style="width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;font-size:12px">
        <option value="">所有类型</option>
      </select>
    </div>
    <div id="pagination" style="padding:4px 16px 8px;display:flex;gap:4px;font-size:12px"></div>
    <div class="entity-list" id="entity-list"><div class="loading">加载中...</div></div>
  </div>
  <div class="main">
    <div class="tabs">
      <div class="tab active" onclick="switchTab('dashboard',this)">📊 概览</div>
      <div class="tab" onclick="switchTab('detail',this)">📄 详情 / 编辑</div>
      <div class="tab" onclick="switchTab('graph',this)">🔗 图谱</div>
      <div class="tab" onclick="switchTab('rag',this)">🔎 混合搜索</div>
    </div>
    <div class="content">
      <div id="dashboard" class="dashboard active"></div>
      <div id="detail" class="detail"><div class="loading">选择一个实体查看详情</div></div>
      <div id="graph" class="graph-viz"><div id="graph-canvas"></div></div>
      <div id="rag" class="detail"></div>
    </div>
  </div>
</div>
<script>
let state = { entity: null, editing: false };

function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('#dashboard,#detail,#graph').forEach(d => d.classList.remove('active'));
  document.getElementById(name).classList.add('active');
  if (name === 'graph') setTimeout(drawGraph, 100);
}

// ---- Dashboard ----
fetch('/api/stats').then(r=>r.json()).then(s => {
  const cards = [
    {h:'实体节点',v:s.nodes},{h:'关系边',v:s.edges},{h:'密度',v:s.density},{h:'平均度数',v:s.avg_degree}
  ];
  document.getElementById('dashboard').innerHTML = cards.map(c =>
    `<div class="stat-card"><h3>${c.h}</h3><div class="value">${c.v}</div></div>`
  ).join('');
});

// ---- Entity list ----
let currentPage = 1;
let typeSet = new Set();

function debounceSearch() {
  clearTimeout(window._st);
  window._st = setTimeout(() => loadEntities(1), 200);
}

function loadEntities(page) {
  currentPage = page;
  const q = document.getElementById('search').value;
  const t = document.querySelector('#type-filter select').value;
  fetch(`/api/entities?q=${encodeURIComponent(q)}&page=${page}&per=50&type=${encodeURIComponent(t)}`)
    .then(r=>r.json()).then(d => {
      const list = document.getElementById('entity-list');
      if (d.entities.length === 0) {
        list.innerHTML = '<div style="padding:16px;color:#999;text-align:center">无匹配实体</div>';
      } else {
        list.innerHTML = d.entities.map(e =>
          `<div class="entity-item ${state.entity===e.name?'active':''}" onclick="selectEntity('${escapeStr(e.name)}')">
            <div><div class="entity-name">${escapeHtml(e.name)}</div><div class="entity-type">${e.type||'ENTITY'}</div></div>
            <div class="entity-degree">${e.out_degree}→ ${e.in_degree}←</div>
          </div>`
        ).join('');
      }
      d.entities.forEach(e => { if (e.type) e.type.split(', ').forEach(t => typeSet.add(t)); });
      const sel = document.querySelector('#type-filter select');
      const cur = sel.value;
      sel.innerHTML = '<option value="">所有类型</option>' +
        [...typeSet].sort().map(t => `<option value="${t}" ${t===cur?'selected':''}>${t}</option>`).join('');

      const totalPages = Math.ceil(d.total / d.per);
      const pg = document.getElementById('pagination');
      pg.innerHTML = `<span>共${d.total}个</span>`;
      if (totalPages > 1) {
        for (let i = Math.max(1, page-2); i <= Math.min(totalPages, page+2); i++) {
          pg.innerHTML += `<button onclick="loadEntities(${i})" style="padding:2px 8px;${i===page?'background:#4a90d9;color:#fff':''}">${i}</button>`;
        }
      }
    });
}

function selectEntity(name) {
  state.entity = name;
  state.editing = false;
  switchTab('detail', document.querySelector('.tab:nth-child(2)'));
  document.querySelectorAll('.entity-item').forEach(e => e.classList.remove('active'));
  const items = document.querySelectorAll('.entity-item');
  for (const item of items) {
    if (item.querySelector('.entity-name').textContent === name) {
      item.classList.add('active'); break;
    }
  }
  loadDetail(name);
}

function loadDetail(name) {
  const el = document.getElementById('detail');
  el.innerHTML = '<div class="loading">加载中...</div>';
  el.classList.add('active');

  fetch(`/api/entity/${encodeURIComponent(name)}`).then(r=>r.json()).then(d => {
    if (d.error) { el.innerHTML = `<div class="error">${d.error}</div>`; return; }

    const hasWiki = d.wiki_content && d.wiki_content.length > 20;
    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:start">
        <div>
          <h1>${escapeHtml(d.name)}</h1>
          <div class="type-badge" id="entity-type-badge">${escapeHtml(d.type)}</div>
        </div>
        <div>
          ${hasWiki ? `<button class="sync-btn" onclick="syncWiki('${escapeStr(d.name)}')">🔄 同步Wiki</button>` : ''}
          <button class="edit-btn" onclick="toggleEdit()">✏️ ${state.editing?'取消':'编辑'}</button>
          <button class="delete-btn" onclick="deleteEntity('${escapeStr(d.name)}')" style="margin-left:4px">🗑 删除</button>
        </div>
      </div>
      ${hasWiki ? `<div class="wiki-preview">${escapeHtml(d.wiki_content)}</div>` : ''}
      <div id="detail-body">${state.editing ? renderEditForm(d) : renderDetailView(d)}</div>
    `;
  });
}

function renderDetailView(d) {
  const outRows = d.outgoing.map(e =>
    `<tr><td><b>${escapeHtml(e.relation)}</b></td><td>→ <a href="#" onclick="selectEntity('${escapeStr(e.target)}');return false">${escapeHtml(e.target)}</a></td><td>${e.confidence.toFixed(2)}</td></tr>`
  ).join('');
  const inRows = d.incoming.map(e =>
    `<tr><td><b>${escapeHtml(e.relation)}</b></td><td>← <a href="#" onclick="selectEntity('${escapeStr(e.source)}');return false">${escapeHtml(e.source)}</a></td><td>${e.confidence.toFixed(2)}</td></tr>`
  ).join('');
  return `
    <h3>出向关系 (${d.outgoing.length})</h3>
    <table class="relation-table"><tr><th>关系</th><th>目标</th><th>置信度</th></tr>${outRows||'<tr><td colspan="3" style="color:#999">无</td></tr>'}</table>
    <h3>入向关系 (${d.incoming.length})</h3>
    <table class="relation-table"><tr><th>关系</th><th>来源</th><th>置信度</th></tr>${inRows||'<tr><td colspan="3" style="color:#999">无</td></tr>'}</table>
  `;
}

function toggleEdit() {
  state.editing = !state.editing;
  if (state.entity) loadDetail(state.entity);
}

function renderEditForm(d) {
  return `
    <div style="margin-bottom:12px">
      <label style="font-size:13px;color:#666">实体类型: </label>
      <input id="edit-type" value="${escapeHtml(d.type)}" style="padding:4px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px">
    </div>
    <h3>出向关系</h3>
    <table class="relation-table" id="edit-outgoing">
      <tr><th>关系</th><th>目标实体</th><th>置信度</th><th></th></tr>
    </table>
    <div class="add-row">
      <select id="new-out-rel" style="width:120px"></select>
      <input id="new-out-target" placeholder="目标实体" style="width:180px">
      <input id="new-out-conf" type="number" step="0.01" min="0" max="1" value="0.9" style="width:60px">
      <button class="edit-btn" onclick="addOutgoingRow()">+ 添加</button>
    </div>
    <h3>入向关系</h3>
    <table class="relation-table" id="edit-incoming">
      <tr><th>关系</th><th>来源实体</th><th>置信度</th><th></th></tr>
    </table>
    <div class="add-row">
      <select id="new-in-rel" style="width:120px"></select>
      <input id="new-in-source" placeholder="来源实体" style="width:180px">
      <input id="new-in-conf" type="number" step="0.01" min="0" max="1" value="0.9" style="width:60px">
      <button class="edit-btn" onclick="addIncomingRow()">+ 添加</button>
    </div>
    <div style="margin-top:16px">
      <button class="save-btn" onclick="saveEntity()">💾 保存</button>
    </div>
    <script>initEditForm(${JSON.stringify(d)})<\/script>
  `;
}

function initEditForm(d) {
  fetch('/api/relations').then(r=>r.json()).then(rels => {
    const opts = rels.map(r => `<option value="${r}">${r}</option>`).join('');
    document.querySelectorAll('#edit-outgoing ~ .add-row select, #edit-incoming ~ .add-row select').forEach(s => s.innerHTML = opts);
    document.getElementById('new-out-rel').innerHTML = opts;
    document.getElementById('new-in-rel').innerHTML = opts;

    const outTbl = document.getElementById('edit-outgoing');
    d.outgoing.forEach(e => {
      const row = outTbl.insertRow();
      row.innerHTML = `<td><select class="edit-out-rel">${opts.replace(`value="${e.relation}"`,`value="${e.relation}" selected`)}</select></td>
        <td><input class="edit-out-target" value="${escapeHtml(e.target)}"></td>
        <td><input class="edit-out-conf" type="number" step="0.01" min="0" max="1" value="${e.confidence}" style="width:60px"></td>
        <td><button class="delete-btn" onclick="this.closest('tr').remove()">✕</button></td>`;
    });
    const inTbl = document.getElementById('edit-incoming');
    d.incoming.forEach(e => {
      const row = inTbl.insertRow();
      row.innerHTML = `<td><select class="edit-in-rel">${opts.replace(`value="${e.relation}"`,`value="${e.relation}" selected`)}</select></td>
        <td><input class="edit-in-source" value="${escapeHtml(e.source)}"></td>
        <td><input class="edit-in-conf" type="number" step="0.01" min="0" max="1" value="${e.confidence}" style="width:60px"></td>
        <td><button class="delete-btn" onclick="this.closest('tr').remove()">✕</button></td>`;
    });
  });
}

function addOutgoingRow() {
  const tbl = document.getElementById('edit-outgoing');
  const rel = document.getElementById('new-out-rel').value;
  const target = document.getElementById('new-out-target').value;
  const conf = document.getElementById('new-out-conf').value;
  if (!target) return;
  const opts = document.getElementById('new-out-rel').innerHTML;
  const row = tbl.insertRow();
  row.innerHTML = `<td><select class="edit-out-rel">${opts.replace(`value="${rel}"`,`value="${rel}" selected`)}</select></td>
    <td><input class="edit-out-target" value="${escapeHtml(target)}"></td>
    <td><input class="edit-out-conf" type="number" step="0.01" min="0" max="1" value="${conf}" style="width:60px"></td>
    <td><button class="delete-btn" onclick="this.closest('tr').remove()">✕</button></td>`;
  document.getElementById('new-out-target').value = '';
}

function addIncomingRow() {
  const tbl = document.getElementById('edit-incoming');
  const rel = document.getElementById('new-in-rel').value;
  const source = document.getElementById('new-in-source').value;
  const conf = document.getElementById('new-in-conf').value;
  if (!source) return;
  const opts = document.getElementById('new-in-rel').innerHTML;
  const row = tbl.insertRow();
  row.innerHTML = `<td><select class="edit-in-rel">${opts.replace(`value="${rel}"`,`value="${rel}" selected`)}</select></td>
    <td><input class="edit-in-source" value="${escapeHtml(source)}"></td>
    <td><input class="edit-in-conf" type="number" step="0.01" min="0" max="1" value="${conf}" style="width:60px"></td>
    <td><button class="delete-btn" onclick="this.closest('tr').remove()">✕</button></td>`;
  document.getElementById('new-in-source').value = '';
}

function saveEntity() {
  const name = state.entity;
  const payload = {
    type: document.getElementById('edit-type').value,
    outgoing: [],
    incoming: [],
  };

  document.querySelectorAll('#edit-outgoing tr:not(:first-child)').forEach(row => {
    const rel = row.querySelector('.edit-out-rel')?.value;
    const target = row.querySelector('.edit-out-target')?.value;
    const conf = parseFloat(row.querySelector('.edit-out-conf')?.value) || 0.5;
    if (target) payload.outgoing.push({relation: rel, target, confidence: conf});
  });
  document.querySelectorAll('#edit-incoming tr:not(:first-child)').forEach(row => {
    const rel = row.querySelector('.edit-in-rel')?.value;
    const source = row.querySelector('.edit-in-source')?.value;
    const conf = parseFloat(row.querySelector('.edit-in-conf')?.value) || 0.5;
    if (source) payload.incoming.push({relation: rel, source, confidence: conf});
  });

  fetch(`/api/entity/${encodeURIComponent(name)}/update`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  }).then(r=>r.json()).then(() => {
    state.editing = false;
    loadDetail(name);
    loadEntities(currentPage);
  });
}

function deleteEntity(name) {
  if (!confirm(`确定删除实体 "${name}" 及其所有关系？`)) return;
  fetch(`/api/entity/${encodeURIComponent(name)}/delete`, {method:'POST'})
    .then(r=>r.json()).then(() => {
      state.entity = null;
      document.getElementById('detail').innerHTML = '<div class="loading">实体已删除</div>';
      loadEntities(currentPage);
    });
}

function syncWiki(name) {
  fetch(`/api/entity/${encodeURIComponent(name)}/sync-wiki`, {method:'POST'})
    .then(r=>r.json()).then(d => {
      if (d.ok) {
        alert(`同步完成: ${d.actions.join('\\n') || '无变更'}`);
        loadDetail(name);
        loadEntities(currentPage);
      } else { alert('同步失败: ' + (d.error||'未知错误')); }
    });
}

// ---- Graph Viz ----
function drawGraph() {
  const el = document.getElementById('graph-canvas');
  el.innerHTML = '';

  fetch('/api/graph-data').then(r=>r.json()).then(data => {
    if (!data.nodes.length) { el.innerHTML = '<div class="loading">图谱为空</div>'; return; }

    const w = el.clientWidth || 900;
    const h = el.clientHeight || 600;

    const svg = d3.select(el).append('svg').attr('width', w).attr('height', h)
      .call(d3.zoom().on('zoom', (e) => g.attr('transform', e.transform)));

    const g = svg.append('g');

    const nodes = data.nodes.map(n => ({...n}));
    const edges = data.edges.map(e => ({source: e.source, target: e.target, relation: e.relation}));

    const color = d3.scaleOrdinal(d3.schemeCategory10);

    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(100))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(w/2, h/2))
      .force('collision', d3.forceCollide().radius(d => d.size + 10));

    const link = g.append('g').selectAll('line').data(edges).join('line')
      .attr('stroke', '#ccc').attr('stroke-width', 1).attr('stroke-opacity', 0.6);

    const node = g.append('g').selectAll('circle').data(nodes).join('circle')
      .attr('r', d => Math.max(4, d.size / 2))
      .attr('fill', d => color(d.type))
      .attr('stroke', '#fff').attr('stroke-width', 1.5)
      .call(d3.drag()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      )
      .on('click', (e, d) => { selectEntity(d.id); })
      .append('title').text(d => d.id);

    const label = g.append('g').selectAll('text').data(nodes).join('text')
      .text(d => d.id.length > 15 ? d.id.slice(0, 15) + '...' : d.id)
      .attr('font-size', '10px').attr('dx', 8).attr('dy', 4);

    sim.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('cx', d => d.x).attr('cy', d => d.y);
      label.attr('x', d => d.x).attr('y', d => d.y);
    });
  });
}

// ---- RAG Search ----
function switchTabRag() {
  const el = document.getElementById('rag');
  if (el.innerHTML.trim() === '') {
    el.innerHTML = `
      <div style="margin-bottom:16px">
        <div style="display:flex;gap:8px">
          <input id="rag-query" placeholder="输入搜索关键词..." style="flex:1;padding:10px 14px;border:1px solid #ddd;border-radius:6px;font-size:14px;outline:none"
            onkeydown="if(event.key==='Enter') doRagSearch()">
          <button class="save-btn" onclick="doRagSearch()" style="padding:10px 20px">搜索</button>
        </div>
        <div style="margin-top:8px;display:flex;gap:8px;font-size:12px;color:#666">
          <label><input type="checkbox" id="rag-vector" checked> 向量搜索</label>
          <label><input type="checkbox" id="rag-graph" checked> 图谱搜索</label>
        </div>
      </div>
      <div id="rag-results"></div>
    `;
  }
}

let ragTimeout = null;
function doRagSearch() {
  const q = document.getElementById('rag-query').value.trim();
  if (!q) return;
  const res = document.getElementById('rag-results');
  res.innerHTML = '<div class="loading">搜索中...</div>';

  fetch('/api/rag-search?q=' + encodeURIComponent(q) + '&k=8')
    .then(r => r.json()).then(d => {
      let html = '';
      if (d.vector && d.vector.length) {
        html += '<h3>📄 向量搜索结果（文档分块）</h3>';
        d.vector.forEach(r => {
          html += `<div style="background:#fff;border:1px solid #eee;border-radius:6px;padding:10px;margin-bottom:6px">
            <div style="font-size:11px;color:#999;margin-bottom:4px">${escapeHtml(r.source)} · 相似度: ${r.score.toFixed(3)}</div>
            <div style="font-size:13px">${escapeHtml(r.text)}</div>
          </div>`;
        });
      }
      if (d.graph && d.graph.length) {
        html += '<h3>🔗 图谱实体匹配</h3>';
        d.graph.forEach(r => {
          html += `<div style="background:#fff;border:1px solid #eee;border-radius:6px;padding:8px 12px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;cursor:pointer"
            onclick="selectEntity('${escapeStr(r.name)}')">
            <div><span style="font-weight:500">${escapeHtml(r.name)}</span> <span class="type-badge">${escapeHtml(r.type)}</span></div>
            <div class="entity-degree">${r.degree}</div>
          </div>`;
        });
      }
      if (!html) html = '<div style="color:#999;text-align:center;padding:40px">无结果</div>';
      res.innerHTML = html;
    }).catch(e => res.innerHTML = '<div class="error">搜索失败: ' + e + '</div>');
}

// Override switchTab for RAG
const origSwitchTab = window.switchTab;
window.switchTab = function(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('#dashboard,#detail,#graph,#rag').forEach(d => d.classList.remove('active'));
  document.getElementById(name).classList.add('active');
  if (name === 'rag') { switchTabRag(); }
  if (name === 'graph') setTimeout(drawGraph, 100);
};

// ---- Utilities ----
function escapeHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function escapeStr(s) { return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'"); }

// Init
loadEntities(1);
</script>
</body>
</html>"""


def main():
    import argparse

    parser = argparse.ArgumentParser(description="知识图谱 Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()

    print(f"\n  Knowledge Graph Web UI")
    print(f"  Open http://{args.host}:{args.port} in your browser\n")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
