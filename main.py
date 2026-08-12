import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

# API base URLs
API_BASE_MIHOYO = "https://hyp-api.mihoyo.com/hyp/hyp-connect/api"
API_BASE_HOYOVERSE = "https://sg-hyp-api.hoyoverse.com/hyp/hyp-connect/api"
API_BASE_CLOUD_CN = "https://api-cloudgame.mihoyo.com/hk4e_cg_cn/gamer/api"
API_BASE_CLOUD_SG = "https://sg-cg-api.hoyoverse.com/hk4e_global/cg/gamer/api"

# Configuration
RESOLUTIONS = ((1440, 3120), (1, 1), (1152, 2048))
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
REQUEST_TIMEOUT = httpx.Timeout(30.0)
LAUNCHER_ID_CN = "jGHBHlcOq1"
LAUNCHER_ID_GLOBAL = "VYTpXlbWo8"
COMMIT_MESSAGE_FILE = Path("commit_msg.txt")

# Endpoints
ENDPOINT_GET_GAMES = "getGames"
ENDPOINT_GET_ALL_GAME_INFO = "getAllGameBasicInfo"

type RequestParams = Mapping[str, str | int]


@dataclass(slots=True)
class RunState:
    """Files and output groups changed during one run."""

    updated_folders: set[str] = field(default_factory=set)
    downloaded_files: list[Path] = field(default_factory=list)


