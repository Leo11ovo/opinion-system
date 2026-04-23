"""
Report layer graph helpers.

Design goal:
- Keep evidence layer unchanged (Post/Chunk/Entity/Claim + existing relations).
- Add a lightweight report layer for quarterly storytelling and structured output.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .neo4j_client import get_session
from .sync_mysql_to_neo4j import _read_report_file


def _slug(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9\-_]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "na"


def _h(text: str, n: int = 10) -> str:
    return hashlib.md5(str(text or "").encode("utf-8")).hexdigest()[:n]


# -----------------------------
# ID generation rules
# -----------------------------
def report_id(topic: str, quarter: str, title: str) -> str:
    return f"{topic}_report_{_slug(quarter)}_{_h(title)}"


def section_id(report_node_id: str, section_name: str, order: int) -> str:
    return f"{report_node_id}_section_{int(order)}_{_h(section_name)}"


def finding_id(report_node_id: str, section_node_id: str, text: str, index: int) -> str:
    return f"{report_node_id}_finding_{int(index)}_{_h(section_node_id + '|' + text)}"


def recommendation_id(report_node_id: str, text: str, index: int) -> str:
    return f"{report_node_id}_rec_{int(index)}_{_h(text)}"


def metric_id(report_node_id: str, metric_name: str, index: int) -> str:
    return f"{report_node_id}_metric_{int(index)}_{_h(metric_name)}"


def report_topic_id(topic: str, topic_name: str) -> str:
    return f"{topic}_report_topic_{_h(topic_name)}"


def report_event_id(report_node_id: str, event_name: str, index: int = 1) -> str:
    return f"{report_node_id}_event_{int(index)}_{_h(event_name)}"


# -----------------------------
# Node payloads
# -----------------------------
@dataclass
class ReportNode:
    id: str
    topic: str
    title: str
    quarter: str
    summary: str = ""
    period_start: str = ""
    period_end: str = ""
    source_doc: str = ""
    created_at: str = ""


@dataclass
class SectionNode:
    id: str
    report_id: str
    name: str
    order: int
    summary: str = ""


@dataclass
class FindingNode:
    id: str
    report_id: str
    section_id: str
    title: str
    statement: str
    confidence: float = 0.8
    severity: str = "medium"


@dataclass
class RecommendationNode:
    id: str
    report_id: str
    title: str
    action: str
    priority: str = "P2"
    owner: str = ""


@dataclass
class MetricNode:
    id: str
    report_id: str
    name: str
    value: str
    unit: str = ""
    period: str = ""
    source: str = "report"


# -----------------------------
# Upsert node functions
# -----------------------------
def upsert_report(node: ReportNode) -> None:
    now = node.created_at or datetime.now().isoformat()
    with get_session() as session:
        session.run(
            """
            MERGE (r:Report {id: $id})
            SET r.topic = $topic,
                r.title = $title,
                r.quarter = $quarter,
                r.summary = $summary,
                r.period_start = $period_start,
                r.period_end = $period_end,
                r.source_doc = $source_doc,
                r.source = 'report_layer',
                r.created_at = coalesce(r.created_at, $created_at),
                r.updated_at = $created_at
            """,
            {
                "id": node.id,
                "topic": node.topic,
                "title": node.title,
                "quarter": node.quarter,
                "summary": node.summary,
                "period_start": node.period_start,
                "period_end": node.period_end,
                "source_doc": node.source_doc,
                "created_at": now,
            },
        )


def upsert_section(node: SectionNode) -> None:
    with get_session() as session:
        session.run(
            """
            MERGE (s:Section {id: $id})
            SET s.report_id = $report_id,
                s.name = $name,
                s.section_order = $section_order,
                s.summary = $summary,
                s.source = 'report_layer'
            """,
            {
                "id": node.id,
                "report_id": node.report_id,
                "name": node.name,
                "section_order": int(node.order),
                "summary": node.summary,
            },
        )


def upsert_finding(node: FindingNode) -> None:
    with get_session() as session:
        session.run(
            """
            MERGE (f:Finding {id: $id})
            SET f.report_id = $report_id,
                f.section_id = $section_id,
                f.title = $title,
                f.statement = $statement,
                f.confidence = $confidence,
                f.severity = $severity,
                f.source = 'report_layer'
            """,
            {
                "id": node.id,
                "report_id": node.report_id,
                "section_id": node.section_id,
                "title": node.title,
                "statement": node.statement,
                "confidence": float(node.confidence),
                "severity": node.severity,
            },
        )


def upsert_recommendation(node: RecommendationNode) -> None:
    with get_session() as session:
        session.run(
            """
            MERGE (r:Recommendation {id: $id})
            SET r.report_id = $report_id,
                r.title = $title,
                r.action = $action,
                r.priority = $priority,
                r.owner = $owner,
                r.source = 'report_layer'
            """,
            {
                "id": node.id,
                "report_id": node.report_id,
                "title": node.title,
                "action": node.action,
                "priority": node.priority,
                "owner": node.owner,
            },
        )


def upsert_platform(platform_name: str) -> None:
    with get_session() as session:
        session.run(
            "MERGE (p:Platform {name: $name}) SET p.name = $name",
            {"name": str(platform_name or "").strip()},
        )


def upsert_topic(topic_node_id: str, topic_name: str, project_topic: str) -> None:
    with get_session() as session:
        session.run(
            """
            MERGE (t:Topic {id: $id})
            SET t.name = $name,
                t.project = $project,
                t.level = coalesce(t.level, 'report'),
                t.source = coalesce(t.source, 'report_layer')
            """,
            {"id": topic_node_id, "name": topic_name, "project": project_topic},
        )


def upsert_event(event_node_id: str, event_name: str, project_topic: str, summary: str = "") -> None:
    with get_session() as session:
        session.run(
            """
            MERGE (e:Event {id: $id})
            SET e.name = $name,
                e.project = $project,
                e.summary = $summary,
                e.source = coalesce(e.source, 'report_layer')
            """,
            {"id": event_node_id, "name": event_name, "project": project_topic, "summary": summary},
        )


def upsert_metric(node: MetricNode) -> None:
    with get_session() as session:
        session.run(
            """
            MERGE (m:Metric {id: $id})
            SET m.report_id = $report_id,
                m.name = $name,
                m.value = $value,
                m.unit = $unit,
                m.period = $period,
                m.metric_source = $metric_source,
                m.source = 'report_layer'
            """,
            {
                "id": node.id,
                "report_id": node.report_id,
                "name": node.name,
                "value": node.value,
                "unit": node.unit,
                "period": node.period,
                "metric_source": node.source,
            },
        )


# -----------------------------
# Report layer relationships
# -----------------------------
def rel_report_has_section(report_node_id: str, section_node_id: str) -> None:
    _merge_rel("Report", report_node_id, "HAS_SECTION", "Section", section_node_id)


def rel_report_has_recommendation(report_node_id: str, rec_node_id: str) -> None:
    _merge_rel("Report", report_node_id, "HAS_RECOMMENDATION", "Recommendation", rec_node_id)


def rel_section_analyzes_platform(section_node_id: str, platform_name: str) -> None:
    _merge_rel_by_name("Section", section_node_id, "ANALYZES_PLATFORM", "Platform", platform_name)


def rel_section_has_finding(section_node_id: str, finding_node_id: str) -> None:
    _merge_rel("Section", section_node_id, "HAS_FINDING", "Finding", finding_node_id)


def rel_finding_about_platform(finding_node_id: str, platform_name: str) -> None:
    _merge_rel_by_name("Finding", finding_node_id, "ABOUT_PLATFORM", "Platform", platform_name)


def rel_finding_about_topic(finding_node_id: str, topic_node_id: str) -> None:
    _merge_rel("Finding", finding_node_id, "ABOUT_TOPIC", "Topic", topic_node_id)


def rel_finding_supported_by_metric(finding_node_id: str, metric_node_id: str) -> None:
    _merge_rel("Finding", finding_node_id, "SUPPORTED_BY", "Metric", metric_node_id)


def rel_finding_supported_by_event(finding_node_id: str, event_node_id: str) -> None:
    _merge_rel("Finding", finding_node_id, "SUPPORTED_BY_EVENT", "Event", event_node_id)


def rel_recommendation_for_platform(rec_node_id: str, platform_name: str) -> None:
    _merge_rel_by_name("Recommendation", rec_node_id, "FOR_PLATFORM", "Platform", platform_name)


def rel_recommendation_addresses_topic(rec_node_id: str, topic_node_id: str) -> None:
    _merge_rel("Recommendation", rec_node_id, "ADDRESSES_TOPIC", "Topic", topic_node_id)


def rel_recommendation_responds_to(rec_node_id: str, finding_node_id: str) -> None:
    _merge_rel("Recommendation", rec_node_id, "RESPONDS_TO", "Finding", finding_node_id)


def rel_event_relates_to_topic(event_node_id: str, topic_node_id: str) -> None:
    _merge_rel("Event", event_node_id, "RELATES_TO_TOPIC", "Topic", topic_node_id)


# -----------------------------
# Bridge relationships
# -----------------------------
def bridge_finding_supported_by_post(finding_node_id: str, post_node_id: str) -> None:
    _merge_rel("Finding", finding_node_id, "SUPPORTED_BY_POST", "Post", post_node_id)


def bridge_finding_supported_by_chunk(finding_node_id: str, chunk_node_id: str) -> None:
    _merge_rel("Finding", finding_node_id, "SUPPORTED_BY_CHUNK", "Chunk", chunk_node_id)


def bridge_finding_derived_from_claim(finding_node_id: str, claim_node_id: str) -> None:
    _merge_rel("Finding", finding_node_id, "DERIVED_FROM", "Claim", claim_node_id)


def bridge_event_evidenced_by_post(event_node_id: str, post_node_id: str) -> None:
    _merge_rel("Event", event_node_id, "EVIDENCED_BY", "Post", post_node_id)


def bridge_event_evidenced_by_claim(event_node_id: str, claim_node_id: str) -> None:
    _merge_rel("Event", event_node_id, "EVIDENCED_BY", "Claim", claim_node_id)


def bridge_claim_about_topic(claim_node_id: str, topic_node_id: str) -> None:
    _merge_rel("Claim", claim_node_id, "ABOUT_TOPIC", "Topic", topic_node_id)


def bridge_claim_about_event(claim_node_id: str, event_node_id: str) -> None:
    _merge_rel("Claim", claim_node_id, "ABOUT_EVENT", "Event", event_node_id)


def bridge_claim_mentions_entity(claim_node_id: str, entity_node_id: str) -> None:
    _merge_rel("Claim", claim_node_id, "MENTIONS", "Entity", entity_node_id)


def backfill_claim_mentions_entity(topic: Optional[str] = None) -> int:
    """
    Supplement relation:
    (Claim)<-[:HAS_CLAIM]-(Chunk)-[:MENTIONS]->(Entity) => (Claim)-[:MENTIONS]->(Entity)
    """
    where = ""
    params: Dict[str, Any] = {}
    if topic:
        where = "WHERE cl.topic = $topic OR e.topic = $topic OR ch.topic = $topic"
        params["topic"] = topic
    with get_session() as session:
        result = session.run(
            f"""
            MATCH (ch:Chunk)-[:HAS_CLAIM]->(cl:Claim)
            MATCH (ch)-[:MENTIONS]->(e:Entity)
            {where}
            MERGE (cl)-[r:MENTIONS]->(e)
            RETURN count(r) AS c
            """,
            params,
        )
        row = result.single()
        return int(row["c"] if row else 0)


def _merge_rel(src_label: str, src_id: str, rel_type: str, dst_label: str, dst_id: str) -> None:
    with get_session() as session:
        session.run(
            f"""
            MATCH (a:{src_label} {{id: $src_id}})
            MATCH (b:{dst_label} {{id: $dst_id}})
            MERGE (a)-[:{rel_type}]->(b)
            """,
            {"src_id": src_id, "dst_id": dst_id},
        )


def _merge_rel_by_name(src_label: str, src_id: str, rel_type: str, dst_label: str, dst_name: str) -> None:
    with get_session() as session:
        session.run(
            f"""
            MATCH (a:{src_label} {{id: $src_id}})
            MATCH (b:{dst_label} {{name: $dst_name}})
            MERGE (a)-[:{rel_type}]->(b)
            """,
            {"src_id": src_id, "dst_name": dst_name},
        )


def write_minimal_quarterly_report_example(
    *,
    project_topic: str,
    quarter: str,
    report_title: str,
    platform_name: str,
    topic_name: str,
    finding_statement: str,
    recommendation_action: str,
    metric_name: str,
    metric_value: str,
    metric_unit: str = "%",
    evidence_post_id: Optional[str] = None,
    evidence_chunk_id: Optional[str] = None,
    evidence_claim_id: Optional[str] = None,
) -> Dict[str, str]:
    """
    Minimal fixed-shape quarterly report write example.
    """
    rid = report_id(project_topic, quarter, report_title)
    sid = section_id(rid, "总体态势", 1)
    fid = finding_id(rid, sid, finding_statement, 1)
    rec_id = recommendation_id(rid, recommendation_action, 1)
    mid = metric_id(rid, metric_name, 1)
    tid = report_topic_id(project_topic, topic_name)
    eid = report_event_id(rid, f"{topic_name}-代表事件", 1)

    upsert_report(
        ReportNode(
            id=rid,
            topic=project_topic,
            title=report_title,
            quarter=quarter,
            summary=f"{quarter}季度报告（最小示例）",
        )
    )
    upsert_section(SectionNode(id=sid, report_id=rid, name="总体态势", order=1))
    upsert_finding(
        FindingNode(
            id=fid,
            report_id=rid,
            section_id=sid,
            title="核心发现",
            statement=finding_statement,
        )
    )
    upsert_recommendation(
        RecommendationNode(
            id=rec_id,
            report_id=rid,
            title="重点建议",
            action=recommendation_action,
        )
    )
    upsert_metric(
        MetricNode(
            id=mid,
            report_id=rid,
            name=metric_name,
            value=str(metric_value),
            unit=metric_unit,
            period=quarter,
        )
    )
    upsert_platform(platform_name)
    upsert_topic(tid, topic_name, project_topic)
    upsert_event(eid, f"{topic_name}-代表事件", project_topic)

    rel_report_has_section(rid, sid)
    rel_report_has_recommendation(rid, rec_id)
    rel_section_analyzes_platform(sid, platform_name)
    rel_section_has_finding(sid, fid)
    rel_finding_about_platform(fid, platform_name)
    rel_finding_about_topic(fid, tid)
    rel_finding_supported_by_metric(fid, mid)
    rel_finding_supported_by_event(fid, eid)
    rel_recommendation_for_platform(rec_id, platform_name)
    rel_recommendation_addresses_topic(rec_id, tid)
    rel_recommendation_responds_to(rec_id, fid)
    rel_event_relates_to_topic(eid, tid)

    if evidence_post_id:
        bridge_finding_supported_by_post(fid, evidence_post_id)
        bridge_event_evidenced_by_post(eid, evidence_post_id)
    if evidence_chunk_id:
        bridge_finding_supported_by_chunk(fid, evidence_chunk_id)
    if evidence_claim_id:
        bridge_finding_derived_from_claim(fid, evidence_claim_id)
        bridge_event_evidenced_by_claim(eid, evidence_claim_id)
        bridge_claim_about_topic(evidence_claim_id, tid)
        bridge_claim_about_event(evidence_claim_id, eid)

    return {
        "report_id": rid,
        "section_id": sid,
        "finding_id": fid,
        "recommendation_id": rec_id,
        "metric_id": mid,
        "topic_id": tid,
        "event_id": eid,
    }


def _infer_quarter(filename: str, fallback_date: Optional[datetime] = None) -> str:
    text = str(filename or "")
    year_match = re.search(r"(20\d{2})", text)
    year = year_match.group(1) if year_match else str((fallback_date or datetime.now()).year)
    if "第一季度" in text or "一季度" in text or "Q1" in text.upper():
        return f"{year}Q1"
    if "第二季度" in text or "二季度" in text or "Q2" in text.upper():
        return f"{year}Q2"
    if "第三季度" in text or "三季度" in text or "Q3" in text.upper():
        return f"{year}Q3"
    if "第四季度" in text or "四季度" in text or "Q4" in text.upper():
        return f"{year}Q4"
    if "上半年" in text:
        return f"{year}H1"
    if "下半年" in text:
        return f"{year}H2"
    return f"{year}ANNUAL"


def _normalize_title(path: Path) -> str:
    title = path.stem
    title = re.sub(r"\s+", " ", title).strip()
    return title or path.name


def _topic_from_title(title: str, default_topic_name: str = "综合舆情") -> str:
    t = str(title or "")
    if "交通" in t:
        return "交通舆情"
    if "控烟" in t or "烟" in t:
        return "控烟舆情"
    if "疫情" in t:
        return "公共卫生舆情"
    if "京津冀" in t:
        return "区域协同舆情"
    return default_topic_name


def _recommendation_from_text(text: str) -> str:
    content = str(text or "")
    if not content:
        return "建立季度复盘与风险预警机制。"
    if "建议" in content or "应对" in content or "治理" in content:
        return "基于报告发现，推进分平台响应与分级处置机制。"
    return "围绕核心风险点建立监测、研判、响应闭环。"


def _evidence_post_id(project_topic: str, path: Path) -> str:
    rid = "report_" + hashlib.md5(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"{project_topic}_report_data_{rid}"


def _pick_one_claim_for_post(post_id: str) -> Optional[str]:
    with get_session() as session:
        row = session.run(
            """
            MATCH (p:Post {id: $pid})-[:HAS_CLAIM]->(c:Claim)
            RETURN c.id AS cid
            ORDER BY c.id
            LIMIT 1
            """,
            {"pid": post_id},
        ).single()
        return str(row["cid"]) if row and row.get("cid") else None


def _safe_metric_value(text: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", str(text or ""))
    if m:
        return m.group(1)
    return "N/A"


def clear_report_layer(project_topic: Optional[str] = None) -> int:
    """
    Remove report-layer nodes only, leaving evidence layer intact.
    """
    params: Dict[str, Any] = {}
    topic_filter = "true"
    if project_topic:
        topic_filter = "(coalesce(n.topic, '') = $topic OR coalesce(n.project, '') = $topic OR coalesce(n.report_id, '') CONTAINS $topic)"
        params["topic"] = project_topic
    with get_session() as session:
        row = session.run(
            """
            MATCH (n)
            WHERE any(l IN labels(n) WHERE l IN ['Report', 'Section', 'Finding', 'Recommendation', 'Metric'])
              AND """ + topic_filter + """
            WITH collect(n) AS nodes, count(n) AS c
            FOREACH (x IN nodes | DETACH DELETE x)
            RETURN c
            """,
            params,
        ).single()
        return int(row["c"] if row else 0)


def _clean_text(text: str) -> str:
    return re.sub(r"\r\n?", "\n", str(text or "")).strip()


def _split_lines(text: str) -> List[str]:
    return [line.strip() for line in _clean_text(text).split("\n") if line.strip()]


def _is_heading(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    patterns = [
        r"^第[一二三四五六七八九十百]+[章节部分篇].*",
        r"^[0-9]+(\.[0-9]+){0,2}\s+.+",
        r"^[0-9]+[、.．]\s*.+",
        r"^[一二三四五六七八九十]+[、.．]\s*.+",
        r"^(摘要|概述|综述|背景|现状|问题|建议|对策|结论|总结|启示|分析|风险提示).*$",
    ]
    return any(re.match(p, text) for p in patterns)


def _split_sections(content: str, title: str) -> List[Tuple[str, str]]:
    lines = _split_lines(content)
    if not lines:
        return [("全文", "")]

    sections: List[Tuple[str, List[str]]] = []
    current_title = "导言"
    current_lines: List[str] = []

    for line in lines:
        if _is_heading(line) and current_lines:
            sections.append((current_title, current_lines))
            current_title = line[:80]
            current_lines = []
            continue
        if _is_heading(line) and not current_lines and current_title == "导言":
            current_title = line[:80]
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))

    normalized = [(name or "未命名章节", "\n".join(chunk).strip()) for name, chunk in sections if "\n".join(chunk).strip()]
    if not normalized:
        normalized = [("全文", _clean_text(content))]

    # Avoid generating too many tiny sections from noisy OCR headings.
    merged: List[Tuple[str, str]] = []
    for name, text in normalized:
        if len(text) < 80 and merged:
            prev_name, prev_text = merged[-1]
            merged[-1] = (prev_name, f"{prev_text}\n{text}".strip())
        else:
            merged.append((name, text))
    return merged[:12]


def _extract_recommendation_blocks(content: str) -> List[str]:
    lines = _split_lines(content)
    recs: List[str] = []
    capture = False
    buffer: List[str] = []
    for line in lines:
        if any(key in line for key in ("建议", "对策", "应对", "治理", "举措")) and _is_heading(line):
            if buffer:
                recs.append(" ".join(buffer).strip())
                buffer = []
            capture = True
            continue
        if capture and _is_heading(line):
            if buffer:
                recs.append(" ".join(buffer).strip())
            capture = False
            buffer = []
        if capture:
            buffer.append(line)
    if buffer:
        recs.append(" ".join(buffer).strip())
    recs = [r for r in recs if len(r) >= 20]
    return recs[:6]


def _extract_metric_candidates(text: str) -> List[Tuple[str, str, str]]:
    metrics: List[Tuple[str, str, str]] = []
    content = str(text or "")
    for m in re.finditer(r"([^\n，。；;:：]{0,24}?)(\d+(?:\.\d+)?)\s*(%|万|亿|件|条|次|篇|个)", content):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" :：,，;；()（）") or "指标"
        value = m.group(2)
        unit = m.group(3)
        metrics.append((name[:30], value, unit))
    unique: List[Tuple[str, str, str]] = []
    seen = set()
    for item in metrics:
        key = (item[0], item[1], item[2])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:5]


def _platform_candidates(title: str, text: str, default_platform: str) -> List[str]:
    mapping = {
        "微博": ["微博"],
        "微信": ["微信"],
        "视频": ["视频", "短视频", "抖音", "快手"],
        "新闻APP": ["新闻app", "新闻客户端", "客户端"],
        "新闻网站": ["新闻网站", "门户网站", "网站"],
        "论坛": ["论坛", "贴吧", "社区"],
        "自媒体": ["自媒体", "公众号", "博主", "up主"],
    }
    source = f"{title}\n{text}".lower()
    platforms: List[str] = []
    for platform_name, terms in mapping.items():
        if any(term.lower() in source for term in terms):
            platforms.append(platform_name)
    if not platforms and default_platform:
        platforms.append(default_platform)
    return platforms[:3]


def _topic_candidates(title: str, section_name: str, text: str, default_topic_name: str) -> List[str]:
    candidates = [_topic_from_title(title, default_topic_name=default_topic_name)]
    checks = {
        "交通舆情": ["交通", "出行", "客运", "铁路", "地铁", "公交", "高速"],
        "控烟舆情": ["控烟", "烟草", "电子烟", "禁烟", "吸烟"],
        "公共卫生舆情": ["疫情", "防疫", "卫生", "健康"],
        "区域协同舆情": ["京津冀", "区域协同", "一体化"],
        "企业声誉舆情": ["董事长", "企业", "品牌", "舆情态势"],
    }
    source = f"{title}\n{section_name}\n{text}"
    for topic_name, terms in checks.items():
        if any(term in source for term in terms):
            candidates.append(topic_name)
    result: List[str] = []
    for name in candidates:
        if name not in result:
            result.append(name)
    return result[:3]


def _event_candidates(title: str, text: str) -> List[str]:
    title = str(title or "").strip()
    events: List[str] = []
    if "事件" in title or "被投诉" in title or "留置" in title:
        events.append(title)
    if "疫情" in title:
        events.append(f"{title}-疫情相关事件")
    result: List[str] = []
    for name in events:
        if name and name not in result:
            result.append(name)
    return result[:2]


def _finding_points(section_text: str) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}|[。！？]", str(section_text or "")) if len(p.strip()) >= 24]
    if not paragraphs:
        cleaned = re.sub(r"\s+", " ", str(section_text or "")).strip()
        return [cleaned[:180]] if cleaned else []
    scored = sorted(paragraphs, key=lambda x: len(x), reverse=True)
    return [re.sub(r"\s+", " ", p).strip()[:200] for p in scored[:2]]


def ingest_report_directory_to_report_layer(
    *,
    project_topic: str,
    report_dir: str,
    report_files: Optional[List[str]] = None,
    default_platform: str = "报告",
    default_topic_name: str = "综合舆情",
    rebuild: bool = False,
) -> Dict[str, Any]:
    """
    Ingest all files in report_data directory into report layer.
    Existing evidence layer remains untouched.
    """
    base = Path(report_dir).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"report_dir not found: {base}")

    allowed_files = None
    if report_files:
        allowed_files = {str(Path(p).expanduser().resolve()) for p in report_files}

    files = [
        p
        for p in sorted(base.iterdir())
        if p.is_file()
        and p.suffix.lower() in {".txt", ".md", ".docx", ".pdf"}
        and (allowed_files is None or str(p.resolve()) in allowed_files)
    ]
    cleared = 0
    if rebuild:
        cleared = clear_report_layer(project_topic=project_topic)

    written = 0
    written_sections = 0
    written_findings = 0
    written_recommendations = 0
    written_metrics = 0
    bridged_post = 0
    bridged_claim = 0
    ids: Dict[str, Dict[str, str]] = {}

    for p in files:
        title = _normalize_title(p)
        quarter = _infer_quarter(p.name, datetime.fromtimestamp(p.stat().st_mtime))
        content = _read_report_file(p)
        cleaned = _clean_text(content)
        post_id = _evidence_post_id(project_topic, p)
        claim_id = _pick_one_claim_for_post(post_id)
        rid = report_id(project_topic, quarter, title)

        upsert_report(
            ReportNode(
                id=rid,
                topic=project_topic,
                title=title,
                quarter=quarter,
                summary=(re.sub(r"\s+", " ", cleaned)[:240] if cleaned else f"{title} 报告导入"),
                source_doc=str(p.resolve()),
            )
        )
        report_topic_names = _topic_candidates(title, "", cleaned[:400], default_topic_name)
        report_platforms = _platform_candidates(title, cleaned[:800], default_platform)
        report_event_names = _event_candidates(title, cleaned[:400])
        topic_ids: Dict[str, str] = {}
        event_ids: Dict[str, str] = {}

        for topic_name in report_topic_names:
            tid = report_topic_id(project_topic, topic_name)
            upsert_topic(tid, topic_name, project_topic)
            topic_ids[topic_name] = tid

        for platform_name in report_platforms:
            upsert_platform(platform_name)

        for idx_event, event_name in enumerate(report_event_names, 1):
            eid = report_event_id(rid, event_name, idx_event)
            upsert_event(eid, event_name, project_topic, summary=event_name)
            event_ids[event_name] = eid
            for tid in topic_ids.values():
                rel_event_relates_to_topic(eid, tid)
            bridge_event_evidenced_by_post(eid, post_id)
            if claim_id:
                bridge_event_evidenced_by_claim(eid, claim_id)

        sections = _split_sections(cleaned, title)
        recommendations = _extract_recommendation_blocks(cleaned)
        if not recommendations:
            recommendations = [_recommendation_from_text(cleaned)]

        metric_rows = _extract_metric_candidates(cleaned)
        if not metric_rows:
            metric_rows = [("报告文本长度", str(len(cleaned)), "chars")]

        metric_ids: List[str] = []
        for idx_metric, (m_name, m_value, m_unit) in enumerate(metric_rows, 1):
            mid = metric_id(rid, m_name, idx_metric)
            upsert_metric(
                MetricNode(
                    id=mid,
                    report_id=rid,
                    name=m_name,
                    value=m_value,
                    unit=m_unit,
                    period=quarter,
                )
            )
            metric_ids.append(mid)
            written_metrics += 1

        finding_ids: List[str] = []
        for idx_section, (section_name, section_text) in enumerate(sections, 1):
            sid = section_id(rid, section_name, idx_section)
            upsert_section(
                SectionNode(
                    id=sid,
                    report_id=rid,
                    name=section_name,
                    order=idx_section,
                    summary=re.sub(r"\s+", " ", section_text)[:200],
                )
            )
            rel_report_has_section(rid, sid)
            section_platforms = _platform_candidates(section_name, section_text, default_platform)
            for platform_name in section_platforms:
                if platform_name != "报告":
                    rel_section_analyzes_platform(sid, platform_name)
            written_sections += 1

            section_topics = _topic_candidates(title, section_name, section_text, default_topic_name)
            for topic_name in section_topics:
                if topic_name not in topic_ids:
                    tid = report_topic_id(project_topic, topic_name)
                    upsert_topic(tid, topic_name, project_topic)
                    topic_ids[topic_name] = tid

            points = _finding_points(section_text)
            for idx_finding, point in enumerate(points, 1):
                fid = finding_id(rid, sid, point, idx_finding)
                upsert_finding(
                    FindingNode(
                        id=fid,
                        report_id=rid,
                        section_id=sid,
                        title=section_name[:40],
                        statement=point,
                        confidence=round(max(0.55, min(0.95, 0.65 + math.log10(max(len(point), 10)) * 0.08)), 2),
                    )
                )
                rel_section_has_finding(sid, fid)
                for platform_name in section_platforms[:1]:
                    if platform_name != "报告":
                        rel_finding_about_platform(fid, platform_name)
                for topic_name in section_topics[:2]:
                    rel_finding_about_topic(fid, topic_ids[topic_name])
                if metric_ids:
                    rel_finding_supported_by_metric(fid, metric_ids[min(idx_finding - 1, len(metric_ids) - 1)])
                for eid in list(event_ids.values())[:1]:
                    rel_finding_supported_by_event(fid, eid)
                bridge_finding_supported_by_post(fid, post_id)
                bridge_finding_supported_by_chunk(fid, f"{post_id}_chunk_1")
                if claim_id:
                    bridge_finding_derived_from_claim(fid, claim_id)
                    bridged_claim += 1
                finding_ids.append(fid)
                written_findings += 1

        recommendation_ids: List[str] = []
        for idx_rec, action in enumerate(recommendations, 1):
            rec_id = recommendation_id(rid, action, idx_rec)
            upsert_recommendation(
                RecommendationNode(
                    id=rec_id,
                    report_id=rid,
                    title=f"建议{idx_rec}",
                    action=action[:240],
                )
            )
            rel_report_has_recommendation(rid, rec_id)
            for platform_name in report_platforms[:1]:
                if platform_name != "报告":
                    rel_recommendation_for_platform(rec_id, platform_name)
            for tid in list(topic_ids.values())[:2]:
                rel_recommendation_addresses_topic(rec_id, tid)
            for fid in finding_ids[:1]:
                rel_recommendation_responds_to(rec_id, fid)
            recommendation_ids.append(rec_id)
            written_recommendations += 1

        for tid in topic_ids.values():
            if claim_id:
                bridge_claim_about_topic(claim_id, tid)

        if claim_id and event_ids:
            for eid in event_ids.values():
                bridge_claim_about_event(claim_id, eid)

        ids[p.name] = {
            "report_id": rid,
            "section_count": str(len(sections)),
            "finding_count": str(len(finding_ids)),
            "recommendation_count": str(len(recommendation_ids)),
            "metric_count": str(len(metric_ids)),
            "topic_count": str(len(topic_ids)),
            "event_count": str(len(event_ids)),
        }
        written += 1
        bridged_post += 1

    # Optional supplement for claim->entity bridge on this topic
    claim_mentions_edges = backfill_claim_mentions_entity(topic=project_topic)

    return {
        "project_topic": project_topic,
        "report_dir": str(base),
        "cleared_report_layer_nodes": cleared,
        "total_files": len(files),
        "written_reports": written,
        "written_sections": written_sections,
        "written_findings": written_findings,
        "written_recommendations": written_recommendations,
        "written_metrics": written_metrics,
        "bridged_post_count": bridged_post,
        "bridged_claim_count": bridged_claim,
        "claim_mentions_edges": claim_mentions_edges,
        "ids": ids,
    }
