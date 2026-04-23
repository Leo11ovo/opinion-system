"""Build and maintain a 5-node-type Planning Graph from local expert documents."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.graph.neo4j_client import get_session
from src.utils.ai.qwen import QwenClient
from src.utils.logging.logging import log_error, log_success, setup_logger

logger = setup_logger("PlanningGraphBuilder", "default")

PLANNING_LABELS = ["Scenario", "Goal", "Dimension", "Task", "Method"]
REL_TYPES = ["HAS_GOAL", "FOCUS_ON", "REQUIRES_TASK", "SOLVED_BY", "NEXT"]


def _safe_read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    if suffix == ".docx":
        try:
            import docx  # type: ignore

            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if str(p.text).strip())
        except Exception:
            return ""
    if suffix == ".pdf":
        try:
            import fitz  # type: ignore

            text = ""
            with fitz.open(path) as doc:
                for page in doc:
                    text += page.get_text()
            if text.strip():
                return text
        except Exception:
            pass
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            return ""
    return ""


class PlanningGraphBuilder:
    def __init__(
        self,
        *,
        data_root: Optional[Path] = None,
        model: str = "qwen-plus",
        chunk_size: int = 4000,
        chunk_overlap: int = 500,
    ) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.data_root = data_root or (project_root / "data" / "expert")
        self.research_root = self.data_root / "研究文章"
        self.vocab_dir = self.data_root / "planning_vocab"
        self.next_whitelist_path = self.data_root / "planning_next_whitelist.json"
        self.state_path = self.data_root / "planning_build_state.json"
        self.translation_cache_path = self.data_root / "planning_translation_cache.json"
        self.extract_results_path = self.data_root / "planning_extract_results.jsonl"
        self.client = QwenClient()
        self.model = model
        self.chunk_size = max(1000, int(chunk_size))
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size // 2))

    def _chunk_content(self, content: str) -> List[str]:
        text = str(content or "").strip()
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [text]
        chunks: List[str] = []
        step = max(1, self.chunk_size - self.chunk_overlap)
        for start in range(0, len(text), step):
            part = text[start: start + self.chunk_size].strip()
            if part:
                chunks.append(part)
            if start + self.chunk_size >= len(text):
                break
        return chunks

    @staticmethod
    def _dedup_str_list(values: List[Any]) -> List[str]:
        out: List[str] = []
        seen = set()
        for v in values:
            s = str(v or "").strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    @staticmethod
    def _dedup_edges(edges: List[Dict[str, Any]], fields: Tuple[str, str]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        seen = set()
        a, b = fields
        for edge in edges:
            src = str(edge.get(a) or "").strip()
            tgt = str(edge.get(b) or "").strip()
            if not src or not tgt:
                continue
            key = (src.lower(), tgt.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({a: src, b: tgt})
        return out

    @staticmethod
    def _dedup_spans(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for row in spans:
            if not isinstance(row, dict):
                continue
            span_type = str(row.get("type") or "").strip()
            name = str(row.get("name") or "").strip()
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            key = (span_type.lower(), name.lower(), text)
            if key in seen:
                continue
            seen.add(key)
            item: Dict[str, Any] = {"type": span_type, "name": name, "text": text}
            offset = row.get("offset")
            if isinstance(offset, list) and len(offset) == 2:
                item["offset"] = offset
            out.append(item)
        return out

    @staticmethod
    def _merge_hints(base: Dict[str, Any], inc: Dict[str, Any]) -> Dict[str, List[str]]:
        def _as_list(x: Any) -> List[str]:
            if isinstance(x, list):
                return [str(v).strip() for v in x if str(v or "").strip()]
            return []

        return {
            "keywords": PlanningGraphBuilder._dedup_str_list(_as_list(base.get("keywords")) + _as_list(inc.get("keywords"))),
            "exclude": PlanningGraphBuilder._dedup_str_list(_as_list(base.get("exclude")) + _as_list(inc.get("exclude"))),
            "time_terms": PlanningGraphBuilder._dedup_str_list(_as_list(base.get("time_terms")) + _as_list(inc.get("time_terms"))),
        }

    @staticmethod
    def _record_has_entities(rec: Dict[str, Any]) -> bool:
        if not isinstance(rec, dict):
            return False
        total = 0
        total += len(rec.get("scenario", []) or [])
        total += len(rec.get("goals", []) or [])
        total += len(rec.get("dimensions", []) or [])
        total += len(rec.get("tasks", []) or [])
        total += len(rec.get("methods", []) or [])
        return total > 0

    def _append_extract_record(self, row: Dict[str, Any]) -> None:
        self.extract_results_path.parent.mkdir(parents=True, exist_ok=True)
        with self.extract_results_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _ensure_vocab_files(self) -> None:
        self.vocab_dir.mkdir(parents=True, exist_ok=True)
        for kind in ("scenario", "goal", "dimension", "task", "method"):
            path = self.vocab_dir / f"{kind}.json"
            if not path.exists():
                path.write_text("[]", encoding="utf-8")
        if not self.next_whitelist_path.exists():
            self.next_whitelist_path.write_text("[]", encoding="utf-8")
        if not self.translation_cache_path.exists():
            self.translation_cache_path.write_text("{}", encoding="utf-8")

    def _load_vocab(self) -> Dict[str, List[Dict[str, Any]]]:
        self._ensure_vocab_files()
        vocab: Dict[str, List[Dict[str, Any]]] = {}
        for kind in ("scenario", "goal", "dimension", "task", "method"):
            path = self.vocab_dir / f"{kind}.json"
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                vocab[kind] = payload if isinstance(payload, list) else []
            except Exception:
                vocab[kind] = []
        return vocab

    def _save_vocab(self, vocab: Dict[str, List[Dict[str, Any]]]) -> None:
        self._ensure_vocab_files()
        for kind, rows in vocab.items():
            (self.vocab_dir / f"{kind}.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _load_translation_cache(self) -> Dict[str, str]:
        self._ensure_vocab_files()
        try:
            payload = json.loads(self.translation_cache_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return {str(k): str(v) for k, v in payload.items()}
        except Exception:
            pass
        return {}

    def _save_translation_cache(self, cache: Dict[str, str]) -> None:
        self.translation_cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _contains_chinese(text: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))

    @staticmethod
    def _looks_english(text: str) -> bool:
        s = str(text or "").strip()
        if not s:
            return False
        if re.search(r"[\u4e00-\u9fff]", s):
            return False
        return bool(re.search(r"[A-Za-z]", s))

    async def _translate_en_to_zh(self, text: str) -> str:
        prompt = f"""
