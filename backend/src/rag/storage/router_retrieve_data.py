"""Compatibility shim for RouterRAG retrieval.

Legacy storage-path imports are redirected to the active implementation under
`src.utils.rag.ragrouter`.
"""

from src.utils.rag.ragrouter.router_retrieve_data import *  # noqa: F401,F403

