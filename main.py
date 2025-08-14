import httpx
import os

RESOLUTION_SET = [[1440, 3120], [1, 1], [1152, 2048]]
RETRY_TIMES = 3

updated_folders = set()
downloaded_files = []  # Added to track newly downloaded file paths


def url_process(url: str) -> tuple:
    url = url.split("/")
    return url[-1], url[-2], url[-3], url[-4]


def download_image(url: str, base_dir: str, folder_tag: str, retry: bool = False) -> bool:
    file_name, day, month, year = url_process(url)
    out_dir = f"{base_dir}/{year}/{month}/{day}/"
    file_path = f"{out_dir}{file_name}"
    if os.path.exists(file_path):
        print(f"::notice:: File exists: {file_path}")
        return True
    os.makedirs(out_dir, exist_ok=True)
    print(f"::group:: Downloading image: {url}")
    try:
        if retry:
            error_message = ""
            for _ in range(RETRY_TIMES):
                try:
                    response = httpx.get(url)
                    break
                except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectTimeout) as e:
                    error_message += f"```{str(e)}```\n"
            else:
                print(f"::error title=Failed to download image::{error_message}")
                print("::endgroup::")
                return False
        else:
            response = httpx.get(url)
    except Exception as e:
        print(f"::error:: Error downloading {url}: {e}")
        print("::endgroup::")
        return False
    with open(file_path, "wb") as f:
        f.write(response.content)
    downloaded_files.append(file_path)  # Record newly downloaded file
    updated_folders.add(folder_tag)
    print(f"::endgroup:: Successfully downloaded: {file_path}")
    return True


def get_cn_cloud():
    for r in RESOLUTION_SET:
        url = "https://api-cloudgame.mihoyo.com/hk4e_cg_cn/gamer/api/getUIConfig?height=%s&width=%s" % (r[0], r[1])
        response = httpx.get(url).json()
        background_url = response["data"]["bg_image"]["url"]
        download_image(background_url, "./output/cloud_cn", "cloud_cn")


def get_os_sg_cloud():
    for r in RESOLUTION_SET:
        url = "https://sg-cg-api.hoyoverse.com/hk4e_global/cg/gamer/api/getUIConfig?height=%s&width=%s" % (r[0], r[1])
        headers = {
            "x-rpc-cg_game_biz": "hk4e_global",
        }
        response = httpx.get(url, headers=headers).json()
        background_url = response["data"]["bg_image"]["url"]
        download_image(background_url, "./output/cloud_sg", "cloud_sg")


def try_all_resolution():
    import multiprocessing
    import threading
    import json

    client = httpx.Client(headers={"x-rpc-cg_game_biz": "hk4e_global"})
    background_url_list = []
    log = open("log.txt", "w")

    def process_resolution(x, y):
        url = "https://sg-cg-api.hoyoverse.com/hk4e_global/cg/gamer/api/getUIConfig?height=%s&width=%s" % (x, y)
        response = client.get(url).json()
        background_url = response["data"]["bg_image"]["url"]
        print(f"Resolution: {x}x{y}, URL: {background_url}")
        log.write(f"Resolution: {x}x{y}, URL: {background_url}\n")
        background_url_list.append(background_url)

    num_cores = multiprocessing.cpu_count()
    threads = []
    for i in range(1, 3840, 10):
        for j in range(1, 2160, 10):
            if len(threads) >= num_cores:
                for thread in threads:
                    thread.join()
                del threads[:]
            thread = threading.Thread(target=process_resolution, args=(i, j))
            thread.start()
            threads.append(thread)

    for thread in threads:
        thread.join()

    client.close()
    log.close()
    background_url_list = list(set(background_url_list))
    with open("background_url_list.json", "w+") as f:
        json.dump(background_url_list, f, indent=4)


