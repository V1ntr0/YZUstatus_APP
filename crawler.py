import requests
from bs4 import BeautifulSoup
import json
import re
import os
import time
import firebase_admin
from firebase_admin import credentials, messaging

# 1. 初始化 Firebase 憑證 (請確保 serviceAccountKey.json 跟這支程式在同一個資料夾)
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

offices = {
    "教務處": "http://140.138.172.124/demo2/index.php/zh/academic-affairs",
    "學務處": "http://140.138.172.124/demo2/index.php/zh/student-affairs",
    "總務處": "http://140.138.172.124/demo2/index.php/zh/general-affairs",
    "研發處": "http://140.138.172.124/demo2/index.php/zh/research-and-development",
    "資服處": "http://140.138.172.124/demo2/index.php/zh/library-and-information-services",
    "全球處": "http://140.138.172.124/demo2/index.php/zh/global-affairs"
}

date_pattern = re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[-/日]')
CACHE_FILE = "sent_announcements.json"

# 載入過去已發送過的公告清單，避免重複推播
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_cache(cache):
    if len(cache) > 200:
        cache = cache[-200:]
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=4)

def send_push_notification(title, office_name):
    try:
        # 發送給所有訂閱 'announcements' 主題的手機 App 用戶
        message = messaging.Message(
            notification=messaging.Notification(
                title=f"📢 【{office_name}新公告】",
                body=title,
            ),
            topic='announcements',
        )
        response = messaging.send(message)
        print(f"  🚀 成功發送 Firebase 推播通知: {title}")
    except Exception as e:
        print(f"  ❌ 推播失敗: {e}")

def job():
    print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 正在檢查學校最新公告...")
    sent_list = load_cache()
    all_data = {}
    new_announcements_found = 0

    for name, url in offices.items():
        all_data[name] = []
        try:
            response = requests.get(url, timeout=5)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                rows = soup.select('table.category tbody tr, .cat-list-row0, .cat-list-row1')
                
                for row in rows:
                    link_tag = row.select_one('th.list-title a, td.list-title a')
                    if not link_tag:
                        continue
                        
                    title = link_tag.text.strip()
                    href = link_tag.get('href')
                    full_url = f"http://140.138.172.124{href}" if href.startswith('/') else href
                    
                    date = "無日期"
                    row_match = date_pattern.search(row.text)
                    if row_match:
                        date = row_match.group(0)
                    
                    author_tag = row.select_one('td.list-author, .author')
                    author = author_tag.text.strip() if author_tag else name
                    
                    hits_tag = row.select_one('td.list-hits, .hits')
                    hits = hits_tag.text.strip() if hits_tag else "0"

                    content = "無法取得內文"
                    images = []
                    videos = []
                    
                    try:
                        detail_res = requests.get(full_url, timeout=5)
                        detail_res.encoding = 'utf-8'
                        if detail_res.status_code == 200:
                            detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                            if date == "無日期":
                                detail_match = date_pattern.search(detail_soup.text)
                                if detail_match:
                                    date = detail_match.group(0)
                            
                            article_body = detail_soup.select_one('.item-page') or detail_soup.select_one('div[itemprop="articleBody"]')
                            if article_body:
                                content = article_body.text.strip()
                                for img in article_body.select('img'):
                                    img_src = img.get('src')
                                    if img_src:
                                        full_img_url = img_src if img_src.startswith('http') else f"http://140.138.172.124{img_src}"
                                        images.append(full_img_url)
                                for iframe in article_body.select('iframe'):
                                    iframe_src = iframe.get('src')
                                    if iframe_src:
                                        if iframe_src.startswith('//'):
                                            iframe_src = f"https:{iframe_src}"
                                        videos.append(iframe_src)
                                for a_tag in article_body.select('a'):
                                    a_href = a_tag.get('href', '')
                                    if 'youtube.com' in a_href or 'youtu.be' in a_href or a_href.endswith(('.mp4', '.mov')):
                                        if a_href not in videos:
                                            videos.append(a_href)
                    except Exception:
                        pass
                    
                    item_id = f"[{name}] {title}"
                    
                    # 檢查是否為全新公告
                    if item_id not in sent_list and len(sent_list) > 0:
                        print(f"  🔥 發現新公告！[{name}] {title}")
                        send_push_notification(title, name)
                        sent_list.append(item_id)
                        new_announcements_found += 1
                    elif len(sent_list) == 0:
                        # 第一次初始化時，先把現有的加入快取，不發推播
                        sent_list.append(item_id)

                    all_data[name].append({
                        "title": title,
                        "date": date,
                        "author": author,
                        "hits": hits,
                        "category": name,
                        "url": full_url,
                        "content": content,
                        "images": images,
                        "videos": videos
                    })
        except Exception as e:
            print(f"無法連線至 {name}: {e}")

    # 儲存最新的 JSON 供 App 聯網讀取
    with open("announcements.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)
    
    save_cache(sent_list)
    print(f"✅ 檢查完畢！本次新增 {new_announcements_found} 筆新公告。")
    upload_to_github()

from github import Github

# 自動上傳至 GitHub 的函式
def upload_to_github():
    try:
        token = os.environ.get("GITHUB_TOKEN") or "你的_GITHUB_TOKEN"
        g = Github(token)
        repo = g.get_repo("V1ntr0/YZUstatus_APP")
        
        # 讀取本地剛剛寫好的 JSON 內容
        with open("announcements.json", "r", encoding="utf-8") as f:
            local_content = f.read()
            
        try:
            # 1. 嘗試取得遠端 GitHub 上現有的檔案
            file = repo.get_contents("announcements.json")
            remote_content = file.decoded_content.decode("utf-8")
            
            # 2. 比對本地跟遠端內容是否一模一樣
            if remote_content == local_content:
                print("  💤 公告內容沒有改變，不需要重複 Commit。")
                return  # 直接結束，不執行更新
            
            # 3. 如果內容不一樣，才執行更新
            repo.update_file(file.path, "Auto update (New announcements detected)", local_content, file.sha)
            print("  ☁️ 偵測到新公告！成功同步至 GitHub 雲端！")
            
        except Exception:
            # 如果遠端還沒有這個檔案（第一次執行），就直接建立
            repo.create_file("announcements.json", "Initial commit", local_content)
            print("  ☁️ 初始化：成功建立 announcements.json！")
            
    except Exception as e:
        print(f"  ❌ 雲端同步失敗: {e}")

# 主程式進入點：設定成無限迴圈，每隔 60 秒自動檢查一次
if __name__ == "__main__":
    print("🚀 元智公告即時監控與推播伺服器已啟動...")
    #while True:
    job()
        #print("⏳ 等待 60 秒後進行下一次檢查...\n")
   #     time.sleep(60)
