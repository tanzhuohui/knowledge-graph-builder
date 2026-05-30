"""向量存储模块 — 文档分块的语义索引与检索

提供两套后端：
1. API Embedding：通过 LLM provider 的 embedding API（OpenAI 兼容）
2. 基于分词频率的统计相似度降级方案
"""

import os
import json
import re
import math
import pickle
import numpy as np
from collections import Counter


# ---------- 简单中文分词 (无需外部依赖) ----------

_CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')
_WORD_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]{1,}')

def tokenize(text):
    """拆分为 tokens：中文单字 + 英文词"""
    tokens = []
    for ch in text:
        if _CHINESE_RE.match(ch):
            tokens.append(ch)
    for m in _WORD_RE.finditer(text):
        tokens.append(m.group().lower())
    return tokens


def compute_tfidf_vectors(texts):
    """基于词频-逆文档频率构建稀疏向量矩阵 (返回 numpy 矩阵 + idf 权重)"""
    doc_freq = Counter()
    doc_tokens = []

    for text in texts:
        tokens = tokenize(text)
        doc_tokens.append(tokens)
        doc_freq.update(set(tokens))

    n_docs = len(texts)
    idf = {w: math.log((n_docs + 1) / (df + 1)) + 1 for w, df in doc_freq.items()}
    vocab = {w: i for i, w in enumerate(idf.keys())}
    n_dim = len(vocab)

    if n_dim == 0:
        return np.zeros((n_docs, 1)), vocab, idf

    matrix = np.zeros((n_docs, n_dim), dtype=np.float32)
    for i, tokens in enumerate(doc_tokens):
        tf = Counter(tokens)
        max_tf = max(tf.values()) if tf else 1
        for w, c in tf.items():
            if w in vocab:
                matrix[i, vocab[w]] = (c / max_tf) * idf[w]

    return matrix, vocab, idf


def cosine_similarity(a, b):
    dots = np.dot(a, b.T)
    na = np.linalg.norm(a, axis=1, keepdims=True).clip(min=1e-10)
    nb = np.linalg.norm(b, axis=1, keepdims=True).clip(min=1e-10)
    return dots / (na * nb.T)


# ---------- LLM API Embedding ----------

def call_embedding_api(texts, llm_config):
    """通过 OpenAI 兼容的 embedding API 获取向量"""
    import requests

    provider = llm_config.get("llm", {}).get("provider", "ollama")
    base_url = llm_config["llm"]["base_url"].rstrip("/")
    api_key = llm_config["llm"].get("api_key", "")
    model = llm_config.get("embedding", {}).get("model", "text-embedding-v3")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # OpenAI 兼容 API（LMStudio / DashScope / OpenAI）
    if provider in ("lmstudio", "openai") or "openai" in base_url or "dashscope" in base_url:
        url = f"{base_url}/embeddings"
        resp = requests.post(url, headers=headers, json={
            "model": model,
            "input": texts if isinstance(texts, list) else [texts],
        }, timeout=60)
        resp.raise_for_status()
        data = resp.json()["data"]
        data.sort(key=lambda x: x["index"])
        return np.array([d["embedding"] for d in data], dtype=np.float32)

    # Ollama
    url = f"{base_url}/api/embed"
    resp = requests.post(url, headers=headers, json={
        "model": model,
        "input": texts if isinstance(texts, list) else [texts],
    }, timeout=60)
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"], dtype=np.float32)


# ---------- VectorStore ----------

class VectorStore:
    """文档分块的向量索引"""

    def __init__(self, llm_config=None):
        self.llm_config = llm_config
        self.chunks = []
        self.vectors = None
        self._tfidf_vocab = None
        self._tfidf_idf = None
        self.index_path = None

    @property
    def use_api(self):
        return self.llm_config and self._has_embedding_support()

    def _has_embedding_support(self):
        provider = self.llm_config.get("llm", {}).get("provider", "")
        base_url = self.llm_config["llm"]["base_url"].lower()
        return provider in ("lmstudio", "openai") or "dashscope" in base_url or "openai" in base_url

    def build_index(self, chunks):
        """为 chunk 列表构建向量索引"""
        self.chunks = chunks
        texts = [c["text"] for c in chunks]

        if not texts:
            self.vectors = np.zeros((0, 1))
            return

        if self.use_api:
            try:
                print(f"  Building API embeddings for {len(chunks)} chunks...")
                self.vectors = call_embedding_api(texts, self.llm_config)
                print(f"  Embedding dim: {self.vectors.shape[1]}")
                return
            except Exception as e:
                print(f"  API embedding failed: {e}, falling back to TF-IDF")

        # TF-IDF fallback
        print(f"  Building TF-IDF vectors for {len(chunks)} chunks...")
        self.vectors, self._tfidf_vocab, self._tfidf_idf = compute_tfidf_vectors(texts)
        print(f"  TF-IDF dim: {self.vectors.shape[1]}")
        return self

    def _query_vector(self, text):
        """将查询文本转为与索引相同维度的向量"""
        if self.use_api and self._has_embedding_support():
            return call_embedding_api([text], self.llm_config)

        # TF-IDF: 使用已存储的词汇表和 idf 构建查询向量
        if self._tfidf_vocab is None or self._tfidf_idf is None:
            return np.zeros((1, self.vectors.shape[1]))

        tokens = tokenize(text)
        tf = Counter(tokens)
        max_tf = max(tf.values()) if tf else 1
        n_dim = len(self._tfidf_vocab)
        qv = np.zeros((1, n_dim), dtype=np.float32)
        for w, c in tf.items():
            if w in self._tfidf_vocab:
                qv[0, self._tfidf_vocab[w]] = (c / max_tf) * self._tfidf_idf[w]
        return qv

    def query(self, text, k=5):
        """查询与 text 最相似的 k 个 chunk"""
        if len(self.chunks) == 0 or self.vectors is None:
            return []

        qv = self._query_vector(text)

        sims = cosine_similarity(qv, self.vectors).flatten()
        top_k = min(k, len(sims))
        indices = np.argsort(sims)[::-1][:top_k]

        return [
            {
                "chunk": self.chunks[i],
                "score": float(sims[i]),
                "index": i,
            }
            for i in indices
            if sims[i] > 0.01
        ]

    def add_chunks(self, chunks):
        """增量添加 chunk 并重建索引"""
        self.chunks.extend(chunks)
        self.build_index(self.chunks)

    def save(self, path):
        """持久化到磁盘"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.index_path = path
        data = {
            "chunks": self.chunks,
            "vectors": self.vectors.tolist() if self.vectors is not None else None,
            "vocab": {w: i for w, i in (self._tfidf_vocab or {}).items()} if self._tfidf_vocab else None,
            "idf": {w: float(v) for w, v in (self._tfidf_idf or {}).items()} if self._tfidf_idf else None,
            "use_api": self.use_api,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path, llm_config=None):
        if not os.path.exists(path):
            vs = cls(llm_config=llm_config)
            vs.index_path = path
            return vs

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        vs = cls(llm_config=llm_config)
        vs.chunks = data.get("chunks", [])
        vecs = data.get("vectors")
        vs.vectors = np.array(vecs, dtype=np.float32) if vecs else None
        vs._tfidf_vocab = data.get("vocab")
        vs._tfidf_idf = data.get("idf")
        vs.index_path = path
        return vs

    def needs_rebuild(self, current_chunks):
        """判断索引是否需要重建（chunk 数量或内容变化）"""
        if len(self.chunks) != len(current_chunks):
            return True
        for a, b in zip(self.chunks, current_chunks):
            if a.get("text") != b.get("text") or a.get("id") != b.get("id"):
                return True
        return False