def mys_wallpaper():
    print("::group::Checking MYS wallpaper")
    api_url = ("https://hk4e-api.mihoyo.com/event/contenthub/v1/wall_papers?page={page_number}&size=100&type={type}&bad"
               "ge_uid=100000000&badge_region=cn_qd01&game_biz=hk4e_cn&lang=zh-cn")
    wallpaper_type_list = [
        {"type": "0", "name": "Patch Wallpapers"},
        {"type": "1", "name": "Event Wallpapers"},
        {"type": "2", "name": "Character Wallpapers"},
    ]
    for w in wallpaper_type_list:
        page_number = 1
        while True:
            print(f"Fetching {w['name']} at page {page_number}...")
            this_url = api_url.format(page_number=page_number, type=w["type"])
            print(f"URL: {this_url}")
            try:
                response = httpx.get(this_url).json()
            except UnicodeDecodeError:
                break
            for wallpaper in response["data"]["wallpapers"]:
                wallpaper_title = wallpaper["title"]
                wallpaper_url_list = [pic["url"] for pic in wallpaper["pic_list"]]
                for url in wallpaper_url_list:
                    base_dir = f"./output/mys/{w['name']}/{wallpaper_title}"
                    file_name, day, month, year = url_process(url)
                    out_dir = f"{base_dir}/{year}/{month}/{day}/"
                    target_file = f"{out_dir}{file_name}"
                    if os.path.exists(target_file):
                        continue
                    print(f"Downloading {w['name']}/{wallpaper_title} image...")
                    if not download_image(url, base_dir, "mys", retry=True):
                        return None
            if not response["data"]["has_more"]:
                break
            else:
                page_number += 1
    print("::endgroup::")


def get_hoyoplay_cn_pure():
    data = httpx.get(
        "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGames?launcher_id=jGHBHlcOq1&language=zh-cn").json()
    data = data["data"]["games"]
    for game in data:
        game_biz = game["biz"]
        background_url = game["display"]["background"]["url"]
        base_dir = f"./output/hoyoplay_cn_pure/{game_biz}"
        download_image(background_url, base_dir, "hoyoplay_cn_pure")


def get_hoyoplay_cn_text():
    data = httpx.get(
        "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getAllGameBasicInfo?launcher_id=jGHBHlcOq1&language=zh-cn&game_id=").json()
    data = data["data"]["game_info_list"]
    for game in data:
        game_biz = game["game"]["biz"]
        for bg in game["backgrounds"]:
            background_url = bg["background"]["url"]
            base_dir = f"./output/hoyoplay_cn_text/{game_biz}"
            download_image(background_url, base_dir, "hoyoplay_cn_text")


def get_hoyoplay_global_pure():
    data = httpx.get(
        "https://sg-hyp-api.hoyoverse.com/hyp/hyp-connect/api/getGames?launcher_id=VYTpXlbWo8&language=zh-cn").json()
    data = data["data"]["games"]
    for game in data:
        game_biz = game["biz"]
        background_url = game["display"]["background"]["url"]
        base_dir = f"./output/hoyoplay_global_pure/{game_biz}"
        download_image(background_url, base_dir, "hoyoplay_global_pure")


def get_hoyoplay_global_text():
    language_set = ["zh-cn", "zh-tw", "en-us", "ja-jp", "ko-kr", "fr-fr", "de-de", "es-es", "pt-pt", "ru-ru",
                    "id-id", "vi-vn", "th-th"]
    for language in language_set:
        data = httpx.get(
            f"https://sg-hyp-api.hoyoverse.com/hyp/hyp-connect/api/getAllGameBasicInfo?launcher_id=VYTpXlbWo8&language={language}").json()
        data = data["data"]["game_info_list"]
        for game in data:
            game_biz = game["game"]["biz"]
            for bg in game["backgrounds"]:
                background_url = bg["background"]["url"]
                base_dir = f"./output/hoyoplay_global_text/{game_biz}"
                download_image(background_url, base_dir, "hoyoplay_global_text")


def main():
    get_cn_cloud()
    get_os_sg_cloud()
    # try_all_resolution()
    mys_wallpaper()
    get_hoyoplay_cn_pure()
    get_hoyoplay_cn_text()
    get_hoyoplay_global_pure()
    get_hoyoplay_global_text()
    commit_message = "Update " + ",".join("`" + folder + "`" for folder in sorted(updated_folders))
    with open("commit_msg.txt", "w") as f:
        f.write(commit_message)

    print("::group::Run Summary")
    if not downloaded_files:
        summary = "## Run Summary\n\n**No files updated.**"
    else:
        summary = "## Run Summary\n\n### Updated Files\n"
        for file in downloaded_files:
            summary += f"- {file}\n"
    print(summary)
    print("::endgroup::")


if __name__ == "__main__":
    main()
