"""notifier/discord.py 단위 테스트."""
from unittest.mock import patch

from notifier.discord import notify_new_concert


class TestNotifyNewConcert:
    def test_does_not_call_requests_when_webhook_url_not_set(self):
        """DISCORD_WEBHOOK_URL이 falsy면 requests.post가 호출되지 않아야 한다."""
        with (
            patch("notifier.discord.DISCORD_WEBHOOK_URL", ""),
            patch("notifier.discord.requests.post") as mock_post,
        ):
            notify_new_concert("NewJeans 내한공연", ["NewJeans"])

        mock_post.assert_not_called()

    def test_posts_webhook_with_expected_content(self):
        """webhook URL 설정 시 requests.post가 1회, 지정된 content로 호출되어야 한다."""
        with (
            patch("notifier.discord.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x"),
            patch("notifier.discord.requests.post") as mock_post,
        ):
            notify_new_concert("NewJeans 내한공연", ["NewJeans"])

        mock_post.assert_called_once_with(
            "https://discord.com/api/webhooks/x",
            json={"content": "NewJeans 내한공연 - NewJeans"},
            timeout=10,
        )

    def test_joins_multiple_artist_names_with_comma(self):
        """아티스트가 2명 이상이면 쉼표로 join되어야 한다."""
        with (
            patch("notifier.discord.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x"),
            patch("notifier.discord.requests.post") as mock_post,
        ):
            notify_new_concert("페스티벌", ["A", "B"])

        mock_post.assert_called_once_with(
            "https://discord.com/api/webhooks/x",
            json={"content": "페스티벌 - A, B"},
            timeout=10,
        )

    def test_swallows_exception_from_requests_post(self):
        """requests.post가 예외를 던져도 notify_new_concert는 예외 없이 반환해야 한다."""
        with (
            patch("notifier.discord.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x"),
            patch("notifier.discord.requests.post", side_effect=Exception("boom")),
        ):
            notify_new_concert("NewJeans 내한공연", ["NewJeans"])
