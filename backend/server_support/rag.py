"""RAG helpers for resolving per-project storage paths and auto-building indices."""
from __future__ import annotations

import csv
import json
import random
import shutil
import threading
import time
import zipfile
from xml.etree import ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import lancedb

from src.graph.neo4j_client import get_session
from src.utils.io.excel import read_jsonl
from src.utils.logging.logging import log_error, log_success, setup_logger
from src.utils.rag.ragrouter.router_vec_data import run_ragrouter
from src.utils.rag.tagrag.tag_vec_data import to_pinyin, vectorize_and_store
from src.utils.setting.paths import get_data_root

_RAG_BUILD_STATUS: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
_RAG_BUILD_THREADS: Dict[Tuple[str, str, str], threading.Thread] = {}
_RAG_BUILD_LOCK = threading.Lock()


def _project_data_root(project: str) -> Optional[Path]:
    project = str(project or "").strip()
    if not project:
        return None
    project_dir = get_data_root() / "projects" / project
    if not project_dir.exists():
        return None
    return project_dir


def _project_rag_root(project: str) -> Optional[Path]:
    project_dir = _project_data_root(project)
    if not project_dir:
        return None
    rag_root = project_dir / "rag"
    rag_root.mkdir(parents=True, exist_ok=True)
    return rag_root


def _status_key(project: str, rag_type: str, topic: str) -> Tuple[str, str, str]:
    return (project, rag_type, topic)


