"""
知识库入库脚本

功能：
- 扫描指定目录下的 .md / .txt 文件
- 滑动窗口切分（chunk_size=500, overlap=50）
- 向量化后存入 chromadb

用法:
    python scripts/ingest.py [knowledge_dir]
    # 默认读取 ./knowledge
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chromadb import PersistentClient

from app.embedding import get_embedding_function

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "knowledge_base")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
OVERLAP = int(os.getenv("OVERLAP", "50"))

chroma = PersistentClient(path=CHROMA_PATH)
embed_fn, embed_model = get_embedding_function()
print(f"[INFO] Embedding 模型: {embed_model}")
collection = chroma.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=embed_fn,
)


def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list:
    """滑动窗口切分"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def ingest_dir(dir_path: str):
    """将目录下所有 .md/.txt 文件切分入库"""
    docs, ids, metadatas = [], [], []
    dir_path = Path(dir_path)

    for fname in sorted(os.listdir(dir_path)):
        if not fname.endswith((".md", ".txt")):
            continue
        fpath = dir_path / fname
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
        for j, chunk in enumerate(split_text(content)):
            docs.append(chunk)
            ids.append(f"{fname}_{j}")
            metadatas.append({"source": fname, "chunk": j})

    if docs:
        # 先清空再入库，避免重复
        existing = collection.get()["ids"]
        if existing:
            collection.delete(ids=existing)
        collection.add(documents=docs, ids=ids, metadatas=metadatas)
        print(f"已入库 {len(docs)} 个片段，来自 {len(set(m['source'] for m in metadatas))} 个文件")
    else:
        print(f"[WARN] 目录 {dir_path} 下未找到 .md/.txt 文件")

    print(f"当前知识库总片段数: {collection.count()}")


if __name__ == "__main__":
    knowledge_dir = sys.argv[1] if len(sys.argv) > 1 else "./knowledge"
    ingest_dir(knowledge_dir)
