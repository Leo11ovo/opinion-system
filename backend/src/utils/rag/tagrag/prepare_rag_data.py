import json
import os
import argparse
from typing import List, Dict, Any
from concurrent.futures import ProcessPoolExecutor
from functools import partial

def process_line(line: str) -> Dict[str, Any]:
    """Process a single line of JSONL."""
    line = line.strip()
    if not line:
        return None
    try:
        item = json.loads(line)
        
        # Extract relevant fields
        text = item.get('contents', '')
        if not text:
            text = item.get('title', '')
        
        tag = item.get('hit_words', '')
        if not tag:
            tag = item.get('title', '') # Fallback
        
        # Create record
        record = {
            "id": item.get('id'),
            "text": text,
            "tag": tag,
            "metadata": {
                "platform": item.get('platform'),
                "author": item.get('author'),
                "published_at": item.get('published_at'),
                "url": item.get('url'),
                "region": item.get('region'),
                "polarity": item.get('polarity'),
                "classification": item.get('classification')
            }
        }
        return record
    except json.JSONDecodeError:
        return None
    except Exception:
        return None

def convert_project_data(input_path: str, output_path: str, max_workers: int = 4):
    """
    Convert project data (jsonl) to format_db JSON using multiprocessing.
    """
    print(f"Reading from: {input_path}")
    
    if not os.path.exists(input_path):
        print(f"Error: Project file not found: {input_path}")
        return

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    count = 0
    
    # Use streaming write to avoid memory issues
    with open(output_path, 'w', encoding='utf-8') as out_f:
        out_f.write('{"data": [\n')
        
        with open(input_path, 'r', encoding='utf-8') as in_f:
            # Use ProcessPoolExecutor for parallel processing
            # Adjust max_workers based on CPU cores
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # Process lines in chunks
                # map keeps the order
                for record in executor.map(process_line, in_f, chunksize=1000):
                    if record:
                        if count > 0:
                            out_f.write(',\n')
                        json.dump(record, out_f, ensure_ascii=False)
                        count += 1
                        
                        if count % 10000 == 0:
                            print(f"Processed {count} records...", end='\r')
                            
        out_f.write('\n]}')
        
    print(f"\nSuccessfully converted {count} records.")
    print(f"Saved to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert project data to RAG format")
    parser.add_argument("--input", type=str, required=True, help="Path to input jsonl file")
    parser.add_argument("--output", type=str, required=True, help="Path to output json file")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4, help="Number of worker processes")
    
    args = parser.parse_args()
    convert_project_data(args.input, args.output, args.workers)