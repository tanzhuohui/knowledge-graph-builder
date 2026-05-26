import re
import os
import yaml
import csv


class DocumentChunker:
    def __init__(self, config_path=None):
        self.config = self._load_config(config_path)

    def _load_config(self, path):
        if path is None:
            path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "chunking_config.yaml",
            )
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)["chunking"]

    def chunk_file(self, filepath):
        """根据文件类型分块，支持 md/txt/csv"""
        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.csv':
            return self.chunk_csv(filepath)
        else:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
            return self.chunk_text(text, os.path.basename(filepath))

    def chunk_csv(self, filepath):
        """将 CSV 文件按行转换为文本块，每行作为一个 chunk"""
        chunks = []
        source = os.path.basename(filepath)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                if not headers:
                    return chunks
                
                for i, row in enumerate(reader):
                    # 将每行转换为可读文本描述
                    parts = [f"行 {i+1}:"]
                    for h in headers:
                        val = row.get(h, '').strip()
                        if val:
                            parts.append(f"{h}={val}")
                    text = ", ".join(parts)
                    chunks.append({
                        "id": f"{source}_row_{i}",
                        "source": source,
                        "index": i,
                        "text": text,
                        "word_count": len(text.split()),
                    })
        except Exception as e:
            print(f"  CSV 解析错误 {filepath}: {e}")
        return chunks

    def chunk_text(self, text, source="unknown"):
        strategy = self.config.get("strategy", "fixed")
        if strategy == "fixed":
            return self._fixed_chunk(text, source)
        elif strategy == "sliding_window":
            return self._sliding_window(text, source)
        else:
            return self._fixed_chunk(text, source)

    def _fixed_chunk(self, text, source):
        chunk_size = self.config.get("chunk_size", 1500)
        overlap = self.config.get("overlap", 250)
        separator = self.config.get("separator", "\n\n")

        paragraphs = text.split(separator)
        chunks = []
        current = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para.split())
            if current_len + para_len > chunk_size and current:
                chunks.append(" ".join(current))
                tail = current[-1] if len(current) > 1 else ""
                current = [tail, para] if tail else [para]
                current_len = len(tail.split()) + para_len
            else:
                current.append(para)
                current_len += para_len

        if current:
            chunks.append(" ".join(current))

        return [
            {
                "id": f"{source}_chunk_{i}",
                "source": source,
                "index": i,
                "text": chunk.strip(),
                "word_count": len(chunk.split()),
            }
            for i, chunk in enumerate(chunks)
            if chunk.strip()
        ]

    def _sliding_window(self, text, source):
        chunk_size = self.config.get("chunk_size", 1500)
        overlap = self.config.get("overlap", 250)
        words = text.split()
        chunks = []
        step = chunk_size - overlap

        for i in range(0, len(words), step):
            window = words[i:i + chunk_size]
            if not window:
                break
            chunk_text = " ".join(window)
            chunks.append({
                "id": f"{source}_chunk_{len(chunks)}",
                "source": source,
                "index": len(chunks),
                "text": chunk_text.strip(),
                "word_count": len(window),
            })

        return chunks
