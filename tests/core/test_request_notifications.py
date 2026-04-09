from types import SimpleNamespace
from unittest.mock import patch


def test_send_request_notification_supports_activated_status():
    from shelfmark.core.request_notifications import send_request_notification

    smtp_config = SimpleNamespace(from_addr="Shelfmark <noreply@example.com>")
    with patch("shelfmark.core.request_notifications._is_notification_enabled", return_value=True), \
         patch("shelfmark.core.request_notifications._get_smtp_config", return_value=smtp_config), \
         patch("shelfmark.download.outputs.email.send_email_message") as mock_send:
        result = send_request_notification(
            user_email="reader@example.com",
            request_title="Future Book",
            new_status="activated",
        )

    assert result is True
    assert mock_send.called
    message = mock_send.call_args[0][1]
    assert message["Subject"] == "Request Activated: Future Book"
    assert "now active" in message.get_content().lower()
