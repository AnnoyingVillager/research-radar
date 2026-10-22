from app.auth import (
    create_session,
    csrf_token,
    hash_password,
    safe_next_url,
    valid_csrf,
    verify_password,
    verify_session,
)


def test_password_and_session_round_trip() -> None:
    encoded = hash_password("a-secure-password")
    assert verify_password("a-secure-password", encoded)
    assert not verify_password("wrong-password", encoded)

    token = create_session("admin", "session-secret", 60)
    assert verify_session(token, "session-secret") == "admin"
    assert verify_session(token + "tampered", "session-secret") is None
    assert verify_session(token, "other-secret") is None


def test_csrf_and_redirect_validation() -> None:
    token = csrf_token("admin", "session-secret")
    assert valid_csrf("admin", "session-secret", token)
    assert not valid_csrf("admin", "session-secret", "invalid")
    assert safe_next_url("/settings") == "/settings"
    assert safe_next_url("//attacker.example") == "/settings"
    assert safe_next_url("https://attacker.example") == "/settings"
