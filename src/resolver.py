import re
import os
import yaml
import requests


try:
    from Levenshtein import ratio as lev_ratio
except ImportError:
    def lev_ratio(a, b):
        max_len = max(len(a), len(b))
        if max_len == 0:
            return 1.0
        dist = _basic_distance(a, b)
        return 1.0 - dist / max_len

    def _basic_distance(a, b):
        if len(a) < len(b):
            return _basic_distance(b, a)
        if len(b) == 0:
            return len(a)
        prev_row = range(len(b) + 1)
        for i, c1 in enumerate(a):
            curr_row = [i + 1]
            for j, c2 in enumerate(b):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]


class EntityResolver:
    def __init__(self, threshold=0.85, llm_config_path=None):
        self.threshold = threshold
        self.llm_config = self._load_llm_config(llm_config_path)
        self.entity_map = {}

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

    def _name_similarity(self, name_a, name_b):
        a = re.sub(r'[^\w\u4e00-\u9fff]', '', name_a.lower())
        b = re.sub(r'[^\w\u4e00-\u9fff]', '', name_b.lower())
        return lev_ratio(a, b)

    def resolve(self, triples):
        name_to_canonical = {}

        for triple in triples:
            for key in ["subject", "object"]:
                name = triple.get(key, "").strip()
                if not name:
                    continue
                if name not in name_to_canonical:
                    canonical = self._find_or_register(name, name_to_canonical)
                    name_to_canonical[name] = canonical
                triple[key] = name_to_canonical[name]

        return triples

    def _find_or_register(self, name, mapping):
        for existing in mapping.values():
            if existing == name:
                return existing
            sim = self._name_similarity(name, existing)
            if sim >= self.threshold:
                return existing

        if self.llm_config:
            llm_canonical = self._ask_llm(name, list(set(mapping.values())))
            if llm_canonical and llm_canonical != name:
                if llm_canonical in mapping.values():
                    return llm_canonical

        return name

    def _ask_llm(self, name, existing_names):
        if len(existing_names) > 20:
            return None

        if not existing_names:
            return None

        prompt = f"""判断以下实体是否指向已有实体:

新实体: {name}
已有实体列表: {existing_names}

如果新实体与列表中某个实体指向同一事物，直接返回该实体名称。否则返回 "NEW"。
只返回名称或 NEW，不要其他内容。
"""
        try:
            provider = self.llm_config["llm"].get("provider", "ollama")
            if provider == "lmstudio":
                return self._ask_lmstudio(prompt, existing_names)
            return self._ask_ollama(prompt, existing_names)
        except Exception:
            pass

        return None

    def _ask_lmstudio(self, prompt, existing_names):
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
            timeout=15,
        )
        result = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
        if result in existing_names:
            return result
        return None

    def _ask_ollama(self, prompt, existing_names):
        model = self.llm_config["llm"]["model"]
        base_url = self.llm_config["llm"]["base_url"]
        resp = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=15,
        )
        result = resp.json().get("response", "").strip().strip('"')
        if result in existing_names:
            return result
        return None

    def get_stats(self):
        return {
            "unique_entities": len(set(self.entity_map.values())),
            "merged_aliases": len(self.entity_map) - len(set(self.entity_map.values())),
        }
