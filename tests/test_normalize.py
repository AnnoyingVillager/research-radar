from app.normalize import (
    clean_abstract,
    crossref_date,
    extract_doi_from_text,
    normalize_doi,
    normalize_title,
)


def test_normalize_doi_and_title() -> None:
    assert normalize_doi("https://doi.org/10.1016/J.JSV.2026.01.001") == (
        "10.1016/j.jsv.2026.01.001"
    )
    assert normalize_title("Flow-Induced Noise: A Study") == "flow induced noise a study"


def test_extract_doi() -> None:
    text = "Link https://doi.org/10.1017/jfm.2026.12."
    assert extract_doi_from_text(text) == "10.1017/jfm.2026.12"


def test_clean_abstract() -> None:
    value = "<jats:p>Abstract This is a <b>test</b>.</jats:p>"
    assert clean_abstract(value) == "This is a test."


def test_crossref_date() -> None:
    assert crossref_date({"date-parts": [[2026, 10, 21]]}) == "2026-10-21"
    assert crossref_date({"date-parts": [[2026]]}) == "2026-01-01"
    assert crossref_date({}) == ""

