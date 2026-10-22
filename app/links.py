from __future__ import annotations

from urllib.parse import quote

from app.config import Settings


def doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}" if doi else ""


def campus_url(doi: str, settings: Settings) -> str:
    if not doi:
        return ""
    if not settings.openurl_base:
        return doi_url(doi)
    separator = "&" if "?" in settings.openurl_base else "?"
    encoded_doi = quote(doi, safe="/:;()")
    return (
        f"{settings.openurl_base}{separator}"
        f"{settings.openurl_doi_param}{encoded_doi}"
    )

