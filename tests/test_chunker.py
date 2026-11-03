from app.ingestion.chunker import MAX_CHUNK_TOKENS, chunk_document
from app.ingestion.models import Block, DocMeta, ParsedDocument
from app.tokens import count_tokens

META = DocMeta("DOC-1", "f", "Doc One", "policy", ("GLOBAL",), "2026-01-01", "all")


def parsed(*blocks):
    return ParsedDocument(meta=META, blocks=list(blocks))


def h(text, page=1):
    return Block(kind="heading", text=text, page=page, level=2)


def t(text, page=1):
    return Block(kind="text", text=text, page=page)


def test_locator_is_the_nearest_heading_and_chunks_start_with_it():
    chunks = chunk_document(parsed(h("1. Scope"), t("Scope text."), h("2. Sick leave"), t("Twelve days.")))
    assert [c.locator for c in chunks] == ["1. Scope", "2. Sick leave"]
    assert chunks[1].text == "2. Sick leave\nTwelve days."


def test_chunk_ids_are_unique_and_prefixed_with_the_document_id():
    chunks = chunk_document(parsed(h("A"), t("a"), h("B"), t("b")))
    assert [c.chunk_id for c in chunks] == ["DOC-1#1", "DOC-1#2"]
    assert all(c.doc_id == "DOC-1" for c in chunks)


def test_document_without_headings_uses_page_numbers_as_locators():
    chunks = chunk_document(parsed(t("first page text", page=1)))
    assert [c.locator for c in chunks] == ["p. 1"]


def test_text_before_the_first_heading_uses_a_page_locator():
    chunks = chunk_document(parsed(t("preamble", page=2), h("1. Rules", page=2), t("rule")))
    assert [c.locator for c in chunks] == ["p. 2", "1. Rules"]


def test_a_chunk_never_crosses_a_heading():
    chunks = chunk_document(parsed(h("A"), t("alpha text"), h("B"), t("beta text")))
    assert "beta" not in chunks[0].text and "alpha" not in chunks[1].text


def test_heading_without_content_makes_no_chunk():
    assert chunk_document(parsed(h("Empty heading"), h("Real"), t("content"))) [0].locator == "Real"


def test_trailing_colon_is_removed_from_locators():
    assert chunk_document(parsed(h("Rules:"), t("x")))[0].locator == "Rules"


def test_tables_become_one_self_describing_line_per_row():
    rows = [["Topic", "Version 1", "Version 2"], ["Sick leave", "10", "12"], ["Bereavement", "3", "5"]]
    chunk = chunk_document(parsed(h("3. Changes"), Block(kind="table", rows=rows)))[0]
    assert "Topic: Sick leave; Version 1: 10; Version 2: 12" in chunk.text
    assert "Topic: Bereavement; Version 1: 3; Version 2: 5" in chunk.text


def test_long_sections_are_split_under_the_token_limit_with_the_heading_repeated():
    paragraphs = [t(f"Paragraph number {i} " + "word " * 60) for i in range(12)]
    chunks = chunk_document(parsed(h("1. Long section"), *paragraphs))
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.tokens <= MAX_CHUNK_TOKENS
        assert chunk.text.startswith("1. Long section\n")
        assert chunk.locator == "1. Long section"


def test_a_single_huge_paragraph_is_split_by_sentences():
    big = " ".join(f"Sentence number {i} says something useful." for i in range(200))
    chunks = chunk_document(parsed(h("Big"), t(big)))
    assert len(chunks) > 1 and all(c.tokens <= MAX_CHUNK_TOKENS for c in chunks)
    rebuilt = " ".join(c.text.split("\n", 1)[1] for c in chunks)
    assert rebuilt.count("Sentence number") == 200      # nothing lost


def test_token_count_matches_the_text():
    chunk = chunk_document(parsed(h("A"), t("Some text here.")))[0]
    assert chunk.tokens == count_tokens(chunk.text)


def test_page_locator_for_a_multi_page_headingless_document_follows_the_first_piece():
    chunks = chunk_document(parsed(t("page one text " * 2, page=1), t("page two text", page=2)))
    assert chunks[0].locator == "p. 1"