def _update_status(project: str, rag_type: str, topic: str, status: str, percent: int, message: str) -> None:
    with _RAG_BUILD_LOCK:
        _RAG_BUILD_STATUS[_status_key(project, rag_type, topic)] = {
            "status": status,
            "percent": max(0, min(100, int(percent))),
            "message": message,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def _neo4j_vector_index_names(database: Optional[str] = None) -> List[str]:
    with get_session(database=database) as session:
        try:
            rows = session.run("SHOW VECTOR INDEXES YIELD name RETURN name").data()
            return [str(row.get("name")) for row in rows if row.get("name")]
        except Exception:
            rows = session.run("SHOW INDEXES YIELD name, type WHERE type = 'VECTOR' RETURN name").data()
            return [str(row.get("name")) for row in rows if row.get("name")]


def _expert_index_ready() -> bool:
    required_index = "expert_entity_embedding_index"
    try:
        names = _neo4j_vector_index_names(database="opinion-expert")
    except Exception as exc:
        if "Database does not exist" not in str(exc) and "database management is not supported" not in str(exc):
            return False
        try:
            names = _neo4j_vector_index_names(database=None)
        except Exception:
            return False
    return required_index in names


def get_rag_build_status(project: str, rag_type: str, topic: str) -> Dict[str, Any]:
    key = _status_key(project, rag_type, topic)
    with _RAG_BUILD_LOCK:
        status = _RAG_BUILD_STATUS.get(key)
    status_payload = dict(status) if isinstance(status, dict) else {
        "status": "idle",
        "percent": 0,
        "message": "",
        "updated_at": None,
    }

    if status_payload.get("status") != "running":
        return status_payload

    with _RAG_BUILD_LOCK:
        thread = _RAG_BUILD_THREADS.get(key)
    if thread is not None and thread.is_alive():
        return status_payload

    if ensure_rag_ready(project, rag_type, topic):
        _update_status(project, rag_type, topic, "done", 100, "准备完成")
    else:
        _update_status(project, rag_type, topic, "error", 100, "构建中断，请重试")

    with _RAG_BUILD_LOCK:
        status = _RAG_BUILD_STATUS.get(key)
    return dict(status) if isinstance(status, dict) else status_payload


def _tagrag_db_ready(topic: str, project: str) -> bool:
    rag_root = _project_rag_root(project)
    if not rag_root:
        return False
    vector_dir = rag_root / "tagrag" / "vector_db"
    if not vector_dir.exists():
        return False
    try:
        db = lancedb.connect(str(vector_dir))
        return to_pinyin(topic) in db.table_names()
    except Exception:
        return False


def _routerrag_db_ready(topic: str, project: str) -> bool:
    rag_root = _project_rag_root(project)
    if not rag_root:
        return False
    vector_dir = rag_root / "routerrag" / f"{topic}数据库" / "vector_db"
    if not vector_dir.exists():
        return False
    try:
        db = lancedb.connect(str(vector_dir))
        table_names = set(db.table_names())
        # RouterRAG 最低可用要求：至少存在 normalrag 表。
        # 仅检查“目录存在/有任意表”会误判，导致前端显示可检索但实际召回为空。
        return "normalrag" in table_names
    except Exception:
        return False


def list_project_tagrag_topics(project: str) -> List[str]:
    rag_root = _project_rag_root(project)
    if not rag_root:
        return []
    format_dir = rag_root / "tagrag" / "format_db"
    if not format_dir.exists():
        return []
    return [p.stem for p in format_dir.glob("*.json") if p.stem]


def list_project_routerrag_topics(project: str) -> List[str]:
    rag_root = _project_rag_root(project)
    if not rag_root:
        return []
    router_root = rag_root / "routerrag"
    if not router_root.exists():
        return []
    topics: List[str] = []
    for child in router_root.iterdir():
        if not child.is_dir():
            continue
        if (child / "normal_db").exists() or (child / "vector_db").exists():
            topics.append(child.name.replace("数据库", ""))
    return topics


def import_routerrag_artifacts(project: str, topic: str, source_path: str) -> Dict[str, Any]:
    """Import existing RouterRAG Lance artifacts into a project topic."""
    project = str(project or "").strip()
    topic = str(topic or "").strip()
    source_path = str(source_path or "").strip()
    if not project:
        raise ValueError("project is required")
    if not topic:
        raise ValueError("topic is required")
    if not source_path:
        raise ValueError("source_path is required")

    rag_root = _project_rag_root(project)
    if not rag_root:
        raise ValueError(f"project not found: {project}")

    src = Path(source_path).expanduser()
    if not src.is_absolute():
        src = (Path.cwd() / src).resolve()
    if not src.exists():
        raise FileNotFoundError(f"source path not found: {src}")

    topic_root = rag_root / "routerrag" / f"{topic}数据库"
    target_vector = topic_root / "vector_db"
    target_vector.mkdir(parents=True, exist_ok=True)

    imported_items: List[str] = []
    imported_count = 0

    def _copy_lance_dir(lance_dir: Path) -> None:
        nonlocal imported_count
        if not lance_dir.is_dir() or lance_dir.suffix.lower() != ".lance":
            return
        dst = target_vector / lance_dir.name
        shutil.copytree(lance_dir, dst, dirs_exist_ok=True)
        imported_items.append(str(dst))
        imported_count += 1

    if src.is_dir() and src.name == "vector_db":
        for child in src.iterdir():
            _copy_lance_dir(child)
        normal_src = src.parent / "normal_db"
        if normal_src.exists() and normal_src.is_dir():
            shutil.copytree(normal_src, topic_root / "normal_db", dirs_exist_ok=True)
    elif src.is_dir() and (src / "vector_db").exists():
        vector_src = src / "vector_db"
        for child in vector_src.iterdir():
            _copy_lance_dir(child)
        normal_src = src / "normal_db"
        if normal_src.exists() and normal_src.is_dir():
            shutil.copytree(normal_src, topic_root / "normal_db", dirs_exist_ok=True)
    elif src.is_dir() and src.suffix.lower() == ".lance":
        _copy_lance_dir(src)
    else:
        raise ValueError("source_path must be a .lance directory, vector_db directory, or topic root containing vector_db")

    tables: List[str] = []
    try:
        db = lancedb.connect(str(target_vector))
        tables = list(db.table_names())
    except Exception:
        tables = []

    return {
        "project": project,
        "topic": topic,
        "topic_path": str(topic_root),
        "vector_db_path": str(target_vector),
        "imported_count": imported_count,
        "imported_items": imported_items,
        "tables": tables,
    }


def _has_local_files(directory: Path) -> bool:
    if not directory.exists() or not directory.is_dir():
        return False
    patterns = ("*.jsonl", "*.csv", "*.txt", "*.md", "*.pdf", "*.docx")
    for pattern in patterns:
        if any(directory.rglob(pattern)):
            return True
    return False


def _resolve_local_source_dir(project: str, start: Optional[str], end: Optional[str]) -> Optional[Path]:
    project_dir = _project_data_root(project)
    if not project_dir:
        return None

    fetch_root = project_dir / "fetch"
    candidates: List[Path] = []

    if start:
        folder = start if not end or end == start else f"{start}_{end}"
        candidates.append(fetch_root / folder)

    if fetch_root.exists():
        fetch_candidates = sorted(
            [p for p in fetch_root.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates.extend(fetch_candidates)

    candidates.extend([
        project_dir / "uploads" / "jsonl",
        project_dir / "raw",
        project_dir / "merge",
        project_dir / "clean",
    ])

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if _has_local_files(candidate):
            return candidate
    return None


def _resolve_explicit_source_dir(project: str, source_dir: Optional[str]) -> Optional[Path]:
    """Resolve a user-provided source directory path.

    Supports:
    - absolute paths
    - relative paths (relative to cwd / data_root / project_dir)
    - shorthand "@report_data" -> data_root/report_data
    """
    raw = str(source_dir or "").strip()
    if not raw:
        return None

    if raw.startswith("@"):
        raw = raw[1:].strip()
    if not raw:
        return None

    project_dir = _project_data_root(project)
    data_root = get_data_root()

    if raw in {"report_data", "backend/data/report_data"}:
        candidate = data_root / "report_data"
        return candidate if _has_local_files(candidate) else None

    path = Path(raw).expanduser()
    candidates: List[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append((Path.cwd() / path).resolve())
        candidates.append((data_root / path).resolve())
        if project_dir:
            candidates.append((project_dir / path).resolve())

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if _has_local_files(candidate):
            return candidate
    return None


def _extract_texts_from_local(source_dir: Path) -> List[str]:
    text_cols = ["contents", "content", "text", "正文"]
    texts: List[str] = []
    seen: set[str] = set()

    def _add_text(value: object) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text or text in seen:
            return
        seen.add(text)
        texts.append(text)

    def _read_docx_text(path: Path) -> str:
        # Prefer python-docx if available.
        try:
            import docx  # type: ignore

            doc = docx.Document(str(path))
            parts = [p.text.strip() for p in doc.paragraphs if str(p.text or "").strip()]
            return "\n".join(parts).strip()
        except Exception:
            pass

        # Fallback: parse word/document.xml directly from docx zip package.
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
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            parts: List[str] = []
            for page in reader.pages:
                try:
                    page_text = page.extract_text() or ""
                except Exception:
                    page_text = ""
                if page_text.strip():
                    parts.append(page_text.strip())
            return "\n\n".join(parts).strip()
        except Exception:
            return ""

    for path in sorted(source_dir.rglob("*.jsonl")):
        df = None
        try:
            df = read_jsonl(path)
        except Exception:
            df = None
        if df is not None and not df.empty:
            text_col = next((c for c in text_cols if c in df.columns), None)
            if text_col:
                for value in df[text_col].fillna(""):
                    _add_text(value)
                continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(payload, dict):
                        for col in text_cols:
                            if col in payload:
                                _add_text(payload.get(col))
                                break
        except Exception:
            continue

    for csv_path in sorted(source_dir.rglob("*.csv")):
        try:
            with csv_path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    for col in text_cols:
                        if col in row:
                            _add_text(row.get(col))
                            break
        except Exception:
            continue

    for txt_path in sorted(source_dir.rglob("*.txt")):
        try:
            _add_text(txt_path.read_text(encoding="utf-8"))
        except Exception:
            continue

    for md_path in sorted(source_dir.rglob("*.md")):
        try:
            _add_text(md_path.read_text(encoding="utf-8"))
        except Exception:
            continue

    for docx_path in sorted(source_dir.rglob("*.docx")):
        try:
            _add_text(_read_docx_text(docx_path))
        except Exception:
            continue

    for pdf_path in sorted(source_dir.rglob("*.pdf")):
        try:
            _add_text(_read_pdf_text(pdf_path))
        except Exception:
            continue

    return texts


def ensure_tagrag_db(
    topic: str,
    project: str,
    fetch_dir: Optional[Path] = None,
    *,
    local_source_dir: Optional[Path] = None,
) -> Optional[Path]:
    rag_root = _project_rag_root(project)
    if not rag_root:
        return None

    source_dir = local_source_dir or fetch_dir
    tagrag_root = rag_root / "tagrag"
    format_dir = tagrag_root / "format_db"
    vector_dir = tagrag_root / "vector_db"
    format_dir.mkdir(parents=True, exist_ok=True)
    vector_dir.mkdir(parents=True, exist_ok=True)

    try:
        db = lancedb.connect(str(vector_dir))
        table_name = to_pinyin(topic)
        if table_name in db.table_names():
            _update_status(project, "tagrag", topic, "done", 100, "准备完成")
            return vector_dir
    except Exception:
        pass

    logger = setup_logger(f"TagRAG_{project}", "default")
    if source_dir is None:
        log_error(logger, f"未发现本地数据源，无法构建TagRAG: {project}", "TagRAG")
        _update_status(project, "tagrag", topic, "error", 100, "本地数据源不存在")
        return None

    _update_status(project, "tagrag", topic, "running", 10, "正在准备本地资料")
    texts = _extract_texts_from_local(source_dir)
    if not texts:
        log_error(logger, f"本地数据源无可用文本，无法构建TagRAG: {source_dir}", "TagRAG")
        _update_status(project, "tagrag", topic, "error", 100, "本地数据为空，构建失败")
        return None

    _update_status(project, "tagrag", topic, "running", 35, "正在整理内容")
    data = {"data": []}
    for idx, text in enumerate(texts):
        data["data"].append({"id": idx, "text": text, "tag": text})

    format_path = format_dir / f"{topic}.json"
    format_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log_success(logger, f"已生成TagRAG格式数据: {format_path}", "TagRAG")

    try:
        _update_status(project, "tagrag", topic, "running", 60, "正在建立索引")
        vectorize_and_store(topic_name=topic, format_json_path=str(format_path), vector_db_path=str(vector_dir))
        _update_status(project, "tagrag", topic, "done", 100, "准备完成")
        return vector_dir
    except Exception as exc:
        log_error(logger, f"TagRAG向量化失败: {exc}", "TagRAG")
        _update_status(project, "tagrag", topic, "error", 100, "准备失败，请稍后重试")
        return None


def ensure_routerrag_db(
    topic: str,
    project: str,
    fetch_dir: Optional[Path] = None,
    *,
    local_source_dir: Optional[Path] = None,
    sample_ratio: Optional[float] = None,
    chunk_mode: str = "sentence",
    chunk_size: int = 220,
    chunk_overlap: int = 40,
    force_rebuild: bool = False,
) -> Optional[Path]:
    rag_root = _project_rag_root(project)
    if not rag_root:
        return None

    source_dir = local_source_dir or fetch_dir
    base_path = rag_root / "routerrag" / f"{topic}数据库"
    vector_dir = base_path / "vector_db"
    if vector_dir.exists():
        if force_rebuild:
            try:
                shutil.rmtree(vector_dir, ignore_errors=True)
                shutil.rmtree(base_path / "normal_db", ignore_errors=True)
            except Exception:
                pass
        elif _routerrag_db_ready(topic, project):
            _update_status(project, "routerrag", topic, "done", 100, "准备完成")
            return base_path
        else:
            # 目录存在但索引不完整时强制重建，避免“假就绪”。
            try:
                shutil.rmtree(vector_dir, ignore_errors=True)
                shutil.rmtree(base_path / "normal_db", ignore_errors=True)
            except Exception:
                pass

    logger = setup_logger(f"RouterRAG_{project}", "default")
    if source_dir is None:
        log_error(logger, f"未发现本地数据源，无法构建RouterRAG: {project}", "RouterRAG")
        _update_status(project, "routerrag", topic, "error", 100, "本地数据源不存在")
        return None

    _update_status(project, "routerrag", topic, "running", 10, "正在准备本地资料")
    texts = _extract_texts_from_local(source_dir)
    if not texts:
        log_error(logger, f"本地数据源无可用文本，无法构建RouterRAG: {source_dir}", "RouterRAG")
        _update_status(project, "routerrag", topic, "error", 100, "本地数据为空，构建失败")
        return None

    if sample_ratio is not None:
        total_before_sample = len(texts)
        try:
            ratio = float(sample_ratio)
        except Exception:
            ratio = 1.0
        ratio = max(0.01, min(1.0, ratio))
        if ratio < 1.0 and len(texts) > 1:
            sample_n = max(1, int(len(texts) * ratio))
            rng = random.Random(42)
            idxs = sorted(rng.sample(range(len(texts)), sample_n))
            texts = [texts[i] for i in idxs]
            log_success(logger, f"RouterRAG采样完成: ratio={ratio:.2f}, 保留{sample_n}/{total_before_sample}", "RouterRAG")

    _update_status(project, "routerrag", topic, "running", 30, "正在整理内容")
    text_db = base_path / "normal_db" / "text_db"
    text_db.mkdir(parents=True, exist_ok=True)

    doc_pack_size = 3
    doc_id = 1
    for i in range(0, len(texts), doc_pack_size):
        chunk = texts[i: i + doc_pack_size]
        file_name = f"doc{doc_id}_{topic}_text1.txt"
        (text_db / file_name).write_text("\n\n---\n\n".join(chunk), encoding="utf-8")
        doc_id += 1

    try:
        _update_status(project, "routerrag", topic, "running", 70, "正在建立索引")
        ok = run_ragrouter(
            topic_name=topic,
            base_path=base_path,
            chunk_mode=chunk_mode,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        if ok:
            _update_status(project, "routerrag", topic, "done", 100, "准备完成")
            return base_path
        _update_status(project, "routerrag", topic, "error", 100, "准备失败，请稍后重试")
        return None
    except Exception as exc:
        log_error(logger, f"RouterRAG向量化失败: {exc}", "RouterRAG")
        _update_status(project, "routerrag", topic, "error", 100, "准备失败，请稍后重试")
        return None


def _ensure_expert_kg(project: str) -> bool:
    logger = setup_logger(f"ExpertBuild_{project}", "default")
    try:
        from src.expert_kg.pipeline import ExpertKGPipeline

        pipeline = ExpertKGPipeline()
        pipeline.run(rebuild=False)
    except Exception as exc:
        log_error(logger, f"专家库流水线执行失败: {exc}", "ExpertKG")
        return False

    if not _expert_index_ready():
        log_error(logger, "专家向量索引未就绪: expert_entity_embedding_index", "ExpertKG")
        return False
    return True


def start_rag_build(
    project: str,
    rag_type: str,
    topic: str,
    *,
    db_topic: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    local_source_dir: Optional[str] = None,
    sample_ratio: Optional[float] = None,
    chunk_mode: str = "sentence",
    chunk_size: int = 220,
    chunk_overlap: int = 40,
    force_rebuild: bool = False,
) -> Dict[str, Any]:
    key = _status_key(project, rag_type, topic)
    status = get_rag_build_status(project, rag_type, topic)
    if status.get("status") == "running":
        return status

    def _run() -> None:
        try:
            source_topic = db_topic or topic
            explicit_source_dir = _resolve_explicit_source_dir(project, local_source_dir)
            if local_source_dir and explicit_source_dir is None:
                _update_status(project, rag_type, topic, "error", 100, f"指定目录无可用数据: {local_source_dir}")
                return

            resolved_source_dir = explicit_source_dir or _resolve_local_source_dir(project, start, end)
            if resolved_source_dir is None:
                _update_status(project, rag_type, topic, "error", 100, "未找到本地可用数据源，未执行远程补数")
                return

            if rag_type == "tagrag":
                ensure_tagrag_db(source_topic, project, local_source_dir=resolved_source_dir)
                return

            if rag_type in {"routerrag", "routerrag_expert"}:
                _update_status(project, rag_type, topic, "running", 20, "正在构建RouterRAG本地索引")
                base_path = ensure_routerrag_db(
                    source_topic,
                    project,
                    local_source_dir=resolved_source_dir,
                    sample_ratio=sample_ratio,
                    chunk_mode=chunk_mode,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    force_rebuild=force_rebuild,
                )
                if not base_path:
                    _update_status(project, rag_type, topic, "error", 100, "RouterRAG构建失败")
                    return

                if rag_type == "routerrag_expert":
                    _update_status(project, rag_type, topic, "running", 80, "正在构建专家库索引")
                    if not _ensure_expert_kg(project):
                        _update_status(project, rag_type, topic, "error", 100, "专家库构建失败")
                        return

                _update_status(project, rag_type, topic, "done", 100, "准备完成")
                return

            _update_status(project, rag_type, topic, "error", 100, f"不支持的构建类型: {rag_type}")
        except Exception:
            _update_status(project, rag_type, topic, "error", 100, "准备失败，请稍后重试")
        finally:
            with _RAG_BUILD_LOCK:
                _RAG_BUILD_THREADS.pop(key, None)

    _update_status(project, rag_type, topic, "running", 5, "开始准备")
    thread = threading.Thread(target=_run, daemon=True)
    with _RAG_BUILD_LOCK:
        _RAG_BUILD_THREADS[key] = thread
    thread.start()
    return get_rag_build_status(project, rag_type, topic)


def ensure_rag_ready(project: str, rag_type: str, topic: str) -> bool:
    if rag_type == "tagrag":
        return _tagrag_db_ready(topic, project)
    if rag_type == "routerrag_expert":
        return _routerrag_db_ready(topic, project) and _expert_index_ready()
    return _routerrag_db_ready(topic, project)
