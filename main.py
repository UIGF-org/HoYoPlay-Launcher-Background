import httpx
import os
from typing import Optional

# API Base URLs
API_BASE_MIHOYO = "https://hyp-api.mihoyo.com/hyp/hyp-connect/api"
API_BASE_HOYOVERSE = "https://sg-hyp-api.hoyoverse.com/hyp/hyp-connect/api"
API_BASE_CLOUD_CN = "https://api-cloudgame.mihoyo.com/hk4e_cg_cn/gamer/api"
API_BASE_CLOUD_SG = "https://sg-cg-api.hoyoverse.com/hk4e_global/cg/gamer/api"

# Configuration Constants
RESOLUTION_SET = [[1440, 3120], [1, 1], [1152, 2048]]
RETRY_TIMES = 3
LAUNCHER_ID_CN = "jGHBHlcOq1"
LAUNCHER_ID_GLOBAL = "VYTpXlbWo8"
COMMIT_MESSAGE_FILE = "commit_msg.txt"

# Endpoint Constants
ENDPOINT_GET_GAMES = "getGames"
ENDPOINT_GET_ALL_GAME_INFO = "getAllGameBasicInfo"

# Global state
updated_folders = set()
downloaded_files = []


def url_process(url: str) -> tuple[str, str, str, str]:
    """Extract file name, day, month, year from URL path."""
    parts = url.split("/")
    return parts[-1], parts[-2], parts[-3], parts[-4]


def download_image(url: str, base_dir: str, folder_tag: str, retry: bool = False) -> bool:
    """Download an image from URL and save it to the appropriate directory structure."""
    file_name, day, month, year = url_process(url)
    out_dir = os.path.join(base_dir, year, month, day)
    file_path = os.path.join(out_dir, file_name)
    
    if os.path.exists(file_path):
        print(f"::notice:: File exists: {file_path}")
        return True
    
    os.makedirs(out_dir, exist_ok=True)
    print(f"::group:: Downloading image: {url}")
    
    response = None
    try:
        if retry:
            error_messages = []
            for attempt in range(RETRY_TIMES):
                try:
                    response = httpx.get(url, timeout=30.0)
                    response.raise_for_status()
                    break
                except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectTimeout, httpx.HTTPStatusError) as e:
                    error_messages.append(f"Attempt {attempt + 1}: {str(e)}")
            else:
                print(f"::error title=Failed to download image::{'  '.join(error_messages)}")
                print("::endgroup::")
                return False
        else:
            response = httpx.get(url, timeout=30.0)
            response.raise_for_status()
    except Exception as e:
        print(f"::error:: Error downloading {url}: {e}")
        print("::endgroup::")
        return False
    
    with open(file_path, "wb") as f:
        f.write(response.content)
    
    downloaded_files.append(file_path)
    updated_folders.add(folder_tag)
    print(f"::endgroup:: Successfully downloaded: {file_path}")
    return True


def get_cn_cloud():
    """Download CN cloud gaming backgrounds for multiple resolutions."""
    for height, width in RESOLUTION_SET:
        url = f"{API_BASE_CLOUD_CN}/getUIConfig?height={height}&width={width}"
        try:
            response = httpx.get(url, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            background_url = data["data"]["bg_image"]["url"]
            download_image(background_url, "./output/cloud_cn", "cloud_cn")
        except (httpx.HTTPError, KeyError) as e:
            print(f"::error::Failed to fetch CN cloud background: {e}")


def get_os_sg_cloud():
    """Download Singapore cloud gaming backgrounds for multiple resolutions."""
    headers = {"x-rpc-cg_game_biz": "hk4e_global"}
    for height, width in RESOLUTION_SET:
        url = f"{API_BASE_CLOUD_SG}/getUIConfig?height={height}&width={width}"
        try:
            response = httpx.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            background_url = data["data"]["bg_image"]["url"]
            download_image(background_url, "./output/cloud_sg", "cloud_sg")
        except (httpx.HTTPError, KeyError) as e:
            print(f"::error::Failed to fetch SG cloud background: {e}")


def mys_wallpaper():
    """Download wallpapers from MiHoYo BBS (MiYouShe)."""
    print("::group::Checking MYS wallpaper")
    api_url = ("https://hk4e-api.mihoyo.com/event/contenthub/v1/wall_papers"
               "?page={page_number}&size=100&type={type}"
               "&badge_uid=100000000&badge_region=cn_qd01&game_biz=hk4e_cn&lang=zh-cn")
    
    wallpaper_types = [
        {"type": "0", "name": "Patch Wallpapers"},
        {"type": "1", "name": "Event Wallpapers"},
        {"type": "2", "name": "Character Wallpapers"},
    ]
    
    for wallpaper_type in wallpaper_types:
        page_number = 1
        while True:
            print(f"Fetching {wallpaper_type['name']} at page {page_number}...")
            url = api_url.format(page_number=page_number, type=wallpaper_type["type"])
            print(f"URL: {url}")
            
            try:
                response = httpx.get(url, timeout=30.0)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, UnicodeDecodeError) as e:
                print(f"Error fetching page {page_number}: {e}")
                break
            
            for wallpaper in data["data"]["wallpapers"]:
                wallpaper_title = wallpaper["title"]
                for pic in wallpaper["pic_list"]:
                    pic_url = pic["url"]
                    base_dir = os.path.join("./output/mys", wallpaper_type['name'], wallpaper_title)
                    
                    # Check if file exists before attempting download
                    file_name, day, month, year = url_process(pic_url)
                    target_file = os.path.join(base_dir, year, month, day, file_name)
                    if os.path.exists(target_file):
                        continue
                    
                    print(f"Downloading {wallpaper_type['name']}/{wallpaper_title} image...")
                    if not download_image(pic_url, base_dir, "mys", retry=True):
                        print(f"::warning::Failed to download {pic_url}")
                        continue
            
            if not data["data"]["has_more"]:
                break
            page_number += 1
    
    print("::endgroup::")


