import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

import main as app


def mock_client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, timeout=app.REQUEST_TIMEOUT)


class RetryTests(unittest.TestCase):
    def test_retries_transient_http_status(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            status_code = 503 if attempts == 1 else 200
            return httpx.Response(status_code, request=request)

        with (
            mock_client(httpx.MockTransport(handler)) as client,
            patch.object(app.time, "sleep") as sleep,
        ):
            response = app.request_with_retry(client, "https://example.test/image")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(attempts, 2)
        sleep.assert_called_once_with(app.RETRY_BACKOFF_SECONDS)

    def test_does_not_retry_non_transient_http_status(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(404, request=request)

        with mock_client(httpx.MockTransport(handler)) as client:
            with self.assertRaises(httpx.HTTPStatusError):
                app.request_with_retry(client, "https://example.test/missing")

        self.assertEqual(attempts, 1)


class ResponseHandlingTests(unittest.TestCase):
    def test_empty_video_does_not_skip_theme(self) -> None:
        data = {
            "data": {
                "game_info_list": [
                    {
                        "game": {"biz": "test_game"},
                        "backgrounds": [
                            {
                                "background": {
                                    "url": "https://cdn.test/2026/08/12/background.webp"
                                },
                                "video": {"url": ""},
                                "theme": {
                                    "url": "https://cdn.test/2026/08/12/theme.webp"
                                },
                            }
                        ],
                    }
                ]
            }
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=data, request=request)

        with (
            mock_client(httpx.MockTransport(handler)) as client,
            patch.object(app, "download_image") as download_image,
        ):
            app.get_hoyoplay_backgrounds(
                client,
                app.RunState(),
                "https://api.test",
                "launcher",
                app.ENDPOINT_GET_ALL_GAME_INFO,
                Path("output"),
                "test",
            )

        downloaded_urls = [call.args[1] for call in download_image.call_args_list]
        self.assertEqual(
            downloaded_urls,
            [
                "https://cdn.test/2026/08/12/background.webp",
                "https://cdn.test/2026/08/12/theme.webp",
            ],
        )

    def test_malformed_hoyoplay_response_does_not_escape(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {}}, request=request)

        with (
            mock_client(httpx.MockTransport(handler)) as client,
            patch.object(app, "download_image") as download_image,
        ):
            app.get_hoyoplay_backgrounds(
                client,
                app.RunState(),
                "https://api.test",
                "launcher",
                app.ENDPOINT_GET_GAMES,
                Path("output"),
                "test",
            )

        download_image.assert_not_called()

    def test_malformed_mys_response_does_not_escape(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {}}, request=request)

        with mock_client(httpx.MockTransport(handler)) as client:
            app.mys_wallpaper(client, app.RunState())


if __name__ == "__main__":
    unittest.main()
