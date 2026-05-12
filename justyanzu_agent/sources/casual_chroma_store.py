"""
仅将 casual_agent 的落盘会话写入 ChromaDB（code_agent 等其它类型不向量化）。
每次索引会先清空集合再写入当前文件，库中只保留「这一次」对应的切块，不累积历史文件。
主流程里 memory_agent 只从磁盘读取该代理最近一次 memory_*.txt；检索 API 仍可供扩展脚本使用。
"""

from __future__ import annotations

import configparser
import json
from pathlib import Path
from typing import Any

_config = configparser.ConfigParser()
_config.read("config.ini")


def _vec_section() -> dict[str, str]:
    if not _config.has_section("CASUAL_VECTOR"):
        return {}
    return {k.lower(): v for k, v in _config.items("CASUAL_VECTOR")}


def is_casual_vector_enabled() -> bool:
    s = _vec_section()
    if not s:
        return False
    return str(s.get("enabled", "true")).lower() in ("1", "true", "yes", "on")


def _retrieve_top_k() -> int:
    s = _vec_section()
    try:
        return max(1, int(s.get("retrieve_top_k", "8")))
    except ValueError:
        return 8


def _max_chunk_chars() -> int:
    s = _vec_section()
    try:
        return max(256, int(s.get("max_chunk_chars", "2000")))
    except ValueError:
        return 2000


def _embedding_model() -> str:
    s = _vec_section()
    name = (s.get("embedding_model") or "all-MiniLM-L6-v2").strip()
    return name or "all-MiniLM-L6-v2"


def _chroma_dir(conversation_root: str | Path) -> Path:
    """conversation_root 为包含 casual_agent 子目录的 conversations 路径。"""
    s = _vec_section()
    rel = (s.get("chroma_subdir") or "casual_agent/chroma_db").strip() or "casual_agent/chroma_db"
    return Path(conversation_root) / rel


def records_to_chunk_texts(records: list[Any], max_chars: int) -> list[str]:
    """
    将非 system 消息按「用户一条 + 助手一条」合并为检索单元；超长块按 max_chars 切分。
    """
    chunks: list[str] = []
    turn_parts: list[str] = []

    def emit() -> None:
        nonlocal turn_parts
        if not turn_parts:
            return
        text = "\n".join(turn_parts).strip()
        turn_parts = []
        if not text:
            return
        for start in range(0, len(text), max_chars):
            chunks.append(text[start : start + max_chars])

    for item in records:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role == "system":
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            if turn_parts:
                emit()
            turn_parts.append(f"用户：{content}")
        elif role == "assistant":
            turn_parts.append(f"助手：{content}")
            emit()
        else:
            turn_parts.append(f"{role}：{content}")
    emit()
    return chunks


def _get_collection(conversation_root: str | Path):
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    chroma_dir = _chroma_dir(conversation_root)
    chroma_dir.mkdir(parents=True, exist_ok=True)
    ef = SentenceTransformerEmbeddingFunction(model_name=_embedding_model())
    client = chromadb.PersistentClient(path=str(chroma_dir))
    return client.get_or_create_collection(
        name="casual_agent_memory",
        embedding_function=ef,
    )


def _clear_all_ids(col) -> None:
    """删除集合内全部文档，便于只保留当前一次索引内容（分页 get，避免默认 limit 截断）。"""
    page = 1000
    try:
        while True:
            batch = col.get(include=[], limit=page)
            ids = batch.get("ids") if batch else None
            if not ids:
                return
            col.delete(ids=list(ids))
    except Exception:
        return


def index_casual_memory_file(
    abs_or_rel_path: str,
    conversation_root: str | Path | None = None,
) -> int:
    """
    读取 save_memory 写入的 JSON 列表，切块并写入 Chroma。
    写入前会清空集合，因此库中仅含本文件切块，不与其他 memory_*.txt 并存。
    返回写入的块数量；未启用或失败时返回 0。
    """
    if not is_casual_vector_enabled():
        return 0
    path = Path(abs_or_rel_path)
    if not path.is_file():
        return 0
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        records = json.loads(raw)
    except Exception:
        return 0
    if not isinstance(records, list):
        return 0

    if conversation_root is None:
        conversation_root = "conversations"
    chunk_texts = records_to_chunk_texts(records, _max_chunk_chars())
    if not chunk_texts:
        return 0

    try:
        col = _get_collection(conversation_root)
    except Exception:
        return 0

    stem = path.stem
    ids = [f"{stem}_{i}" for i in range(len(chunk_texts))]
    metadatas = [
        {"source_file": path.name, "source_path": str(path.resolve())}
        for _ in chunk_texts
    ]
    try:
        _clear_all_ids(col)
        col.add(ids=ids, documents=chunk_texts, metadatas=metadatas)
    except Exception:
        return 0
    return len(chunk_texts)


def search_casual_memory(
    query: str,
    conversation_root: str | Path,
    top_k: int | None = None,
) -> list[str]:
    """按 QUERY 语义检索 casual 历史块文本；空列表表示无结果或未启用。"""
    if not is_casual_vector_enabled():
        return []
    q = (query or "").strip()
    if not q:
        return []
    k = top_k if top_k is not None else _retrieve_top_k()
    try:
        col = _get_collection(conversation_root)
    except Exception:
        return []
    try:
        n = col.count()
    except Exception:
        return []
    if n == 0:
        return []
    try:
        res = col.query(
            query_texts=[q],
            n_results=min(k, max(n, 1)),
        )
    except Exception:
        return []
    docs = res.get("documents") or []
    if not docs or not docs[0]:
        return []
    return [d for d in docs[0] if d]


def backfill_casual_memory_files(conversation_root: str | Path = "conversations") -> int:
    """
    仅将 casual_agent 目录下按文件名排序的**最新一条** memory_*.txt 编入向量库。
    返回写入的块数量（0 表示未找到文件或未启用）。
    """
    from sources.memory import get_latest_saved_memory_filepath

    root = Path(conversation_root)
    latest = get_latest_saved_memory_filepath("casual_agent", str(root))
    if not latest or not Path(latest).is_file():
        return 0
    return index_casual_memory_file(latest, conversation_root=root)
