import os
import re
import json
import yaml
import requests
import time


class WikiLinter:
    def __init__(self, graph, wiki_dir, config_path=None):
        self.graph = graph
        self.wiki_dir = wiki_dir
        self.entities_dir = os.path.join(wiki_dir, "entities")
        self.llm_config = self._load_llm_config(config_path)
        self.report = {
            "issues": [],
            "fixed": [],
            "timestamp": "",
        }

    def _load_llm_config(self, path):
        if path is None:
            path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "llm_config.yaml",
            )
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return None

    def lint(self):
        print("  Running wiki lint checks...")
        self._check_orphan_entities()
        self._check_low_confidence_edges()
        self._check_contradictory_relations()
        self._check_missing_summaries()
        self._print_report()
        return self.report

    def _check_orphan_entities(self):
        orphans = []
        for node in self.graph.nodes():
            if self.graph.degree(node) == 0:
                orphans.append(node)

        if orphans:
            self.report["issues"].append({
                "type": "orphan_entities",
                "count": len(orphans),
                "entities": orphans[:20],
                "severity": "warning",
                "message": f"Found {len(orphans)} isolated entities with no connections",
            })

            for entity in orphans[:5]:
                print(f"    [WARN] Orphan: {entity[:50]}")

    def _check_low_confidence_edges(self):
        low_conf = []
        threshold = 0.5
        for u, v, attrs in self.graph.edges(data=True):
            conf = attrs.get("confidence", 1.0)
            if conf < threshold:
                low_conf.append({
                    "subject": u,
                    "relation": attrs.get("relation", ""),
                    "object": v,
                    "confidence": conf,
                })

        if low_conf:
            self.report["issues"].append({
                "type": "low_confidence_edges",
                "count": len(low_conf),
                "edges": low_conf[:20],
                "severity": "info",
                "message": f"Found {len(low_conf)} edges with confidence < {threshold}",
            })
            print(f"    [INFO] {len(low_conf)} low-confidence edges (< {threshold})")

    def _check_contradictory_relations(self):
        edge_map = {}
        for u, v, attrs in self.graph.edges(data=True):
            key = (u, v)
            if key not in edge_map:
                edge_map[key] = []
            edge_map[key].append(attrs.get("relation", ""))

        contradictions = []
        for (u, v), relations in edge_map.items():
            unique_relations = set(relations)
            if len(unique_relations) > 1:
                contradictions.append({
                    "subject": u,
                    "object": v,
                    "conflicting_relations": list(unique_relations),
                })

        if contradictions and self.llm_config:
            resolved = self._resolve_contradictions(contradictions)
            self.report["issues"].append({
                "type": "contradictory_relations",
                "count": len(contradictions),
                "contradictions": contradictions[:10],
                "resolved": resolved,
                "severity": "warning",
                "message": f"Found {len(contradictions)} pairs with multiple relation types",
            })
        elif contradictions:
            self.report["issues"].append({
                "type": "contradictory_relations",
                "count": len(contradictions),
                "contradictions": contradictions[:10],
                "severity": "warning",
                "message": f"Found {len(contradictions)} pairs with multiple relation types (no LLM to resolve)",
            })

        if contradictions:
            print(f"    [WARN] {len(contradictions)} contradictory relation pairs")

    def _resolve_contradictions(self, contradictions):
        resolved = []
        for item in contradictions[:5]:
            prompt = f"""判断以下两个实体之间的关系，哪个描述更准确:

实体 A: {item['subject']}
实体 B: {item['object']}
可能的关系: {', '.join(item['conflicting_relations'])}

请选择最合适的一个关系类型，并简要说明理由。
输出格式: {{"selected_relation": "...", "reason": "..."}}
只输出 JSON，不要其他内容。
"""
            try:
                provider = self.llm_config["llm"].get("provider", "ollama")
                if provider == "lmstudio":
                    result = self._call_lmstudio(prompt)
                else:
                    result = self._call_ollama(prompt)

                parsed = json.loads(result)
                resolved.append({
                    "subject": item["subject"],
                    "object": item["object"],
                    "selected": parsed.get("selected_relation", ""),
                    "reason": parsed.get("reason", ""),
                })
                self.report["fixed"].append({
                    "type": "contradiction_resolved",
                    "subject": item["subject"],
                    "object": item["object"],
                    "selected": parsed.get("selected_relation", ""),
                })
                print(f"    [FIX] {item['subject']} -> {item['object']}: {parsed.get('selected_relation', '')}")
            except Exception:
                resolved.append({
                    "subject": item["subject"],
                    "object": item["object"],
                    "selected": "UNRESOLVED",
                    "reason": "LLM resolution failed",
                })

            time.sleep(0.2)

        return resolved

    def _check_missing_summaries(self):
        if not os.path.exists(self.entities_dir):
            return

        missing = []
        for filename in os.listdir(self.entities_dir):
            if not filename.endswith(".md"):
                continue
            filepath = os.path.join(self.entities_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "> " not in content or content.count("\n") < 10:
                missing.append(filename)

        if missing:
            self.report["issues"].append({
                "type": "missing_summaries",
                "count": len(missing),
                "files": missing[:20],
                "severity": "info",
                "message": f"Found {len(missing)} entity pages with missing or incomplete summaries",
            })
            print(f"    [INFO] {len(missing)} pages with incomplete summaries")

    def _print_report(self):
        total_issues = len(self.report["issues"])
        total_fixed = len(self.report["fixed"])

        print(f"\n  Lint Report:")
        print(f"    Total issues: {total_issues}")
        print(f"    Auto-fixed: {total_fixed}")

        severity_counts = {"warning": 0, "info": 0, "error": 0}
        for issue in self.report["issues"]:
            sev = issue.get("severity", "info")
            if sev in severity_counts:
                severity_counts[sev] += 1

        print(f"    Warnings: {severity_counts['warning']}")
        print(f"    Info: {severity_counts['info']}")
        print(f"    Errors: {severity_counts['error']}")

    def save_report(self, output_path=None):
        if output_path is None:
            output_path = os.path.join(self.wiki_dir, "lint_report.json")
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.report, f, indent=2, ensure_ascii=False, default=str)
        print(f"  Lint report saved: {output_path}")
        return output_path

    def _call_lmstudio(self, prompt):
        base_url = self.llm_config["llm"]["base_url"].rstrip("/")
        api_key = self.llm_config["llm"].get("api_key", "")
        model = self.llm_config["llm"]["model"]
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            timeout=60,
        )
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _call_ollama(self, prompt):
        model = self.llm_config["llm"]["model"]
        base_url = self.llm_config["llm"]["base_url"]
        resp = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        return resp.json().get("response", "").strip()
