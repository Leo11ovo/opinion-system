import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import lancedb
import numpy as np

from ..core.base import BaseRetriever
from ..retrievers.vector_retriever import RetrievalResult
from ..embeddings.base import BaseEmbedder

logger = logging.getLogger(__name__)

class LanceRetriever(BaseRetriever):
    """Retriever that uses an existing LanceDB vector store."""

    def __init__(self, 
                 uri: str, 
                 table_name: str, 
                 embedder: BaseEmbedder,
                 vector_column: str = "vector",
                 text_column: str = "text",
                 id_column: str = "id"):
        super().__init__()
        self.uri = uri
        self.table_name = table_name
        self.embedder = embedder
        self.vector_column = vector_column
        self.text_column = text_column
        self.id_column = id_column
        self.db = None
        self.table = None
        self._connect()

    def _connect(self):
        """Connect to LanceDB."""
        try:
            self.db = lancedb.connect(self.uri)
            if self.table_name in self.db.table_names():
                self.table = self.db.open_table(self.table_name)
                logger.info(f"Connected to LanceDB table '{self.table_name}' at {self.uri}")
            else:
                logger.warning(f"Table '{self.table_name}' not found in {self.uri}")
        except Exception as e:
            logger.error(f"Failed to connect to LanceDB: {e}")

    def build_index(self, documents: List[Dict[str, Any]], **kwargs) -> None:
        """Not implemented for existing DB."""
        logger.warning("build_index not supported for LanceRetriever (read-only)")

    def save_index(self, path: str, **kwargs) -> None:
        """Not implemented for existing DB."""
        pass

    def load_index(self, path: str, **kwargs) -> None:
        """Not implemented for existing DB."""
        pass

    def retrieve(self, 
                query: str, 
                top_k: int = 10, 
                threshold: float = 0.0,
                **kwargs) -> List[RetrievalResult]:
        """Retrieve documents from LanceDB."""
        if not self.table:
            logger.warning("LanceDB table not initialized.")
            return []

        try:
            # Embed query
            query_embedding = self.embedder.embed(query)
            if isinstance(query_embedding, list):
                query_embedding = np.array(query_embedding)
            
            # Search
            # Note: lancedb search returns a simplified object or Arrow table depending on version
            # We assume standard usage: .search(vec).limit(k).to_list()
            
            # Check for specific search column if provided in kwargs or default to vector_column
            search_col = kwargs.get("vector_column", self.vector_column)
            
            # Perform search
            # We use to_list() or to_pandas()
            results = self.table.search(query_embedding, vector_column_name=search_col).limit(top_k).to_list()
            
            retrieval_results = []
            for item in results:
                distance = float(item.get("_distance", 0.0))
                # Convert distance to similarity (assuming cosine/L2 on normalized vectors)
                # Higher score = better match
                score = 1.0 - distance
                
                text = item.get(self.text_column, "")
                doc_id = str(item.get(self.id_column, ""))
                
                # Construct metadata from other fields
                metadata = {k: v for k, v in item.items() 
                           if k not in [self.vector_column, self.text_column, "_distance"]}
                
                retrieval_results.append(RetrievalResult(
                    text=text,
                    score=score,
                    metadata=metadata,
                    doc_id=doc_id
                ))
                
            return retrieval_results

        except Exception as e:
            logger.error(f"LanceDB retrieval failed: {e}")
            return []
