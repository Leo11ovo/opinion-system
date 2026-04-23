# Report Layer Guide

This guide defines the standard two-layer Neo4j model:

- Evidence layer (existing): `Post`, `Chunk`, `Entity`, `Claim`
- Report layer (new): `Report`, `Section`, `Finding`, `Recommendation`, `Platform`, `Topic`, `Event`, `Metric`

No old labels/relations are renamed or removed.

Current standard entrypoint:

- `sync_mysql_to_neo4j.py::sync_after_upload(...)`
  - writes evidence layer first
  - if report files are present, ingests report layer in the same build flow
  - then runs vector backfill for graph retrieval

## 1) Schema / Constraints

Constraints are created in `schema.py` via `init_schema()`:

- Existing: `Post`, `Chunk`, `Entity`, `Claim`, `Topic`, `Event`, `Platform`, `Account`
- New:
  - `Report.id` unique
  - `Section.id` unique
  - `Finding.id` unique
  - `Recommendation.id` unique
  - `Metric.id` unique

## 2) ID Rules

Implemented in `report_layer.py`:

- `report_id(topic, quarter, title)`
- `section_id(report_id, section_name, order)`
- `finding_id(report_id, section_id, text, index)`
- `recommendation_id(report_id, text, index)`
- `metric_id(report_id, metric_name, index)`
- `report_topic_id(topic, topic_name)`
- `report_event_id(report_id, event_name, index)`

All IDs are deterministic and hash-suffixed for stability.

## 3) Node Properties

- `Report`: `id, topic, title, quarter, summary, period_start, period_end, source_doc, source, created_at, updated_at`
- `Section`: `id, report_id, name, section_order, summary, source`
- `Finding`: `id, report_id, section_id, title, statement, confidence, severity, source`
- `Recommendation`: `id, report_id, title, action, priority, owner, source`
- `Metric`: `id, report_id, name, value, unit, period, metric_source, source`
- `Topic` (report-layer write): `id, name, project, level, source`
- `Event` (report-layer write): `id, name, project, summary, source`
- `Platform`: `name`

## 4) Relationship Functions

Report layer relations:

- `rel_report_has_section`
- `rel_report_has_recommendation`
- `rel_section_analyzes_platform`
- `rel_section_has_finding`
- `rel_finding_about_platform`
- `rel_finding_about_topic`
- `rel_finding_supported_by_metric`
- `rel_finding_supported_by_event`
- `rel_recommendation_for_platform`
- `rel_recommendation_addresses_topic`
- `rel_recommendation_responds_to`
- `rel_event_relates_to_topic`

Bridge relations:

- `bridge_finding_supported_by_post`
- `bridge_finding_supported_by_chunk`
- `bridge_finding_derived_from_claim`
- `bridge_event_evidenced_by_post`
- `bridge_event_evidenced_by_claim`
- `bridge_claim_about_topic`
- `bridge_claim_about_event`
- `bridge_claim_mentions_entity`

Supplement helper:

- `backfill_claim_mentions_entity(topic=None)`:
  - derives `(Claim)-[:MENTIONS]->(Entity)` from shared `Chunk`.

## 5) Minimal Write Example

Use fixed quarterly structure:

```python
from src.graph.report_layer import write_minimal_quarterly_report_example

ids = write_minimal_quarterly_report_example(
    project_topic="report_graph",
    quarter="2026Q1",
    report_title="2026Q1 交通舆情季报",
    platform_name="微博",
    topic_name="交通安全",
    finding_statement="短视频平台事故类舆情传播速度高于图文平台",
    recommendation_action="建立高风险时段的跨平台联动响应机制",
    metric_name="负面讨论占比",
    metric_value="32.4",
    metric_unit="%",
    evidence_post_id="report_graph_report_data_report_xxx",
    evidence_chunk_id="report_graph_report_data_report_xxx_chunk_1",
    evidence_claim_id="report_graph_claim_xxx",
)
print(ids)
```

## 6) Query Routing Guidance

Use report layer when:

- building quarterly narrative
- answering executive summary questions
- tracing recommendation -> finding -> metric/event

Use evidence layer when:

- locating raw textual evidence
- inspecting extraction quality
- retrieving concrete source chunks/posts/entities/claims
