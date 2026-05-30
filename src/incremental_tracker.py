"""增量更新追踪器：记录文档快照，检测新增/修改/删除"""

import os
import json
import hashlib


def file_hash(filepath):
    """计算文件 SHA256（仅内容）"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class IncrementalTracker:
    def __init__(self, state_path):
        self.state_path = state_path
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"files": {}}

    def save(self):
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def scan(self, filepaths):
        """对比当前文件列表与快照，返回 (new_files, modified_files, deleted_files, unchanged_files)"""
        current = {}
        for fp in filepaths:
            abs_fp = os.path.abspath(fp)
            current[abs_fp] = fp

        prev = self.state.get("files", {})
        prev_keys = set(prev.keys())
        curr_keys = set(current.keys())

        new_files = []
        modified_files = []
        unchanged_files = []

        for abs_fp, rel_fp in current.items():
            if abs_fp not in prev_keys:
                new_files.append(rel_fp)
            else:
                cur_hash = file_hash(rel_fp)
                if cur_hash != prev[abs_fp].get("hash"):
                    modified_files.append(rel_fp)
                else:
                    unchanged_files.append(rel_fp)

        deleted_files = [prev[k]["path"] for k in (prev_keys - curr_keys)]

        return new_files, modified_files, deleted_files, unchanged_files

    def register_file(self, filepath, chunk_ids, triple_indices):
        """注册已处理的文件快照"""
        abs_fp = os.path.abspath(filepath)
        self.state.setdefault("files", {})[abs_fp] = {
            "path": filepath,
            "hash": file_hash(filepath),
            "chunk_ids": chunk_ids,
            "triple_indices": triple_indices,
        }

    def unregister_file(self, abs_fp):
        """移除已删除的文件记录"""
        self.state["files"].pop(abs_fp, None)

    def get_deleted_triple_indices(self, abs_fp):
        """获取待删除文件对应的三元组索引"""
        rec = self.state.get("files", {}).get(abs_fp, {})
        return rec.get("triple_indices", [])

    def is_first_run(self):
        return len(self.state.get("files", {})) == 0
