"""
从 MySQL 增量同步到 Neo4j：Post、Account、Platform 及 POSTED、IN_PLATFORM。
与 Upload 产出对齐（同一批写入 MySQL 的数据）；幂等使用 MERGE。
"""
from __future__ import annotations

import logging
import os
import zipfile
import hashlib
from datetime import datetime
from xml.etree import ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..utils.setting.paths import bucket
from ..utils.io.db import db_manager
from ..utils.logging.logging import setup_logger, log_module_start, log_success, log_error
from .config import get_graph_config, is_neo4j_configured
from .neo4j_client import get_driver, get_session
from .schema import init_schema
from . import chunk_embedding as chunk_module
from . import entity_extraction as entity_module
from .backfill_graph_node_embeddings import backfill_graph_node_embeddings

LOG = logging.getLogger(__name__)

REPORT_FILE_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


def _post_global_id(topic: str, channel: str, row_id: str) -> str:
    """全局唯一 Post id，避免多专题/多表冲突。"""
    return f"{topic}_{channel}_{row_id}"


def _account_id(topic: str, author: str) -> str:
    """Account 节点唯一 id：topic + author 的稳定标识。"""
    if not author or not str(author).strip():
        author = "__unknown__"
    return f"{topic}_{author}"


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return s if s else ""


