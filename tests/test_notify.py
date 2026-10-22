from app.config import Settings
from app.notify import EmailNotifier


def test_smtp_refuses_plaintext_authentication() -> None:
    notifier = EmailNotifier(
        Settings(
            smtp_host="smtp.example.test",
            smtp_port=25,
            smtp_username="sender@example.test",
            smtp_password="must-not-leak",
            smtp_from="sender@example.test",
            smtp_to="reader@example.test",
            smtp_starttls=False,
            smtp_ssl=False,
        )
    )

    sent, message = notifier._send_sync("test", "<p>test</p>", "test")

    assert sent is False
    assert "TLS" in message
