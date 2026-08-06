import requests
from bs4 import BeautifulSoup
import json
import re
import os
import time
import firebase_admin
from firebase_admin import credentials, messaging
from github import Github

# 1. 初始化 Firebase 憑證
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

def send_push_notification(title, office_name):
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=f"📢 【{office_name}新公告】",
                body=title,
            ),
            topic='announcements',
        )
        messaging.send(message)
        print(f"  🚀 成功發送 Firebase 推播通知: {title}")
    except Exception as e:
        print(f"  ❌ 推播失敗: {e}")

def job():
    print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 正在檢查學校最新公告...")
    
    # 1. 先從 GitHub 遠端抓取現有的 announcements.json 來當作比對基準
    existing_titles = set()
    try:
        token = os.environ.get("GITHUB_TOKEN")
        g = Github(token)
        repo = g.get_repo("V1ntr0/YZUstatus_APP") # 你的帳號/專案
        file = repo.get_contents("announcements.json")
        old_data = json.loads(file.decoded_content.decode("utf-8"))
        for category, items in old_data.items():
            for item in items:
                existing_titles.add(f"[{category}] {item['title']}")
    except Exception:
        print("  ⚠️ 遠端尚無舊的 announcements.json（初次執行）")

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
                    except Exception:
                        pass
                    
                    item_id = f"[{name}] {title}"
                    
                    # 如果遠端舊資料抓得到，且這個 item 不在舊清單裡 ➔ 代表是全新公告！
                    if len(existing_titles) > 0 and item_id not in existing_titles:
                        print(f"  🔥 發現新公告！{item_id}")
                        send_push_notification(title, name)
                        new_announcements_found += 1

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

    # 儲存本地 JSON
    with open("announcements.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)
        
    print(f"✅ 檢查完畢！本次新增 {new_announcements_found} 筆新公告。")
    upload_to_github()

# 上傳至 GitHub 的函式
def upload_to_github():
    try:
        token = os.environ.get("GITHUB_TOKEN")
        g = Github(token)
        repo = g.get_repo("V1ntr0/YZUstatus_APP")
        
        with open("announcements.json", "r", encoding="utf-8") as f:
            local_content = f.read()
            
        try:
            file = repo.get_contents("announcements.json")
            remote_content = file.decoded_content.decode("utf-8")
            
            if remote_content == local_content:
                print("  💤 公告內容沒有改變，不需要重複 Commit。")
                return 
            
            repo.update_file(file.path, "Auto update (New announcements detected)", local_content, file.sha)
            print("  ☁️ 偵測到新公告！成功同步至 GitHub 雲端！")
            
        except Exception:
            repo.create_file("announcements.json", "Initial commit", local_content)
            print("  ☁️ 初始化：成功建立 announcements.json！")
            
    except Exception as e:
        print(f"  ❌ 雲端同步失敗: {e}")

if __name__ == "__main__":
    job()
