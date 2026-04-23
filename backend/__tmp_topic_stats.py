from src.graph.neo4j_client import get_session

topic = 'report_graph_llm_poc_small'
with get_session(database='opinion-report') as s:
    labels = s.run(
        "MATCH (n) WHERE coalesce(n.topic,'') = $topic OR coalesce(n.project,'') = $topic RETURN labels(n) AS labels, count(*) AS c ORDER BY c DESC",
        topic=topic,
    ).data()
    rels = s.run(
        "MATCH (a)-[r]->(b) WHERE coalesce(a.topic,'') = $topic OR coalesce(b.topic,'') = $topic OR coalesce(a.project,'') = $topic OR coalesce(b.project,'') = $topic RETURN type(r) AS type, count(*) AS c ORDER BY c DESC",
        topic=topic,
    ).data()
print('LABELS', labels)
print('RELS', rels)
