"""Тесты фетчеров с моками HTTP-запросов."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class TestFetchPosts:
    @patch("parser.httpx.get")
    def test_fetch_posts_basic(self, mock_get):
        html = """
        <html>
        <div class="tgme_widget_message" data-post="test_channel/1">
            <div class="tgme_widget_message_date">
                <time datetime="2026-05-15T20:00:00+00:00"></time>
            </div>
            <div class="tgme_widget_message_text">Концерт группы Сплин</div>
        </div>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        from parser import fetch_posts
        posts = fetch_posts("test_channel", days_back=30)

        assert len(posts) == 1
        assert "Сплин" in posts[0]["text"]
        assert posts[0]["url"] == "https://t.me/test_channel/1"

    @patch("parser.httpx.get")
    def test_fetch_posts_old_filtered(self, mock_get):
        old_date = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        html = f"""
        <html>
        <div class="tgme_widget_message" data-post="test/1">
            <div class="tgme_widget_message_date">
                <time datetime="{old_date}"></time>
            </div>
            <div class="tgme_widget_message_text">Старый пост</div>
        </div>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_get.return_value = mock_response

        from parser import fetch_posts
        posts = fetch_posts("test", days_back=14)

        assert len(posts) == 0

    @patch("parser.httpx.get")
    def test_fetch_posts_multiple_images(self, mock_get):
        html = """
        <html>
        <div class="tgme_widget_message" data-post="test/1">
            <div class="tgme_widget_message_date">
                <time datetime="2026-05-15T20:00:00+00:00"></time>
            </div>
            <div class="tgme_widget_message_text">Афиша</div>
            <div class="tgme_widget_message_photo_wrap" style="background-image:url('https://example.com/img1.jpg')"></div>
            <div class="tgme_widget_message_photo_wrap" style="background-image:url('https://example.com/img2.jpg')"></div>
        </div>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        from parser import fetch_posts
        posts = fetch_posts("test", days_back=30)

        assert len(posts) == 1
        assert posts[0]["images"] is not None
        assert len(posts[0]["images"]) == 2


class TestFetchVkPosts:
    @patch("fetch_vk.httpx.get")
    def test_fetch_vk_posts_basic(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": {
                "items": [
                    {
                        "id": 1,
                        "owner_id": -123,
                        "date": int(datetime.now(timezone.utc).timestamp()),
                        "text": "Концерт в пятницу",
                        "marked_as_ads": False,
                        "attachments": [],
                    }
                ],
                "count": 1,
            }
        }
        mock_get.return_value = mock_response

        from fetch_vk import fetch_vk_posts
        posts = fetch_vk_posts("test_group", "fake_token", days_back=30)

        assert len(posts) == 1
        assert "Концерт" in posts[0]["text"]
        assert posts[0]["url"] == "https://vk.com/wall-123_1"

    @patch("fetch_vk.httpx.get")
    def test_fetch_vk_posts_skips_ads(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": {
                "items": [
                    {
                        "id": 1,
                        "owner_id": -123,
                        "date": int(datetime.now(timezone.utc).timestamp()),
                        "text": "Реклама",
                        "marked_as_ads": True,
                        "attachments": [],
                    }
                ],
                "count": 1,
            }
        }
        mock_get.return_value = mock_response

        from fetch_vk import fetch_vk_posts
        posts = fetch_vk_posts("test_group", "fake_token", days_back=30)

        assert len(posts) == 0

    @patch("fetch_vk.httpx.get")
    def test_fetch_vk_posts_skips_empty_text(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": {
                "items": [
                    {
                        "id": 1,
                        "owner_id": -123,
                        "date": int(datetime.now(timezone.utc).timestamp()),
                        "text": "",
                        "marked_as_ads": False,
                        "attachments": [],
                    }
                ],
                "count": 1,
            }
        }
        mock_get.return_value = mock_response

        from fetch_vk import fetch_vk_posts
        posts = fetch_vk_posts("test_group", "fake_token", days_back=30)

        assert len(posts) == 0

    @patch("fetch_vk.httpx.get")
    def test_fetch_vk_posts_api_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "error": {
                "error_code": 5,
                "error_msg": "User authorization failed",
            }
        }
        mock_get.return_value = mock_response

        from fetch_vk import fetch_vk_posts
        with pytest.raises(RuntimeError, match="VK API error"):
            fetch_vk_posts("test_group", "fake_token")


class TestFetchMaxPosts:
    @patch("fetch_max.httpx.get")
    def test_fetch_max_posts_basic(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": [
                {
                    "timestamp": int(datetime.now(timezone.utc).timestamp()),
                    "body": {
                        "text": "Анонс концерта",
                        "attachments": [],
                    },
                }
            ]
        }
        mock_get.return_value = mock_response

        from fetch_max import fetch_max_posts
        posts = fetch_max_posts(123, "fake_token", days_back=30)

        assert len(posts) == 1
        assert "концерта" in posts[0]["text"]

    @patch("fetch_max.httpx.get")
    def test_fetch_max_posts_skips_empty(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": [
                {
                    "timestamp": int(datetime.now(timezone.utc).timestamp()),
                    "body": {"text": "", "attachments": []},
                },
                {
                    "timestamp": None,
                    "body": {"text": "No timestamp", "attachments": []},
                },
            ]
        }
        mock_get.return_value = mock_response

        from fetch_max import fetch_max_posts
        posts = fetch_max_posts(123, "fake_token", days_back=30)

        assert len(posts) == 0

    @patch("fetch_max.httpx.get")
    def test_fetch_max_posts_old_filtered(self, mock_get):
        old_ts = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "messages": [
                {
                    "timestamp": old_ts,
                    "body": {"text": "Старый пост", "attachments": []},
                }
            ]
        }
        mock_get.return_value = mock_response

        from fetch_max import fetch_max_posts
        posts = fetch_max_posts(123, "fake_token", days_back=14)

        assert len(posts) == 0