def get_hoyoplay_backgrounds(api_base: str, launcher_id: str, endpoint: str, 
                            output_dir: str, folder_tag: str, languages: Optional[list[str]] = None):
    """Generic function to download HoYoPlay backgrounds."""
    if languages is None:
        languages = ["zh-cn"]
    
    for language in languages:
        url = f"{api_base}/{endpoint}?launcher_id={launcher_id}&language={language}"
        if endpoint == ENDPOINT_GET_ALL_GAME_INFO:
            url += "&game_id="
        
        try:
            response = httpx.get(url, timeout=30.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            print(f"::error::Failed to fetch {url}: {e}")
            continue
        
        if endpoint == ENDPOINT_GET_GAMES:
            games = data["data"]["games"]
            for game in games:
                game_biz = game["biz"]
                background_url = game["display"]["background"]["url"]
                base_dir = os.path.join(output_dir, game_biz)
                download_image(background_url, base_dir, folder_tag)
        else:  # getAllGameBasicInfo
            game_info_list = data["data"]["game_info_list"]
            for game in game_info_list:
                game_biz = game["game"]["biz"]
                for bg in game["backgrounds"]:
                    background_url = bg["background"]["url"]
                    base_dir = os.path.join(output_dir, game_biz)
                    download_image(background_url, base_dir, folder_tag)


def get_hoyoplay_cn_pure():
    """Download CN HoYoPlay pure backgrounds (without text)."""
    get_hoyoplay_backgrounds(API_BASE_MIHOYO, LAUNCHER_ID_CN, ENDPOINT_GET_GAMES,
                            "./output/hoyoplay_cn_pure", "hoyoplay_cn_pure")


def get_hoyoplay_cn_text():
    """Download CN HoYoPlay backgrounds with text."""
    get_hoyoplay_backgrounds(API_BASE_MIHOYO, LAUNCHER_ID_CN, ENDPOINT_GET_ALL_GAME_INFO,
                            "./output/hoyoplay_cn_text", "hoyoplay_cn_text")


def get_hoyoplay_global_pure():
    """Download global HoYoPlay pure backgrounds (without text)."""
    get_hoyoplay_backgrounds(API_BASE_HOYOVERSE, LAUNCHER_ID_GLOBAL, ENDPOINT_GET_GAMES,
                            "./output/hoyoplay_global_pure", "hoyoplay_global_pure")


def get_hoyoplay_global_text():
    """Download global HoYoPlay backgrounds with text in multiple languages."""
    languages = ["zh-cn", "zh-tw", "en-us", "ja-jp", "ko-kr", "fr-fr", 
                 "de-de", "es-es", "pt-pt", "ru-ru", "id-id", "vi-vn", "th-th"]
    get_hoyoplay_backgrounds(API_BASE_HOYOVERSE, LAUNCHER_ID_GLOBAL, ENDPOINT_GET_ALL_GAME_INFO,
                            "./output/hoyoplay_global_text", "hoyoplay_global_text", languages)


def main():
    """Main function to download all background images."""
    print("::group::Starting background image downloads")
    
    # Download from various sources
    get_cn_cloud()
    get_os_sg_cloud()
    mys_wallpaper()
    get_hoyoplay_cn_pure()
    get_hoyoplay_cn_text()
    get_hoyoplay_global_pure()
    get_hoyoplay_global_text()
    
    print("::endgroup::")
    
    # Generate commit message
    if updated_folders:
        commit_message = "Update " + ", ".join(f"`{folder}`" for folder in sorted(updated_folders))
    else:
        commit_message = "No updates"
    
    with open(COMMIT_MESSAGE_FILE, "w", encoding="utf-8") as f:
        f.write(commit_message)
    
    # Print summary
    print("::group::Run Summary")
    if not downloaded_files:
        print("## Run Summary\n\n**No files updated.**")
    else:
        print("## Run Summary\n\n### Updated Files")
        for file_path in downloaded_files:
            print(f"- {file_path}")
    print("::endgroup::")


if __name__ == "__main__":
    main()