def _safe_ts(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def _read_docx_text(path: Path) -> str:
    # Prefer python-docx when available.
    try:
        import docx  # type: ignore

        doc = docx.Document(str(path))
        parts = [p.text.strip() for p in doc.paragraphs if str(p.text or "").strip()]
        return "\n".join(parts).strip()
    except Exception:
        pass

    # Fallback: parse docx XML directly.
    try:
        with zipfile.ZipFile(path, "r") as zf:
            with zf.open("word/document.xml") as fp:
                tree = ET.parse(fp)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: List[str] = []
        for p in tree.findall(".//w:p", ns):
            runs = [t.text for t in p.findall(".//w:t", ns) if t.text]
            line = "".join(runs).strip()
            if line:
                paragraphs.append(line)
        return "\n".join(paragraphs).strip()
    except Exception:
        return ""


def _read_pdf_text(path: Path) -> str:
    try:
        import fitz  # type: ignore

        parts: List[str] = []
        with fitz.open(path) as doc:
            for page in doc:
                txt = (page.get_text() or "").strip()
                if txt:
                    parts.append(txt)
        if parts:
            return "\n\n".join(parts).strip()
    except Exception:
        pass

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        parts: List[str] = []
        for page in reader.pages:
            txt = (page.extract_text() or "").strip()
            if txt:
                parts.append(txt)
        return "\n\n".join(parts).strip()
    except Exception:
        return ""


def _read_report_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    if suffix == ".docx":
        return _read_docx_text(path)
    if suffix == ".pdf":
        return _read_pdf_text(path)
    return ""


def _resolve_report_ingest_scope(filter_dir: Path, doc_files: List[Path]) -> Optional[Dict[str, Any]]:
    if not doc_files:
        return None

    resolved_files = sorted({str(p.expanduser().resolve()) for p in doc_files})
    parent_dirs = {str(Path(p).parent) for p in resolved_files}
    ingest_dir = filter_dir.resolve() if len(parent_dirs) != 1 else Path(next(iter(parent_dirs)))

    return {
        "report_dir": str(ingest_dir),
        "report_files": resolved_files,
        "file_count": len(resolved_files),
    }


def _count_nodes_by_labels(labels: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    with get_session() as session:
        for label in labels:
            row = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
            counts[label] = int((row and row.get("c")) or 0)
    return counts


def _resolve_graph_capability(enable_entity: bool, enable_llm_extraction: bool, counts: Dict[str, int]) -> Dict[str, Any]:
    structure_labels = ["Post", "Chunk", "Topic", "Event"]
    semantic_labels = ["Entity", "Claim", "Finding"]
    semantic_count = sum(int(counts.get(label, 0) or 0) for label in semantic_labels)
    structure_count = sum(int(counts.get(label, 0) or 0) for label in structure_labels)

    if semantic_count > 0:
        mode = "full_graphrag"
        summary = "已构建可检索的 Finding/Claim/Entity 语义图。"
    elif structure_count > 0:
        mode = "structural_only"
        if enable_entity and not enable_llm_extraction:
            summary = "已构建结构图，但未形成完整语义层；当前未启用 LLM 抽取，GraphRAG 处于弱化模式。"
        else:
            summary = "已构建基础结构图，但语义节点不足，当前仅适合弱化图检索。"
    else:
        mode = "empty"
        summary = "图构建未产出可用节点。"

    return {
        "mode": mode,
        "summary": summary,
        "is_degraded": mode != "full_graphrag",
        "llm_extraction_enabled": bool(enable_llm_extraction),
        "entity_extraction_enabled": bool(enable_entity),
    }


def sync_after_upload(
    topic: str,
    date: str,
    dataset_name: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
    *,
    init_schema_if_missing: bool = True,
    enable_entity_extraction: bool = False,
    enable_chunk_embedding: bool = False,
    enable_llm_extraction: bool = False,
    source_bucket: str = "filter",
) -> Dict[str, Any]:
    """
    在 Upload 成功后调用：将本批 MySQL 数据同步到 Neo4j。
    topic、date、dataset_name 与 upload_filtered_excels 一致。
    仅同步 Post、Account、Platform 及 POSTED、IN_PLATFORM；
    若 enable_entity_extraction / enable_chunk_embedding 为 True 则调用对应模块（见后续实现）。
    """
    if logger is None:
        logger = setup_logger(topic, date)
    log_module_start(logger, "GraphSync")

    if not is_neo4j_configured():
        log_error(logger, "Neo4j 未配置，跳过图同步", "GraphSync")
        return {"status": "skipped", "message": "Neo4j 未配置"}

    target_database = (dataset_name or topic).strip() or topic

    # Handle custom source path
    doc_files: List[Path] = []
    if source_bucket == "custom" and dataset_name:
        custom_path = Path(dataset_name)
        if custom_path.is_file():
            filter_dir = custom_path.parent
            # Only process this specific file
            if custom_path.suffix.lower() == '.jsonl':
                jsonl_files = [custom_path]
                csv_files = []
                doc_files = []
            elif custom_path.suffix.lower() == '.csv':
                jsonl_files = []
                csv_files = [custom_path]
                doc_files = []
            elif custom_path.suffix.lower() in REPORT_FILE_SUFFIXES:
                jsonl_files = []
                csv_files = []
                doc_files = [custom_path]
            else:
                log_error(logger, f"不支持的文件类型: {custom_path}", "GraphSync")
                return {"status": "error", "message": "不支持的文件类型"}
        elif custom_path.is_dir():
            filter_dir = custom_path
            jsonl_files = list(filter_dir.rglob("*.jsonl"))
            csv_files = list(filter_dir.rglob("*.csv"))
            doc_files = [
                p for p in filter_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in REPORT_FILE_SUFFIXES and not p.name.startswith("._")
            ]
        else:
            log_error(logger, f"路径不存在: {custom_path}", "GraphSync")
            return {"status": "error", "message": "路径不存在"}
    else:
        filter_dir = bucket(source_bucket, topic, date)
        jsonl_files = list(filter_dir.glob("*.jsonl")) if filter_dir.exists() else []
        csv_files = list(filter_dir.glob("*.csv")) if filter_dir.exists() else []
        doc_files = []

    if not jsonl_files and not csv_files and not doc_files:
        log_error(logger, f"未找到 {source_bucket} 产物 {filter_dir} (jsonl/csv/pdf/docx/txt/md)", "GraphSync")
        return {"status": "error", "message": f"未找到 {source_bucket} 产物"}

    files_to_process = []
    if jsonl_files:
        files_to_process.extend([(f, 'jsonl') for f in jsonl_files])
    if csv_files:
        files_to_process.extend([(f, 'csv') for f in csv_files])
    if doc_files:
        files_to_process.extend([(f, 'doc') for f in doc_files])

    engine = None
    try:
        engine = db_manager.get_engine_for_database(target_database)
    except Exception as exc:
        if jsonl_files:
            log_error(logger, f"无法连接 MySQL 数据库 {target_database}: {exc}", "GraphSync")
            return {"status": "error", "message": str(exc)}
        else:
            LOG.warning(f"无法连接 MySQL ({exc})，将尝试直接读取本地文件")

    cfg = get_graph_config()
    graph_database = str(cfg.get("database") or "").strip() or None
    batch_size = int(cfg.get("sync_batch_size") or 1000)
    chunk_size = int(cfg.get("chunk_size") or 512)
    chunk_overlap = int(cfg.get("chunk_overlap") or 50)
    enable_entity = bool(cfg.get("enable_entity_extraction", False)) or enable_entity_extraction
    enable_chunk = bool(cfg.get("enable_chunk_embedding", False)) or enable_chunk_embedding
    if enable_entity and not enable_chunk:
        enable_chunk = True
        LOG.warning("enable_entity_extraction=True while chunk embedding disabled; forcing enable_chunk_embedding=True")

    try:
        if init_schema_if_missing:
            init_schema()
    except Exception as exc:
        log_error(logger, f"Neo4j 连接或初始化失败: {exc}", "GraphSync")
        return {"status": "error", "message": str(exc)}

    total_posts = 0
    total_chunks = 0
    total_mentions = 0
    report_layer_result: Optional[Dict[str, Any]] = None
    with get_session() as session:
        for file_path, file_type in files_to_process:
            table_name = file_path.stem
            channel = table_name
            df = None

            try:
                if file_type == 'jsonl' and engine:
                    df = pd.read_sql(f"SELECT * FROM `{table_name}`", con=engine)
                elif file_type == 'csv':
                    df = pd.read_csv(file_path)
                    if 'id' not in df.columns and 'post_id' in df.columns:
                        df['id'] = df['post_id']
                elif file_type == 'doc':
                    channel = "report_data"
                    contents = _read_report_file(file_path)
                    if not str(contents or "").strip():
                        LOG.warning("文档文本为空，跳过: %s", file_path)
                        continue
                    rid = "report_" + hashlib.md5(str(file_path.resolve()).encode("utf-8")).hexdigest()[:16]
                    df = pd.DataFrame(
                        [
                            {
                                "id": rid,
                                "author": "report_source",
                                "title": file_path.stem,
                                "contents": contents,
                                "platform": "report",
                                "published_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                                "url": str(file_path.resolve()),
                                "region": "",
                                "hit_words": "",
                                "polarity": "",
                                "classification": "报告",
                            }
                        ]
                    )
                elif file_type == 'jsonl':
                    LOG.warning(f"Skipping {file_path} because MySQL engine is not available")
                    continue
            except Exception as exc:
                log_error(logger, f"读取数据失败 {file_path}: {exc}", "GraphSync")
                continue

            if df is None or len(df) == 0:
                continue

            expected_cols = ['id', 'author', 'title', 'contents', 'platform', 'published_at', 'url', 'region', 'hit_words', 'polarity', 'classification']
            for col in expected_cols:
                if col not in df.columns:
                    df[col] = None

            total_rows = len(df)
            print(f"开始处理 {file_path.name}, 共 {total_rows} 条数据 (Start processing {total_rows} rows)...")

            process_batch_size = 20 if enable_llm_extraction else batch_size

            for start in range(0, len(df), process_batch_size):
                batch = df.iloc[start : start + process_batch_size]

                for idx, row in batch.iterrows():
                    post_id_raw = row.get("id")
                    if post_id_raw is None or str(post_id_raw).strip() == "":
                        continue
                    post_global_id = _post_global_id(topic, channel, _safe_str(post_id_raw))
                    author = _safe_str(row.get("author"))
                    account_id = _account_id(topic, author)

                    row_platform = _safe_str(row.get("platform"))
                    actual_platform = row_platform if row_platform else channel

                    session.run(
                        "MERGE (p:Platform {name: $name}) SET p.name = $name",
                        {"name": actual_platform},
                    )
                    session.run(
                        """
                        MERGE (a:Account {id: $id})
                        SET a.topic = $topic, a.author = $author
                        """,
                        {"id": account_id, "topic": topic, "author": author or "__unknown__"},
                    )
                    session.run(
                        """
                        MERGE (p:Post {id: $id})
                        SET p.topic = $topic, p.channel = $channel,
                            p.title = $title, p.contents = $contents, p.platform = $platform,
                            p.author = $author, p.published_at = $published_at, p.url = $url,
                            p.region = $region, p.hit_words = $hit_words, p.polarity = $polarity,
                            p.classification = $classification
                        """,
                        {
                            "id": post_global_id,
                            "topic": topic,
                            "channel": channel,
                            "title": _safe_str(row.get("title")),
                            "contents": _safe_str(row.get("contents")),
                            "platform": actual_platform,
                            "author": author or "__unknown__",
                            "published_at": _safe_ts(row.get("published_at")),
                            "url": _safe_str(row.get("url")),
                            "region": _safe_str(row.get("region")),
                            "hit_words": _safe_str(row.get("hit_words")),
                            "polarity": _safe_str(row.get("polarity")),
                            "classification": _safe_str(row.get("classification")) or "未知",
                        },
                    )
                    session.run(
                        """
                        MATCH (a:Account {id: $aid}), (p:Post {id: $pid})
                        MERGE (a)-[:POSTED]->(p)
                        """,
                        {"aid": account_id, "pid": post_global_id},
                    )
                    session.run(
                        """
                        MATCH (p:Post {id: $pid}), (pl:Platform {name: $name})
                        MERGE (p)-[:IN_PLATFORM]->(pl)
                        """,
                        {"pid": post_global_id, "name": actual_platform},
                    )
                    total_posts += 1

                    row_dict = row.to_dict() if hasattr(row, "to_dict") else dict(row)

                    if enable_chunk:
                        try:
                            n = chunk_module.write_chunks_for_post(
                                topic, channel,
                                str(post_id_raw), _safe_str(row.get("contents")),
                                chunk_size=chunk_size,
                                chunk_overlap=chunk_overlap,
                            )
                            total_chunks += n
                        except Exception as e:
                            LOG.warning("Chunk for post %s failed: %s", post_global_id, e)

                    if enable_entity:
                        try:
                            m, _ = entity_module.run_entity_extraction_for_sync(
                                topic, channel, [row_dict],
                                enable_llm=enable_llm_extraction,
                                pre_fetched_llm_result=None,
                                chunk_size=chunk_size,
                                chunk_overlap=chunk_overlap,
                            )
                            total_mentions += m
                        except Exception as e:
                            LOG.warning("Entity/Topic for post %s failed: %s", post_global_id, e)

                    if total_posts % 50 == 0:
                        print(f"  已处理 {total_posts}/{total_rows} 条 Post (Processed {total_posts}/{total_rows})...")

        log_success(logger, f"图同步完成: Post={total_posts}, Chunk={total_chunks}, MENTIONS={total_mentions} (Graph sync completed)", "GraphSync")

    if engine is not None:
        engine.dispose()

    report_scope = _resolve_report_ingest_scope(filter_dir, doc_files)
    if report_scope:
        try:
            from .report_layer import ingest_report_directory_to_report_layer

            report_layer_result = ingest_report_directory_to_report_layer(
                project_topic=topic,
                report_dir=report_scope["report_dir"],
                report_files=report_scope["report_files"],
                rebuild=False,
            )
            log_success(
                logger,
                (
                    "报告层构建完成: "
                    f"files={report_layer_result.get('written_reports', 0)}, "
                    f"findings={report_layer_result.get('written_findings', 0)}, "
                    f"recommendations={report_layer_result.get('written_recommendations', 0)}"
                ),
                "GraphSync",
            )
        except Exception as exc:
            log_error(logger, f"报告层构建失败: {exc}", "GraphSync")
            report_layer_result = {
                "status": "error",
                "message": str(exc),
                "report_dir": report_scope["report_dir"],
                "report_files": report_scope["report_files"],
            }

    graph_counts = _count_nodes_by_labels(["Post", "Chunk", "Entity", "Claim", "Topic", "Event", "Finding"])
    graph_capability = _resolve_graph_capability(enable_entity, enable_llm_extraction, graph_counts)
    backfill_result = backfill_graph_node_embeddings(
        graph_database,
        labels=["Entity", "Claim", "Event", "Topic", "Finding"],
    )

    return {
        "status": "ok",
        "message": f"已同步 {total_posts} 条 Post (Synced {total_posts} posts)",
        "total_posts": total_posts,
        "total_chunks": total_chunks,
        "total_mentions": total_mentions,
        "counts": {
            "posts": total_posts,
            "chunks": total_chunks,
            "mentions": total_mentions,
            "graph_nodes": graph_counts,
        },
        "extraction": {
            "mode": "llm" if enable_llm_extraction else ("naive" if enable_entity else "disabled"),
            "entity_extraction_enabled": bool(enable_entity),
            "chunk_embedding_enabled": bool(enable_chunk),
            "llm_extraction_enabled": bool(enable_llm_extraction),
        },
        "graph_capability": graph_capability,
        "report_layer": report_layer_result
        or {
            "status": "skipped",
            "message": "未检测到报告类文件，跳过报告层构建",
        },
        "vector_backfill": backfill_result,
    }