把下面这个舆情分析术语翻译成简洁中文短语（2~12字），只输出中文短语本身，不要解释：
{text}
"""
        resp = await self.client.call(prompt=prompt, model=self.model, max_tokens=60)
        if not resp or not resp.get("text"):
            return text
        out = str(resp["text"]).strip().splitlines()[0].strip("：: \t")
        out = re.sub(r"[\"'`]", "", out).strip()
        return out or text

    async def _to_zh_canonical_async(self, token: str, translation_cache: Dict[str, str]) -> str:
        s = str(token or "").strip()
        if not s:
            return ""
        if self._contains_chinese(s):
            return s
        if not self._looks_english(s):
            return s
        key = s.lower()
        if key in translation_cache:
            return translation_cache[key]
        zh = await self._translate_en_to_zh(s)
        zh = str(zh or s).strip()
        if not self._contains_chinese(zh):
            zh = s
        translation_cache[key] = zh
        return zh

    @staticmethod
    def _normalize_one(text: str, bucket: List[Dict[str, Any]]) -> str:
        token = str(text or "").strip()
        if not token:
            return ""
        t = token.lower()
        for row in bucket:
            canonical = str(row.get("canonical") or "").strip()
            aliases = [str(a).strip().lower() for a in (row.get("aliases") or [])]
            if t == canonical.lower() or t in aliases:
                return canonical
        return token

    @staticmethod
    def _append_vocab(bucket: List[Dict[str, Any]], token: str, source: str) -> None:
        s = str(token or "").strip()
        if not s:
            return
        for row in bucket:
            if str(row.get("canonical") or "").strip().lower() == s.lower():
                sources = set(row.get("source_docs") or [])
                sources.add(source)
                row["source_docs"] = sorted(sources)
                row["lang"] = "zh"
                return
        bucket.append({
            "canonical": s,
            "aliases": [s],
            "source_docs": [source],
            "lang": "zh",
        })

    async def _extract_plan_from_doc(self, title: str, content: str) -> Dict[str, Any]:
        prompt = f"""
你是舆情分析规划知识抽取器。请从文档提取规划图谱元素。
只输出JSON，不要解释。

