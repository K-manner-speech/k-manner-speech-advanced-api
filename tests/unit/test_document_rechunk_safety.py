from inspect import getsource

from worker.domain_adapters import DocumentAnalysisAdapter


def test_reanalysis_replaces_chunks_only_after_current_analysis_is_confirmed() -> None:
    source = getsource(DocumentAnalysisAdapter.complete)

    confirmed = source.index("if updated is None")
    delete_chunks = source.index('"delete from public.document_chunks "')
    insert_chunks = source.index("insert into public.document_chunks")
    ready = source.index("set processing_status = 'ready'")

    assert confirmed < delete_chunks < insert_chunks < ready
    assert "d.id = :document_id and d.version_no = :version" in source
    assert "a.processing_token = :token" in source
