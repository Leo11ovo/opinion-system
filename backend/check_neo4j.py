from src.graph.neo4j_client import get_session

def check_neo4j():
    with get_session() as session:
        # Check node counts
        result = session.run("MATCH (n) RETURN labels(n) as label, count(n) as count")
        print("Node Counts:")
        for record in result:
            print(f"{record['label']}: {record['count']}")
            
        # Check available topics
        print("\nAvailable Topics:")
        result = session.run("MATCH (n) WHERE n.topic IS NOT NULL RETURN DISTINCT n.topic as topic, labels(n) as label, count(n) as count")
        for record in result:
            print(f"Topic: {record['topic']} ({record['label']}) - Count: {record['count']}")

if __name__ == "__main__":
    check_neo4j()
