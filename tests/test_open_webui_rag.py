"""Open WebUI retrieves from documents with NaN's models, not local ones (spec AI-009 PR 5, AC9).

Measured from inside the container on 2026-10-07 (verification.md, PR 5a): NaN
answers v0.11.4's `requests` client, embeds a batch of 16, and its `/rerank`
returns the `results` shape `ExternalReranker` parses.
"""

from __future__ import annotations

from tests.test_agent_stack_role import _common, _context, _env


def _rag() -> dict:
    return _common()["apps"]["services"]["ai"]["open_webui"]["rag"]


def test_embeddings_come_from_nan_so_no_local_model_loads() -> None:
    """With the engine empty, v0.11.4 loads a sentence-transformers model into the
    container at start (`get_ef`, routers/retrieval.py), and ace2 has 1.5 GB per service."""
    env = _env()
    assert env["RAG_EMBEDDING_ENGINE"] == "openai"
    assert env["RAG_OPENAI_API_BASE_URL"] == env["OPENAI_API_BASE_URLS"], "one inference provider, one URL"
    assert env["RAG_OPENAI_API_KEY"] == _context()["agent_stack_nan_api_key"]
    assert env["RAG_EMBEDDING_MODEL"] == _rag()["embedding_model"]
    assert env["RAG_EMBEDDING_BATCH_SIZE"] == str(_rag()["embedding_batch_size"])


def test_the_reranker_is_nan_and_hybrid_search_is_on_so_it_runs() -> None:
    """v0.11.4 calls the reranker only on the hybrid-search path (`query_collection`,
    retrieval/utils.py): without `ENABLE_RAG_HYBRID_SEARCH` an external reranker is
    configured, and never called."""
    env = _env()
    assert env["ENABLE_RAG_HYBRID_SEARCH"] == "true"
    assert env["RAG_RERANKING_ENGINE"] == "external"
    assert env["RAG_RERANKING_MODEL"] == _rag()["reranking_model"]
    assert env["RAG_EXTERNAL_RERANKER_URL"] == env["OPENAI_API_BASE_URLS"] + "/rerank"
    assert env["RAG_EXTERNAL_RERANKER_API_KEY"] == _context()["agent_stack_nan_api_key"]
