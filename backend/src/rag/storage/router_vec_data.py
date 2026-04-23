"""Compatibility shim for RouterRAG vectorization.

Legacy storage-path imports are redirected to the active implementation under
`src.utils.rag.ragrouter`.
"""

from src.utils.rag.ragrouter.router_vec_data import *  # noqa: F401,F403

