from __future__ import annotations

from worker.executors import PCM_STREAM_BATCH_BYTES, batch_pcm_chunks


def test_batches_pcm_into_half_second_database_writes() -> None:
    raw = bytes(index % 251 for index in range(48_123))

    batches = list(batch_pcm_chunks([raw[:1_000], raw[1_000:25_000], raw[25_000:]]))

    assert [len(batch) for batch in batches] == [24_000, 24_000, 123]
    assert b"".join(batches) == raw


def test_real_failed_audio_size_requires_only_fifty_three_writes() -> None:
    raw = bytes(1_263_360)
    provider_chunks = [raw[offset : offset + 1_920] for offset in range(0, len(raw), 1_920)]

    batches = list(batch_pcm_chunks(provider_chunks))

    assert PCM_STREAM_BATCH_BYTES == 24_000
    assert len(provider_chunks) == 658
    assert len(batches) == 53
    assert b"".join(batches) == raw


def test_empty_pcm_chunks_do_not_create_database_writes() -> None:
    assert list(batch_pcm_chunks([b"", b""])) == []
