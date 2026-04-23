import logging
from typing import List, Union
import numpy as np
from .base import BaseEmbedder
# Use relative import based on project structure
# backend/src/rag/embeddings/openai_embedder.py -> backend/src/utils/rag/embedding.py
from ...utils.rag.embedding import get_sync_client, generate_embedding_sync

logger = logging.getLogger(__name__)

class OpenAIEmbedder(BaseEmbedder):
    """Embedder using OpenAI API (or compatible like Qwen)."""
    
    def __init__(self, model_name: str = None, dimension: int = None):
        super().__init__()
        try:
            self.client, self.default_model, self.default_dimension = get_sync_client()
            self.model_name = model_name or self.default_model
            self.dimension = dimension or self.default_dimension
            logger.info(f"Initialized OpenAIEmbedder with model {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

    def embed(self, texts: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Embed a string or list of strings.
        Returns a list of floats (for single string) or list of list of floats.
        """
        is_single = isinstance(texts, str)
        if is_single:
            texts = [texts]
            
        embeddings = []
        for text in texts:
            try:
                emb = generate_embedding_sync(self.client, text, self.model_name)
                embeddings.append(emb)
            except Exception as e:
                logger.error(f"Error embedding text '{text[:50]}...': {e}")
                # Return zero vector or skip? 
                # Better to return zero vector to maintain index alignment if batch processing
                embeddings.append([0.0] * self.dimension)
            
        if is_single:
            return embeddings[0]
        return embeddings
