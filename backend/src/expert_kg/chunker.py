"""
Text chunking utilities for Expert KG.
Wraps the core RAG chunker.
"""
from typing import List, Tuple, Dict, Optional
from src.rag.core.chunker import TextChunker, ChunkConfig

class ExpertChunker:
    """
    Chunker specifically for Expert KG documents.
    Uses src.rag.core.chunker.TextChunker under the hood.
    """
    def __init__(self):
        # Config for expert documents (reports, papers)
        # Maybe slightly larger chunks for expert content?
        # Spec says 500-800 chars.
        self.config = ChunkConfig(
            chunk_size=800,
            chunk_overlap=100,
            min_chunk_size=100,
            separator="\n\n"
        )
        self.chunker = TextChunker(self.config)

    def chunk_text(self, text: str, source_id: str) -> List[Dict]:
        """
        Split text into chunks and return list of chunk node data.
        Returns:
            List of dicts, each representing a chunk node.
        """
        chunks = self.chunker.chunk_by_size(text)
        chunk_nodes = []
        
        for chunk_text, index in chunks:
            chunk_id = f"{source_id}_chunk_{index}"
            chunk_nodes.append({
                "id": chunk_id,
                "label": "ExpertChunk",
                "content": chunk_text,
                "index": index,
                "source_id": source_id
            })
            
        return chunk_nodes
