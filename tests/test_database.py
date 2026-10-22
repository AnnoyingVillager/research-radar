import sqlite3

import pytest
from cryptography.fernet import Fernet

from app.auth import hash_password, verify_password
from app.crypto import SecretStorageError
from app.db import Database
from app.domain import RawPaper


def make_database(tmp_path) -> Database:
    return Database(
        tmp_path / "radar.db",
        settings_key_path=tmp_path / "secrets" / "settings-encryption.key",
    )


def make_paper(source: str = "crossref", abstract: str = "") -> RawPaper:
    return RawPaper(
        source=source,
        source_id="10.1234/test",
        title="Aeroacoustic Test Paper",
        doi="10.1234/test",
        abstract=abstract,
        venue_slug="jsv",
        venue_name="Journal of Sound and Vibration",
        venue_kind="journal",
        published_date="2026-10-01",
        online_date="2026-10-01",
    )


def test_upsert_deduplicates_by_doi(tmp_path) -> None:
    database = make_database(tmp_path)
    database.init()
    first_id, first_new = database.upsert_paper(make_paper())
    second_id, second_new = database.upsert_paper(
        make_paper(source="rss", abstract="Newly available abstract")
    )
    assert first_id == second_id
    assert first_new is True
    assert second_new is False
    paper = database.get_paper(first_id)
    assert paper is not None
    assert paper["abstract"] == "Newly available abstract"


def test_feedback_is_persisted(tmp_path) -> None:
    database = make_database(tmp_path)
    database.init()
    paper_id, _ = database.upsert_paper(make_paper())
    database.set_feedback(paper_id, "important")
    assert database.feedback_score(paper_id) == 1.0
    database.set_feedback(paper_id, "ignore")
    assert database.feedback_score(paper_id) == -1.0


def test_runtime_settings_and_admin_are_persisted(tmp_path) -> None:
    database = make_database(tmp_path)
    database.init()
    database.set_app_settings(
        {
            "smtp_host": "smtp.example.edu.cn",
            "llm_enabled": "true",
            "summary_limit": "12",
        }
    )
    encoded = hash_password("a-long-admin-password")
    assert database.create_initial_admin("admin", encoded) is True
    assert database.create_initial_admin("admin", hash_password("must-not-replace")) is False
    assert (
        database.create_initial_admin(
            "second-admin",
            hash_password("must-not-create"),
        )
        is False
    )

    assert database.get_app_settings()["smtp_host"] == "smtp.example.edu.cn"
    user = database.get_user("ADMIN")
    assert user is not None
    assert verify_password("a-long-admin-password", user["password_hash"])
    assert not verify_password("must-not-replace", user["password_hash"])
    assert database.get_user("second-admin") is None


def test_secret_settings_are_encrypted_at_rest(tmp_path) -> None:
    database = make_database(tmp_path)
    database.init()
    database.set_app_settings(
        {
            "openalex_api_key": "openalex-secret-value",
            "llm_api_key": "llm-secret-value",
            "smtp_password": "smtp-secret-value",
            "smtp_host": "smtp.example.edu.cn",
        }
    )

    with sqlite3.connect(database.path) as connection:
        rows = dict(
            connection.execute(
                "SELECT key, value FROM app_settings",
            ).fetchall()
        )

    for field in ("openalex_api_key", "llm_api_key", "smtp_password"):
        assert rows[field].startswith("enc:v1:")
    assert "openalex-secret-value" not in rows["openalex_api_key"]
    assert "llm-secret-value" not in rows["llm_api_key"]
    assert "smtp-secret-value" not in rows["smtp_password"]
    assert rows["smtp_host"] == "smtp.example.edu.cn"
    assert database.get_app_settings()["openalex_api_key"] == "openalex-secret-value"


def test_legacy_plaintext_secret_is_migrated(tmp_path) -> None:
    database = make_database(tmp_path)
    database.init()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES('smtp_password', 'legacy-plaintext', '2026-10-22T00:00:00+00:00')
            """
        )

    database.init()

    with sqlite3.connect(database.path) as connection:
        stored = connection.execute(
            "SELECT value FROM app_settings WHERE key='smtp_password'",
        ).fetchone()[0]
    assert stored.startswith("enc:v1:")
    assert "legacy-plaintext" not in stored
    assert database.get_app_settings()["smtp_password"] == "legacy-plaintext"
    assert b"legacy-plaintext" not in database.path.read_bytes()
    wal_path = database.path.with_name(f"{database.path.name}-wal")
    if wal_path.exists():
        assert b"legacy-plaintext" not in wal_path.read_bytes()


def test_wrong_encryption_key_cannot_read_secrets(tmp_path) -> None:
    database = make_database(tmp_path)
    database.init()
    database.set_app_settings({"llm_api_key": "protected-value"})

    with pytest.raises(SecretStorageError, match="密钥文件缺失"):
        Database(
            database.path,
            settings_key_path=tmp_path / "missing-secrets" / "settings-encryption.key",
        )

    wrong_key_path = tmp_path / "wrong-secrets" / "settings-encryption.key"
    wrong_key_path.parent.mkdir(parents=True)
    wrong_key_path.write_bytes(Fernet.generate_key() + b"\n")
    wrong_database = Database(database.path, settings_key_path=wrong_key_path)
    with pytest.raises(SecretStorageError):
        wrong_database.get_app_settings()

