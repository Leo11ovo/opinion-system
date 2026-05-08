from src.graph.neo4j_client import get_session

s = get_session(database="3cb72f36")
labels = ["Finding", "Claim", "Entity", "Chunk", "Topic", "Event", "Report", "Section", "Recommendation", "Metric"]
for label in labels:
    row = s.run(f"""
        MATCH (n:{label})
        WITH count(n) AS cnt,
             avg(size(coalesce(n.statement, ''))) AS avg_stmt,
             avg(size(coalesce(n.content, ''))) AS avg_cont,
             avg(size(coalesce(n.title, ''))) AS avg_title,
             avg(size(coalesce(n.name, ''))) AS avg_name
        RETURN cnt, round(avg_stmt, 1) AS avg_stmt, round(avg_cont, 1) AS avg_cont,
               round(avg_title, 1) AS avg_title, round(avg_name, 1) AS avg_name
    """).single()
    if row:
        print(f"{label:15s}: count={row['cnt']:5d}, avg_stmt={row['avg_stmt']}, avg_cont={row['avg_cont']}, avg_title={row['avg_title']}, avg_name={row['avg_name']}")
    else:
        print(f"{label:15s}: 0 nodes")
