from app.speech.phrase_chunker import PhraseChunker, PhraseChunkerConfig


def test_phrase_chunker_preserves_exact_text() -> None:
    source = "Welcome back, Poom. I kept everything ready while you were away. Shall we continue building?"
    chunker = PhraseChunker(PhraseChunkerConfig(first_min_chars=18, min_chars=24, max_chars=55))
    chunks: list[str] = []
    for fragment in (source[:11], source[11:37], source[37:68], source[68:]):
        chunks.extend(chunker.feed(fragment))
    chunks.extend(chunker.flush())

    assert "".join(chunks) == source
    assert len(chunks) >= 2
    assert all(chunks)


def test_phrase_chunker_forces_boundary_at_maximum() -> None:
    source = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    chunker = PhraseChunker(PhraseChunkerConfig(first_min_chars=12, min_chars=12, max_chars=40))
    chunks = chunker.feed(source) + chunker.flush()

    assert "".join(chunks) == source
    assert all(len(chunk) <= 40 for chunk in chunks[:-1])
