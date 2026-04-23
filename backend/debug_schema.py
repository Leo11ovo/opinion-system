
import lancedb
from pathlib import Path
import sys

def inspect_schema():
    db_path = r"F:\opinion-system\opinion-system\backend\src\utils\rag\tagrag\vector_db"
    db = lancedb.connect(db_path)
    print(f"Tables: {db.table_names()}")
    
    if "test" in db.table_names():
        table = db.open_table("test")
        print("Schema:")
        print(table.schema)
        
        # Check versions
        print(f"Current version: {table.version}")
        try:
             versions = table.list_versions()
             print(f"Versions: {len(versions)}")
             for v in versions:
                 print(f"Version {v['version']}: {v['timestamp']}")
        except Exception as e:
             print(f"Could not list versions: {e}")

        # Try to read data
        try:
            df = table.to_pandas()
            print(f"Successfully read {len(df)} rows.")
            print("-" * 50)
            
            # Check for Graph Nodes (Entities)
            print("【图谱节点检查】(查找 source='graph' 的数据):")
            graph_nodes = []
            for idx, row in df.iterrows():
                if '"source": "graph"' in str(row['metadata']):
                    graph_nodes.append(row)
                    if len(graph_nodes) >= 5:
                        break
            
            if graph_nodes:
                print(f"找到图谱节点示例 ({len(graph_nodes)}条):")
                for node in graph_nodes:
                    print(f"ID: {node['id']}")
                    print(f"Name: {node['text']}")
                    print(f"Tag: {node.get('tag', 'N/A')}") # Assuming tag is in metadata or text column based on earlier code
                    print(f"Metadata: {node['metadata']}")
                    print("-" * 30)
            else:
                print("警告：前几千条数据中未发现 source='graph' 的节点。")
                # Try to filter using pandas for full scan
                graph_df = df[df['metadata'].str.contains('"source": "graph"', na=False)]
                if not graph_df.empty:
                     print(f"全表扫描发现 {len(graph_df)} 个图谱节点。")
                     print("示例:")
                     print(graph_df.head(3)[['id', 'text', 'metadata']])
                else:
                     print("全表扫描未发现图谱节点！请检查 sync_graph_to_vector.py 是否正确运行。")

        except Exception as e:
            print(f"Error reading latest version: {e}")
            
            # Try previous version
            if table.version > 1:
                try:
                    print(f"Trying version {table.version - 1}...")
                    table.checkout(table.version - 1)
                    df = table.to_pandas()
                    print(f"Successfully read {len(df)} rows from v{table.version}.")
                except Exception as e2:
                    print(f"Error reading previous version: {e2}")

if __name__ == "__main__":
    inspect_schema()
