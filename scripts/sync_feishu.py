#!/usr/bin/env python3
"""飞书知识库同步插件：自动拉取飞书文档并转为 Markdown 存入 data/raw/"""

import os
import sys
import yaml
import json
import time
import hashlib
import requests
from urllib.parse import quote

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

class FeishuSyncer:
    def __init__(self, config_path=None):
        self.base_url = "https://open.feishu.cn/open-apis"
        self.config = self._load_config(config_path)
        self.token = None
        self.img_dir = os.path.join(BASE_DIR, "data", "raw", "feishu_images")
        os.makedirs(self.img_dir, exist_ok=True)

    def _load_config(self, path):
        if path is None:
            path = os.path.join(BASE_DIR, "config", "feishu_config.yaml")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Feishu config not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)["feishu"]

    def get_token(self):
        if self.token:
            return self.token
        
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        data = {
            "app_id": self.config["app_id"],
            "app_secret": self.config["app_secret"]
        }
        resp = requests.post(url, json=data)
        result = resp.json()
        
        if result.get("code") != 0:
            raise Exception(f"Failed to get token: {result}")
            
        self.token = result["tenant_access_token"]
        print("  Authenticated with Feishu successfully.")
        return self.token

    def _get(self, path, params=None):
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        resp = requests.get(url, headers=headers, params=params)
        result = resp.json()
        if result.get("code") != 0:
            print(f"  WARN: API error {path}: {result}")
        return result

    def sync_wiki(self, space_id, root_token=None):
        """Synchronize a Feishu Wiki space."""
        print(f"  Syncing Wiki Space: {space_id}")
        
        # Get root node if not provided
        if not root_token:
            res = self._get(f"/wiki/v2/spaces/{space_id}/root_node")
            if res.get("code") == 0 and "data" in res:
                root_token = res["data"]["node"]["obj_token"]
        
        # Walk tree
        nodes = self._walk_nodes(space_id, root_token)
        print(f"  Found {len(nodes)} documents.")
        
        # Sync documents
        synced_count = 0
        for node in nodes:
            if node["obj_type"] != "docx":
                continue
            
            obj_token = node["obj_token"]
            title = node.get("title", "Untitled")
            print(f"  Downloading: {title}...")
            
            try:
                content = self._get_docx_content(obj_token)
                md_content = self._blocks_to_markdown(content.get("blocks", []))
                
                # Save to raw
                filename = self._safe_filename(title)
                filepath = os.path.join(BASE_DIR, "data", "raw", f"{filename}.md")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n\n{md_content}")
                
                synced_count += 1
                time.sleep(0.2)
            except Exception as e:
                print(f"  ERROR syncing {title}: {e}")
        
        print(f"\n  Done. Synced {synced_count} documents to data/raw/")

    def _walk_nodes(self, space_id, parent_token):
        nodes = []
        page_token = None
        
        while True:
            params = {"page_size": 50}
            if page_token:
                params["page_token"] = page_token
                
            res = self._get(f"/wiki/v2/spaces/{space_id}/nodes", {"parent_node_token": parent_token, **params})
            
            if res.get("code") == 0 and "data" in res:
                items = res["data"]["items"]
                nodes.extend(items)
                
                for item in items:
                    if item["has_child"]:
                        nodes.extend(self._walk_nodes(space_id, item["node_token"]))
                
                if not res["data"]["has_more"]:
                    break
                page_token = res["data"]["page_token"]
            else:
                break
        return nodes

    def _get_docx_content(self, document_id):
        res = self._get(f"/docx/v1/documents/{document_id}/raw_content", {"lang": 0})
        return res.get("data", {})

    def _blocks_to_markdown(self, blocks):
        md = []
        for block in blocks:
            block_type = block.get("block_type")
            
            # 1: Page, 2: Text, 3: Heading
            if block_type in [1, 2, 3]:
                style = block.get("heading", {}).get("style", 1) if block_type == 3 else 1
                prefix = "#" * style if block_type == 3 else ""
                
                text = self._get_text_content(block)
                if text:
                    md.append(f"{prefix} {text}\n")
            
            elif block_type == 10: # Bullet List
                text = self._get_text_content(block)
                if text:
                    md.append(f"- {text}\n")
            
            elif block_type == 7: # Image
                token = block.get("image", {}).get("token")
                if token:
                    filename = self._download_image(token)
                    md.append(f"![Image]({filename})\n")
            
            elif block_type == 4: # Table
                md.append("*(Table content omitted for simplicity)*\n")

        return "\n".join(md)

    def _get_text_content(self, block):
        # Text elements are nested. We simplify by looking for 'text' keys recursively
        texts = []
        if "text" in block:
            for t in block["text"]:
                if isinstance(t, dict):
                    texts.append(t.get("text_run", {}).get("content", ""))
                elif isinstance(t, str):
                    texts.append(t)
        return "".join(texts).strip()

    def _download_image(self, file_token):
        local_name = f"img_{file_token}.bin" # Ideally check extension
        local_path = os.path.join("feishu_images", local_name)
        
        # Check if already exists
        if os.path.exists(os.path.join(BASE_DIR, "data", "raw", local_path)):
            return local_path

        headers = {"Authorization": f"Bearer {self.get_token()}"}
        resp = requests.get(f"{self.base_url}/drive/v1/medias/{file_token}", headers=headers)
        
        if resp.status_code == 200:
            with open(os.path.join(BASE_DIR, "data", "raw", local_path), "wb") as f:
                f.write(resp.content)
            return local_path
        return ""

    def _safe_filename(self, name):
        safe = "".join([c if c.isalnum() or c in (' ', '_', '-', '.') else '_' for c in name])
        return safe.strip()

def main():
    try:
        config_path = sys.argv[1] if len(sys.argv) > 1 else None
        syncer = FeishuSyncer(config_path)
        
        # Requires space_id from config or args
        space_id = syncer.config.get("space_id")
        if not space_id:
            print("Please set 'space_id' in config/feishu_config.yaml")
            return

        syncer.sync_wiki(space_id)
    except Exception as e:
        print(f"Fatal Error: {e}")

if __name__ == "__main__":
    main()
