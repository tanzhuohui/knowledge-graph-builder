import json
import os
import yaml
import requests
import re
import time


class EntityExtractor:
    def __init__(self, config_path=None, schema_path=None):
        self.llm_config = self._load_llm_config(config_path)
        self.schema = self._load_schema(schema_path)

    def _load_llm_config(self, path):
        if path is None:
            path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "llm_config.yaml",
            )
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_schema(self, path):
        if path is None:
            path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "schema.json",
            )
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _build_prompt(self, text, related_contexts=None):
        entity_types = [e["type"] for e in self.schema.get("entities", [])]
        relation_types = [r["type"] for r in self.schema.get("relations", [])]

        prompt_body = f"""你是一个知识图谱构建专家。请从以下文本中提取所有实体和关系。

【文本内容】
{text}

"""

        if related_contexts:
            related_section = "\n【相关上下文】（以下内容与本文本语义相近，可作为抽取参考）\n"
            for i, ctx in enumerate(related_contexts[:3]):
                related_section += f"\n--- 相关片段 {i+1} (相似度: {ctx['score']:.2f}) ---\n{ctx['chunk']['text'][:500]}\n"
            prompt_body += related_section

        prompt_body += f"""
【提取要求】
1. 实体类型: {", ".join(entity_types)}
2. 关系类型: {", ".join(relation_types)}
3. 输出格式 (严格 JSON 数组):
[
  {{
    "subject": "实体 A",
    "subject_type": "PERSON",
    "relation": "WORKS_FOR",
    "object": "实体 B",
    "object_type": "ORGANIZATION",
    "confidence": 0.95,
    "source_text": "原文引用"
  }}
]

【注意事项】
- 只输出 JSON，不要其他解释
- 关系必须有明确的方向性
- 不确定的关系标注 confidence < 0.7
- 优先从【文本内容】中抽取，【相关上下文】仅作为补充参考
"""
        return prompt_body

    def _build_vision_prompt(self, text, related_contexts=None):
        entity_types = [e["type"] for e in self.schema.get("entities", [])]
        relation_types = [r["type"] for r in self.schema.get("relations", [])]

        prompt_body = f"""你是一个知识图谱构建专家。请分析这张图片/图表/截图，提取其中包含的实体和关系。
图片说明: {text}
"""

        if related_contexts:
            related_section = "\n【相关上下文】（以下内容与本文本语义相近，可作为抽取参考）\n"
            for i, ctx in enumerate(related_contexts[:3]):
                related_section += f"\n--- 相关片段 {i+1} (相似度: {ctx['score']:.2f}) ---\n{ctx['chunk']['text'][:500]}\n"
            prompt_body += related_section

        prompt_body += f"""
【提取要求】
1. 实体类型: {", ".join(entity_types)}
2. 关系类型: {", ".join(relation_types)}
3. 输出格式 (严格 JSON 数组):
[
  {{
    "subject": "实体 A",
    "subject_type": "PERSON",
    "relation": "WORKS_FOR",
    "object": "实体 B",
    "object_type": "ORGANIZATION",
    "confidence": 0.95,
    "source_text": "图片中可见的内容描述"
  }}
]

【注意事项】
- 只输出 JSON，不要其他解释
- 关系必须有明确的方向性
- 不确定的关系标注 confidence < 0.7
- 优先从图片可见内容中抽取
- 如果图片中没有可抽取的内容，返回 []
"""
        return prompt_body

    def _call_llm(self, prompt, max_retries=3):
        provider = self.llm_config["llm"].get("provider", "ollama")
        if provider == "lmstudio":
            return self._call_lmstudio(prompt, max_retries)
        return self._call_ollama(prompt, max_retries)

    def _call_lmstudio(self, prompt, max_retries=3):
        base_url = self.llm_config["llm"]["base_url"].rstrip("/")
        api_key = self.llm_config["llm"].get("api_key", "")
        model = self.llm_config["llm"]["model"]
        timeout = self.llm_config["llm"].get("timeout", 120)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.llm_config["llm"].get("temperature", 0),
            "chat_template_kwargs":{"enable_thinking":False},
        }

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"  LLM call attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def _call_ollama(self, prompt, max_retries=3):
        model = self.llm_config["llm"]["model"]
        base_url = self.llm_config["llm"]["base_url"]
        timeout = self.llm_config["llm"].get("timeout", 120)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.llm_config["llm"].get("temperature", 0),
            },
        }

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{base_url}/api/generate",
                    json=payload,
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json().get("response", "")
            except Exception as e:
                print(f"  LLM call attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def _call_vision_llm(self, prompt, image_path, max_retries=3):
        provider = self.llm_config["llm"].get("provider", "ollama")
        if provider == "ollama":
            return self._call_ollama_vision(prompt, image_path, max_retries)
        return self._call_openai_vision(prompt, image_path, max_retries)

    def _call_openai_vision(self, prompt, image_path, max_retries=3):
        import base64
        base_url = self.llm_config["llm"]["base_url"].rstrip("/")
        api_key = self.llm_config["llm"].get("api_key", "")
        model = self.llm_config["llm"].get("vision_model", self.llm_config["llm"]["model"])
        timeout = self.llm_config["llm"].get("timeout", 120)

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}
        mime = mime_map.get(ext, "image/png")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ],
            }],
            "temperature": self.llm_config["llm"].get("temperature", 0),
        }

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers=headers, json=payload, timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"  Vision API call attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def _call_ollama_vision(self, prompt, image_path, max_retries=3):
        import base64
        model = self.llm_config["llm"].get("vision_model", self.llm_config["llm"]["model"])
        base_url = self.llm_config["llm"]["base_url"]
        timeout = self.llm_config["llm"].get("timeout", 120)

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": self.llm_config["llm"].get("temperature", 0)},
        }

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{base_url}/api/generate",
                    json=payload, timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json().get("response", "")
            except Exception as e:
                print(f"  Ollama vision call attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def _parse_json(self, raw_text):
        json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        raise ValueError(f"No JSON array found in response: {raw_text[:200]}")

    def extract(self, text, chunk_id="unknown", related_contexts=None, image_path=None):
        if image_path:
            prompt = self._build_vision_prompt(text, related_contexts)
            raw = self._call_vision_llm(prompt, image_path)
        else:
            prompt = self._build_prompt(text, related_contexts)
            raw = self._call_llm(prompt)
        triples = self._parse_json(raw)

        for t in triples:
            t["source_chunk"] = chunk_id

        confidence_threshold = self.llm_config.get("extraction", {}).get(
            "confidence_threshold", 0.7
        )
        filtered = [
            t for t in triples
            if t.get("confidence", 0) >= confidence_threshold
        ]
        return filtered

    def extract_batch(self, chunks, vector_store=None, rag_k=3):
        all_triples = []

        for i, chunk in enumerate(chunks):
            print(f"  Extracting chunk {i+1}/{len(chunks)}: {chunk['id']}")
            related_contexts = None
            if vector_store is not None:
                related_contexts = vector_store.query(chunk["text"], k=rag_k)
                # 排除自身
                related_contexts = [rc for rc in related_contexts if rc["chunk"]["id"] != chunk["id"]]
                if related_contexts:
                    print(f"    → RAG context: {len(related_contexts)} similar chunk(s)")
            try:
                triples = self.extract(chunk["text"], chunk["id"], related_contexts,
                                       image_path=chunk.get("image_path"))
                all_triples.extend(triples)
            except Exception as e:
                print(f"  ERROR on chunk {chunk['id']}: {e}")

        return all_triples