约束：
1) 仅使用五类节点：Scenario, Goal, Dimension, Task, Method
2) 仅使用关系：HAS_GOAL, FOCUS_ON, REQUIRES_TASK, SOLVED_BY
3) 不要生成 NEXT（NEXT 由白名单维护）
4) 每个字段尽量短语化，避免长句
5) Method 必须是可由文本检索直接支持的分析动作，不要输出数学公式编号/纯理论模型名
6) 输出必须基于文档证据，无法确定就留空

文档标题：
{title}

文档内容（截断）：
{content[:10000]}

输出格式：
{{
  "scenario": ["..."],
  "goals": ["..."],
  "dimensions": ["..."],
  "tasks": ["..."],
  "methods": ["..."],
  "evidence_spans": [
    {{"type":"task|method|dimension|goal|scenario","name":"...","text":"原文短片段","offset":[0,120]}}
  ],
  "retrieval_hints": {{
    "keywords": ["..."],
    "exclude": ["..."],
    "time_terms": ["..."]
  }},
  "edges": {{
    "has_goal": [{{"scenario":"...","goal":"..."}}],
    "focus_on": [{{"goal":"...","dimension":"..."}}],
    "requires_task": [{{"goal":"...","task":"..."}}],
    "solved_by": [{{"task":"...","method":"..."}}]
  }}
}}
"""
        resp = await self.client.call(prompt=prompt, model=self.model, max_tokens=1800)
        if not resp or not resp.get("text"):
            return {}
        txt = str(resp["text"])
        m = re.search(r"\{[\s\S]*\}", txt)
        if not m:
            return {}
        try:
            payload = json.loads(m.group(0))
            if isinstance(payload, dict):
                payload.setdefault("evidence_spans", [])
                payload.setdefault("retrieval_hints", {})
                if not isinstance(payload["evidence_spans"], list):
                    payload["evidence_spans"] = []
                if not isinstance(payload["retrieval_hints"], dict):
                    payload["retrieval_hints"] = {}
                payload["retrieval_hints"].setdefault("keywords", [])
                payload["retrieval_hints"].setdefault("exclude", [])
                payload["retrieval_hints"].setdefault("time_terms", [])
                return payload
        except Exception:
            return {}
        return {}

    def _merge_chunk_payloads(self, payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        scenarios: List[Any] = []
        goals: List[Any] = []
        dimensions: List[Any] = []
        tasks: List[Any] = []
        methods: List[Any] = []
        has_goal: List[Dict[str, Any]] = []
        focus_on: List[Dict[str, Any]] = []
        requires_task: List[Dict[str, Any]] = []
        solved_by: List[Dict[str, Any]] = []
        evidence_spans: List[Dict[str, Any]] = []
        retrieval_hints: Dict[str, Any] = {"keywords": [], "exclude": [], "time_terms": []}

        for p in payloads:
            if not isinstance(p, dict):
                continue
            scenarios.extend(p.get("scenario", []) or [])
            goals.extend(p.get("goals", []) or [])
            dimensions.extend(p.get("dimensions", []) or [])
            tasks.extend(p.get("tasks", []) or [])
            methods.extend(p.get("methods", []) or [])
            edges = p.get("edges", {}) or {}
            has_goal.extend(edges.get("has_goal", []) or [])
            focus_on.extend(edges.get("focus_on", []) or [])
            requires_task.extend(edges.get("requires_task", []) or [])
            solved_by.extend(edges.get("solved_by", []) or [])
            evidence_spans.extend(p.get("evidence_spans", []) or [])
            retrieval_hints = self._merge_hints(retrieval_hints, p.get("retrieval_hints", {}) or {})

        return {
            "scenario": self._dedup_str_list(scenarios),
            "goals": self._dedup_str_list(goals),
            "dimensions": self._dedup_str_list(dimensions),
            "tasks": self._dedup_str_list(tasks),
            "methods": self._dedup_str_list(methods),
            "edges": {
                "has_goal": self._dedup_edges(has_goal, ("scenario", "goal")),
                "focus_on": self._dedup_edges(focus_on, ("goal", "dimension")),
                "requires_task": self._dedup_edges(requires_task, ("goal", "task")),
                "solved_by": self._dedup_edges(solved_by, ("task", "method")),
            },
            "evidence_spans": self._dedup_spans(evidence_spans),
            "retrieval_hints": retrieval_hints,
        }

    def _collect_documents(self) -> List[Path]:
        if not self.research_root.exists():
            return []
        docs: List[Path] = []
        for p in sorted(self.research_root.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".pdf", ".docx", ".txt", ".md"} and not p.name.startswith("._"):
                docs.append(p)
        return docs

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"docs": {}}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("docs"), dict):
                return payload
        except Exception:
            pass
        return {"docs": {}}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_session(self):
        try:
            return get_session(database="opinion-expert")
        except Exception:
            return get_session()

    def _reset_planning_graph(self) -> None:
        with self._get_session() as session:
            session.run(
                """
                MATCH (n)
                WHERE any(l IN labels(n) WHERE l IN ['Scenario','Goal','Dimension','Task','Method'])
                DETACH DELETE n
                """
            )

    def _upsert_records(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return
        with self._get_session() as session:
            for rec in records:
                for s in rec.get("scenario", []):
                    session.run("MERGE (:Scenario:ExpertNode {name:$name})", {"name": s})
                for g in rec.get("goals", []):
                    session.run("MERGE (:Goal:ExpertNode {name:$name})", {"name": g})
                for d in rec.get("dimensions", []):
                    session.run("MERGE (:Dimension:ExpertNode {name:$name})", {"name": d})
                for t in rec.get("tasks", []):
                    session.run(
                        """
                        MERGE (n:Task:ExpertNode {name:$name})
                        SET n.hint_keywords = coalesce(n.hint_keywords, []) + $keywords,
                            n.hint_exclude = coalesce(n.hint_exclude, []) + $exclude,
                            n.hint_time_terms = coalesce(n.hint_time_terms, []) + $time_terms
                        """,
                        {
                            "name": t,
                            "keywords": rec.get("retrieval_hints", {}).get("keywords", []),
                            "exclude": rec.get("retrieval_hints", {}).get("exclude", []),
                            "time_terms": rec.get("retrieval_hints", {}).get("time_terms", []),
                        },
                    )
                for m in rec.get("methods", []):
                    session.run(
                        """
                        MERGE (n:Method:ExpertNode {name:$name})
                        SET n.hint_keywords = coalesce(n.hint_keywords, []) + $keywords,
                            n.hint_exclude = coalesce(n.hint_exclude, []) + $exclude,
                            n.hint_time_terms = coalesce(n.hint_time_terms, []) + $time_terms
                        """,
                        {
                            "name": m,
                            "keywords": rec.get("retrieval_hints", {}).get("keywords", []),
                            "exclude": rec.get("retrieval_hints", {}).get("exclude", []),
                            "time_terms": rec.get("retrieval_hints", {}).get("time_terms", []),
                        },
                    )

                edges = rec.get("edges", {})
                for e in edges.get("has_goal", []):
                    session.run(
                        "MATCH (s:Scenario {name:$s}) "
                        "MATCH (g:Goal {name:$g}) "
                        "MERGE (s)-[:HAS_GOAL]->(g)",
                        {"s": e.get("scenario"), "g": e.get("goal")},
                    )
                for e in edges.get("focus_on", []):
                    session.run(
                        "MATCH (g:Goal {name:$g}) "
                        "MATCH (d:Dimension {name:$d}) "
                        "MERGE (g)-[:FOCUS_ON]->(d)",
                        {"g": e.get("goal"), "d": e.get("dimension")},
                    )
                for e in edges.get("requires_task", []):
                    session.run(
                        "MATCH (g:Goal {name:$g}) "
                        "MATCH (t:Task {name:$t}) "
                        "MERGE (g)-[:REQUIRES_TASK]->(t)",
                        {"g": e.get("goal"), "t": e.get("task")},
                    )
                for e in edges.get("solved_by", []):
                    session.run(
                        "MATCH (t:Task {name:$t}) "
                        "MATCH (m:Method {name:$m}) "
                        "MERGE (t)-[:SOLVED_BY]->(m)",
                        {"t": e.get("task"), "m": e.get("method")},
                    )

    def _apply_next_whitelist(self) -> None:
        try:
            whitelist = json.loads(self.next_whitelist_path.read_text(encoding="utf-8"))
        except Exception:
            whitelist = []
        with self._get_session() as session:
            for row in whitelist:
                src = str(row.get("from_task") or "").strip()
                tgt = str(row.get("to_task") or "").strip()
                if not src or not tgt:
                    continue
                session.run(
                    """
                    MATCH (a:Task {name:$src})
                    MATCH (b:Task {name:$tgt})
                    MERGE (a)-[r:NEXT]->(b)
                    SET r.source = 'whitelist'
                    """,
                    {"src": src, "tgt": tgt},
                )

    def build(
        self,
        *,
        resume: bool = True,
        force_reextract: bool = False,
        flush_every_docs: int = 5,
    ) -> Dict[str, Any]:
        docs = self._collect_documents()
        if not docs:
            return {"status": "error", "message": f"未找到研究文章目录: {self.research_root}"}

        total_docs = len(docs)
        print(f"[PlanningGraph] Found {total_docs} documents.", flush=True)
        if force_reextract and self.extract_results_path.exists():
            self.extract_results_path.unlink()
            print("[PlanningGraph] Cleared extract jsonl due to --force-reextract", flush=True)

        vocab = self._load_vocab()
        translation_cache = self._load_translation_cache()
        state = self._load_state() if resume else {"docs": {}}
        doc_state: Dict[str, Any] = state.get("docs", {})
        if force_reextract:
            # Force re-extract must ignore any stale checkpoint entries;
            # otherwise a later resume run may incorrectly "reuse" old docs.
            doc_state = {}
            state = {"docs": {}}
        records: List[Dict[str, Any]] = []
        pending_records: List[Dict[str, Any]] = []
        failed_docs = [0]
        reused_count = [0]
        flush_every_docs = max(1, int(flush_every_docs))
        self._reset_planning_graph()

        async def _run_all() -> None:
            for doc_idx, doc in enumerate(docs, 1):
                doc_key = str(doc.resolve())
                doc_mtime = int(doc.stat().st_mtime) if doc.exists() else 0
                if resume and not force_reextract:
                    cached = doc_state.get(doc_key)
                    cached_record = cached.get("record") if isinstance(cached, dict) else None
                    if (
                        isinstance(cached, dict)
                        and str(cached.get("status", "ok")) == "ok"
                        and int(cached.get("mtime", -1)) == doc_mtime
                        and isinstance(cached_record, dict)
                        and self._record_has_entities(cached_record)
                    ):
                        records.append(cached["record"])
                        pending_records.append(cached["record"])
                        reused_count[0] += 1
                        print(
                            f"[PlanningGraph] Reuse {doc_idx}/{total_docs} ({doc_idx/total_docs*100:.1f}%): {doc.name}",
                            flush=True,
                        )
                        if len(pending_records) >= flush_every_docs:
                            self._upsert_records(pending_records)
                            print(f"[PlanningGraph] Flush graph batch: {len(pending_records)} docs", flush=True)
                            pending_records.clear()
                        continue

                text = _safe_read_text(doc)
                if not text.strip():
                    print(f"[PlanningGraph] Skip empty doc: {doc.name}", flush=True)
                    continue
                chunks = self._chunk_content(text)
                chunk_payloads: List[Dict[str, Any]] = []
                total_chunks = len(chunks)
                print(
                    f"[PlanningGraph] Doc {doc_idx}/{total_docs} ({doc_idx/total_docs*100:.1f}%): "
                    f"{doc.name} | chunks={total_chunks}",
                    flush=True,
                )
                for idx, chunk in enumerate(chunks, 1):
                    parsed_chunk = await self._extract_plan_from_doc(f"{doc.name}#chunk{idx}", chunk)
                    if parsed_chunk:
                        chunk_payloads.append(parsed_chunk)
                    if idx == total_chunks or idx % 5 == 0:
                        print(
                            f"[PlanningGraph]   chunk {idx}/{total_chunks} "
                            f"({idx/max(1,total_chunks)*100:.1f}%)",
                            flush=True,
                        )
                parsed = self._merge_chunk_payloads(chunk_payloads)
                if not parsed:
                    print(f"[PlanningGraph] No planning entities extracted: {doc.name}", flush=True)
                    failed_docs[0] += 1
                    doc_state[doc_key] = {
                        "mtime": doc_mtime,
                        "status": "failed",
                        "reason": "empty_parse_payload",
                        "record": {},
                        "updated_at": datetime.now().isoformat(),
                    }
                    if resume:
                        state["docs"] = doc_state
                        self._save_state(state)
                    continue
                # alias normalize + language normalize (await translation in async loop)
                scenario: List[str] = []
                for x in parsed.get("scenario", []):
                    scenario.append(await self._to_zh_canonical_async(self._normalize_one(x, vocab["scenario"]), translation_cache))

                goals: List[str] = []
                for x in parsed.get("goals", []):
                    goals.append(await self._to_zh_canonical_async(self._normalize_one(x, vocab["goal"]), translation_cache))

                dimensions: List[str] = []
                for x in parsed.get("dimensions", []):
                    dimensions.append(await self._to_zh_canonical_async(self._normalize_one(x, vocab["dimension"]), translation_cache))

                tasks: List[str] = []
                for x in parsed.get("tasks", []):
                    tasks.append(await self._to_zh_canonical_async(self._normalize_one(x, vocab["task"]), translation_cache))

                methods: List[str] = []
                for x in parsed.get("methods", []):
                    methods.append(await self._to_zh_canonical_async(self._normalize_one(x, vocab["method"]), translation_cache))

                for s in scenario:
                    self._append_vocab(vocab["scenario"], s, doc.name)
                for g in goals:
                    self._append_vocab(vocab["goal"], g, doc.name)
                for d in dimensions:
                    self._append_vocab(vocab["dimension"], d, doc.name)
                for t in tasks:
                    self._append_vocab(vocab["task"], t, doc.name)
                for m in methods:
                    self._append_vocab(vocab["method"], m, doc.name)

                current_record = {
                    "scenario": sorted({x for x in scenario if x}),
                    "goals": sorted({x for x in goals if x}),
                    "dimensions": sorted({x for x in dimensions if x}),
                    "tasks": sorted({x for x in tasks if x}),
                    "methods": sorted({x for x in methods if x}),
                    "edges": parsed.get("edges", {}),
                    "evidence_spans": parsed.get("evidence_spans", []),
                    "retrieval_hints": parsed.get("retrieval_hints", {"keywords": [], "exclude": [], "time_terms": []}),
                    "source_doc": doc.name,
                }
                if not self._record_has_entities(current_record):
                    print(f"[PlanningGraph] No usable entities extracted: {doc.name}", flush=True)
                    failed_docs[0] += 1
                    doc_state[doc_key] = {
                        "mtime": doc_mtime,
                        "status": "failed",
                        "reason": "zero_entities_after_normalize",
                        "record": {},
                        "updated_at": datetime.now().isoformat(),
                    }
                    if resume:
                        state["docs"] = doc_state
                        self._save_state(state)
                    continue

                records.append(current_record)
                self._append_extract_record(
                    {
                        "doc_id": doc_key,
                        "file_name": doc.name,
                        "scenario": records[-1]["scenario"],
                        "goals": records[-1]["goals"],
                        "dimensions": records[-1]["dimensions"],
                        "tasks": records[-1]["tasks"],
                        "methods": records[-1]["methods"],
                        "evidence_spans": records[-1]["evidence_spans"],
                        "retrieval_hints": records[-1]["retrieval_hints"],
                        "updated_at": datetime.now().isoformat(),
                    }
                )
                pending_records.append(records[-1])
                doc_state[doc_key] = {
                    "mtime": doc_mtime,
                    "status": "ok",
                    "record": records[-1],
                    "updated_at": datetime.now().isoformat(),
                }
                if resume:
                    state["docs"] = doc_state
                    self._save_state(state)
                print(
                    f"[PlanningGraph]   extracted: S={len(scenario)} G={len(goals)} D={len(dimensions)} "
                    f"T={len(tasks)} M={len(methods)}",
                    flush=True,
                )
                if len(pending_records) >= flush_every_docs:
                    self._upsert_records(pending_records)
                    print(f"[PlanningGraph] Flush graph batch: {len(pending_records)} docs", flush=True)
                    pending_records.clear()

            if pending_records:
                self._upsert_records(pending_records)
                print(f"[PlanningGraph] Final flush graph batch: {len(pending_records)} docs", flush=True)
                pending_records.clear()

        asyncio.run(_run_all())

        if not records:
            return {"status": "error", "message": "未抽取到有效规划节点"}

        self._save_vocab(vocab)
        self._save_translation_cache(translation_cache)
        self._apply_next_whitelist()
        if resume:
            state["docs"] = doc_state
            state["last_build_at"] = datetime.now().isoformat()
            state["last_build_records"] = len(records)
            self._save_state(state)

        summary = {
            "scenario": len(vocab["scenario"]),
            "goal": len(vocab["goal"]),
            "dimension": len(vocab["dimension"]),
            "task": len(vocab["task"]),
            "method": len(vocab["method"]),
        }
        log_success(logger, f"Planning Graph构建完成: {summary}", "PlanningGraph")
        return {
            "status": "ok",
            "records": len(records),
            "reused": reused_count[0],
            "failed": failed_docs[0],
            "vocab_summary": summary,
        }