def request_with_retry(
    client: httpx.Client,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: RequestParams | None = None,
) -> httpx.Response:
    """Send a GET request, retrying transient transport and server failures."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        retry_error: httpx.HTTPError
        try:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as error:
            if (
                error.response.status_code not in RETRYABLE_STATUS_CODES
                or attempt == RETRY_ATTEMPTS
            ):
                raise
            retry_error = error
        except httpx.TransportError as error:
            if attempt == RETRY_ATTEMPTS:
                raise
            retry_error = error

        delay = RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)
        print(
            f"::warning::Request failed (attempt {attempt}/{RETRY_ATTEMPTS}): "
            f"{retry_error}. Retrying in {delay:g}s."
        )
        time.sleep(delay)

    raise RuntimeError("Retry loop exited unexpectedly")  # pragma: no cover


def fetch_json(
    client: httpx.Client,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: RequestParams | None = None,
) -> dict[str, Any]:
    """Fetch a JSON object, rejecting non-object top-level responses."""
    data = request_with_retry(client, url, headers=headers, params=params).json()
    if not isinstance(data, dict):
        raise TypeError("Expected the API response to be a JSON object")
    return data


def url_process(url: str) -> tuple[str, str, str, str]:
    """Extract the file name, day, month, and year from a URL path."""
    parts = urlsplit(url).path.rstrip("/").split("/")
    if len(parts) < 4 or not all(parts[-4:]):
        raise ValueError(f"Invalid image URL format: {url}")
    return parts[-1], parts[-2], parts[-3], parts[-4]


def image_path(url: str, base_dir: Path) -> Path:
    """Build the archive path for an image URL."""
    file_name, day, month, year = url_process(url)
    return base_dir / year / month / day / file_name


def download_image(
    client: httpx.Client,
    url: str,
    base_dir: Path,
    folder_tag: str,
    state: RunState,
) -> bool:
    """Download an image to its date-based archive directory."""
    try:
        file_path = image_path(url, base_dir)
    except ValueError as error:
        print(f"::error::Cannot archive image: {error}")
        return False

    if file_path.exists():
        print(f"::notice::File exists: {file_path}")
        return True

    file_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"::group::Downloading image: {url}")

    try:
        response = request_with_retry(client, url)
        file_path.write_bytes(response.content)
    except (httpx.HTTPError, OSError) as error:
        print(f"::error::Error downloading {url}: {error}")
        print("::endgroup::")
        return False

    state.downloaded_files.append(file_path)
    state.updated_folders.add(folder_tag)
    print(f"Successfully downloaded: {file_path}")
    print("::endgroup::")
    return True


def get_cloud_backgrounds(
    client: httpx.Client,
    state: RunState,
    *,
    api_base: str,
    output_dir: Path,
    folder_tag: str,
    name: str,
    headers: Mapping[str, str] | None = None,
) -> None:
    """Download cloud-gaming backgrounds for all configured resolutions."""
    for height, width in RESOLUTIONS:
        try:
            data = fetch_json(
                client,
                f"{api_base}/getUIConfig",
                headers=headers,
                params={"height": height, "width": width},
            )
            background_url = data["data"]["bg_image"]["url"]
            if not isinstance(background_url, str) or not background_url:
                raise TypeError("Expected bg_image.url to be a non-empty string")
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            print(f"::error::Failed to fetch {name} cloud background: {error}")
            continue

        download_image(client, background_url, output_dir, folder_tag, state)


def get_cn_cloud(client: httpx.Client, state: RunState) -> None:
    """Download CN cloud-gaming backgrounds."""
    get_cloud_backgrounds(
        client,
        state,
        api_base=API_BASE_CLOUD_CN,
        output_dir=Path("output/cloud_cn"),
        folder_tag="cloud_cn",
        name="CN",
    )


def get_os_sg_cloud(client: httpx.Client, state: RunState) -> None:
    """Download Singapore cloud-gaming backgrounds."""
    get_cloud_backgrounds(
        client,
        state,
        api_base=API_BASE_CLOUD_SG,
        output_dir=Path("output/cloud_sg"),
        folder_tag="cloud_sg",
        name="SG",
        headers={"x-rpc-cg_game_biz": "hk4e_global"},
    )


def mys_wallpaper(client: httpx.Client, state: RunState) -> None:
    """Download wallpapers from MiHoYo BBS (MiYouShe)."""
    print("::group::Checking MYS wallpapers")
    api_url = "https://hk4e-api.mihoyo.com/event/contenthub/v1/wall_papers"
    wallpaper_types = (
        ("0", "Patch Wallpapers"),
        ("1", "Event Wallpapers"),
        ("2", "Character Wallpapers"),
    )

    for wallpaper_type, wallpaper_type_name in wallpaper_types:
        page_number = 1
        while True:
            print(f"Fetching {wallpaper_type_name} at page {page_number}...")
            try:
                data = fetch_json(
                    client,
                    api_url,
                    params={
                        "page": page_number,
                        "size": 100,
                        "type": wallpaper_type,
                        "badge_uid": "100000000",
                        "badge_region": "cn_qd01",
                        "game_biz": "hk4e_cn",
                        "lang": "zh-cn",
                    },
                )
                wallpapers = data["data"]["wallpapers"]
                has_more = data["data"]["has_more"]
                if not isinstance(wallpapers, list) or not isinstance(has_more, bool):
                    raise TypeError("Unexpected MYS pagination response")
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                print(
                    f"::error::Failed to fetch {wallpaper_type_name} "
                    f"page {page_number}: {error}"
                )
                break

            for wallpaper in wallpapers:
                try:
                    wallpaper_title = wallpaper["title"]
                    pictures = wallpaper["pic_list"]
                    if not isinstance(wallpaper_title, str) or not isinstance(
                        pictures, list
                    ):
                        raise TypeError("Unexpected wallpaper entry")
                except (KeyError, TypeError) as error:
                    print(f"::warning::Skipping malformed wallpaper entry: {error}")
                    continue

                base_dir = Path("output/mys") / wallpaper_type_name / wallpaper_title
                for picture in pictures:
                    try:
                        picture_url = picture["url"]
                        if not isinstance(picture_url, str) or not picture_url:
                            raise TypeError(
                                "Expected picture.url to be a non-empty string"
                            )
                        target_file = image_path(picture_url, base_dir)
                    except (KeyError, TypeError, ValueError) as error:
                        print(f"::warning::Skipping malformed wallpaper image: {error}")
                        continue

                    if target_file.exists():
                        continue

                    print(
                        f"Downloading {wallpaper_type_name}/{wallpaper_title} image..."
                    )
                    if not download_image(client, picture_url, base_dir, "mys", state):
                        print(f"::warning::Failed to download {picture_url}")

            if not has_more:
                break
            page_number += 1

    print("::endgroup::")


def download_game_list_backgrounds(
    client: httpx.Client,
    state: RunState,
    data: dict[str, Any],
    output_dir: Path,
    folder_tag: str,
) -> None:
    """Download pure backgrounds from a getGames response."""
    games = data["data"]["games"]
    if not isinstance(games, list):
        raise TypeError("Expected data.games to be a list")

    for game in games:
        try:
            game_biz = game["biz"]
            background_url = game["display"]["background"]["url"]
            if not isinstance(game_biz, str) or not isinstance(background_url, str):
                raise TypeError("Unexpected game entry")
        except (KeyError, TypeError) as error:
            print(f"::warning::Skipping malformed game entry: {error}")
            continue

        download_image(
            client,
            background_url,
            output_dir / game_biz,
            folder_tag,
            state,
        )


def optional_asset_url(background: Mapping[str, Any], asset_name: str) -> str | None:
    """Return an optional background asset URL, validating its shape."""
    asset = background.get(asset_name)
    if asset is None:
        return None
    if not isinstance(asset, Mapping):
        raise TypeError(f"Expected {asset_name} to be an object")

    url = asset.get("url")
    if url in (None, ""):
        return None
    if not isinstance(url, str):
        raise TypeError(f"Expected {asset_name}.url to be a string")
    return url


def download_game_info_backgrounds(
    client: httpx.Client,
    state: RunState,
    data: dict[str, Any],
    output_dir: Path,
    folder_tag: str,
) -> None:
    """Download static, animated, and theme assets from game information."""
    game_info_list = data["data"]["game_info_list"]
    if not isinstance(game_info_list, list):
        raise TypeError("Expected data.game_info_list to be a list")

    for game_info in game_info_list:
        try:
            game_biz = game_info["game"]["biz"]
            backgrounds = game_info["backgrounds"]
            if not isinstance(game_biz, str) or not isinstance(backgrounds, list):
                raise TypeError("Unexpected game information entry")
        except (KeyError, TypeError) as error:
            print(f"::warning::Skipping malformed game information: {error}")
            continue

        for background in backgrounds:
            if not isinstance(background, Mapping):
                print("::warning::Skipping malformed background entry")
                continue

            try:
                background_url = optional_asset_url(background, "background")
                video_url = optional_asset_url(background, "video")
                theme_url = optional_asset_url(background, "theme")
            except TypeError as error:
                print(f"::warning::Skipping malformed background entry: {error}")
                continue

            assets = (
                ("background", background_url),
                ("video", video_url),
                ("theme", theme_url),
            )
            for asset_name, asset_url in assets:
                if asset_url:
                    download_image(
                        client,
                        asset_url,
                        output_dir / game_biz / asset_name,
                        folder_tag,
                        state,
                    )


def get_hoyoplay_backgrounds(
    client: httpx.Client,
    state: RunState,
    api_base: str,
    launcher_id: str,
    endpoint: str,
    output_dir: Path,
    folder_tag: str,
    languages: Sequence[str] = ("zh-cn",),
) -> None:
    """Download HoYoPlay backgrounds for the requested languages."""
    if endpoint not in {ENDPOINT_GET_GAMES, ENDPOINT_GET_ALL_GAME_INFO}:
        raise ValueError(f"Unsupported HoYoPlay endpoint: {endpoint}")

    for language in languages:
        params: dict[str, str] = {
            "launcher_id": launcher_id,
            "language": language,
        }
        if endpoint == ENDPOINT_GET_ALL_GAME_INFO:
            params["game_id"] = ""

        url = f"{api_base}/{endpoint}"
        try:
            data = fetch_json(client, url, params=params)
            if endpoint == ENDPOINT_GET_GAMES:
                download_game_list_backgrounds(
                    client, state, data, output_dir, folder_tag
                )
            else:
                download_game_info_backgrounds(
                    client, state, data, output_dir, folder_tag
                )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            print(
                f"::error::Failed to process HoYoPlay response for "
                f"{language} ({url}): {error}"
            )


def get_hoyoplay_cn_pure(client: httpx.Client, state: RunState) -> None:
    """Download CN HoYoPlay pure backgrounds (without text)."""
    get_hoyoplay_backgrounds(
        client,
        state,
        API_BASE_MIHOYO,
        LAUNCHER_ID_CN,
        ENDPOINT_GET_GAMES,
        Path("output/hoyoplay_cn_pure"),
        "hoyoplay_cn_pure",
    )


def get_hoyoplay_cn_text(client: httpx.Client, state: RunState) -> None:
    """Download CN HoYoPlay backgrounds with text."""
    get_hoyoplay_backgrounds(
        client,
        state,
        API_BASE_MIHOYO,
        LAUNCHER_ID_CN,
        ENDPOINT_GET_ALL_GAME_INFO,
        Path("output/hoyoplay_cn_text"),
        "hoyoplay_cn_text",
    )


def get_hoyoplay_global_pure(client: httpx.Client, state: RunState) -> None:
    """Download global HoYoPlay pure backgrounds (without text)."""
    get_hoyoplay_backgrounds(
        client,
        state,
        API_BASE_HOYOVERSE,
        LAUNCHER_ID_GLOBAL,
        ENDPOINT_GET_GAMES,
        Path("output/hoyoplay_global_pure"),
        "hoyoplay_global_pure",
    )


def get_hoyoplay_global_text(client: httpx.Client, state: RunState) -> None:
    """Download global HoYoPlay backgrounds with text in multiple languages."""
    languages = (
        "zh-cn",
        "zh-tw",
        "en-us",
        "ja-jp",
        "ko-kr",
        "fr-fr",
        "de-de",
        "es-es",
        "pt-pt",
        "ru-ru",
        "id-id",
        "vi-vn",
        "th-th",
    )
    get_hoyoplay_backgrounds(
        client,
        state,
        API_BASE_HOYOVERSE,
        LAUNCHER_ID_GLOBAL,
        ENDPOINT_GET_ALL_GAME_INFO,
        Path("output/hoyoplay_global_text"),
        "hoyoplay_global_text",
        languages,
    )


def write_run_summary(state: RunState) -> None:
    """Write the commit message and print the GitHub Actions run summary."""
    if state.updated_folders:
        folders = ", ".join(f"`{folder}`" for folder in sorted(state.updated_folders))
        commit_message = f"Update {folders}"
    else:
        commit_message = "No updates"
    COMMIT_MESSAGE_FILE.write_text(commit_message, encoding="utf-8")

    print("::group::Run Summary")
    if state.downloaded_files:
        print("## Run Summary\n\n### Updated Files")
        for file_path in state.downloaded_files:
            print(f"- {file_path}")
    else:
        print("## Run Summary\n\n**No files updated.**")
    print("::endgroup::")


def main() -> None:
    """Download and archive all configured background-image sources."""
    state = RunState()
    print("::group::Starting background image downloads")

    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        get_cn_cloud(client, state)
        get_os_sg_cloud(client, state)
        mys_wallpaper(client, state)
        get_hoyoplay_cn_pure(client, state)
        get_hoyoplay_cn_text(client, state)
        get_hoyoplay_global_pure(client, state)
        get_hoyoplay_global_text(client, state)

    print("::endgroup::")
    write_run_summary(state)


if __name__ == "__main__":
    main()
