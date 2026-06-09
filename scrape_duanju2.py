#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions 适配版 - 自动保存到 output/ 目录
"""

import sys
import json
import re
import time
import csv
import os
from urllib.parse import urljoin
from datetime import datetime

# ============== 尝试导入HTTP库 ==============
HTTP_BACKEND = None
requests = None

try:
    from curl_cffi import requests as curl_requests
    requests = curl_requests
    HTTP_BACKEND = "curl_cffi"
    print("[+] 使用 curl_cffi 后端")
except ImportError:
    pass

if HTTP_BACKEND is None:
    try:
        import cloudscraper
        requests = cloudscraper.create_scraper()
        HTTP_BACKEND = "cloudscraper"
        print("[+] 使用 cloudscraper 后端")
    except ImportError:
        pass

if HTTP_BACKEND is None:
    import requests as std_requests
    requests = std_requests
    HTTP_BACKEND = "requests"
    print("[!] 使用标准 requests")

from bs4 import BeautifulSoup

# ============== 配置 ==============
BASE_URL = "https://duanju2.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

CATEGORIES = {
    "女频恋爱": "/show/duanju---%E5%A5%B3%E9%A2%91%E6%81%8B%E7%88%B1--------.html",
    "脑洞悬疑": "/show/duanju---%E8%84%91%E6%B4%9E%E6%82%AC%E7%96%91--------.html",
    "年代穿越": "/show/duanju---%E5%B9%B4%E4%BB%A3%E7%A9%BF%E8%B6%8A--------.html",
    "古装仙侠": "/show/duanju---%E5%8F%A4%E8%A3%85%E4%BB%99%E4%BE%A0--------.html",
    "现代都市": "/show/duanju---%E7%8E%B0%E4%BB%A3%E9%83%BD%E5%B8%82--------.html",
    "反转": "/show/duanju---%E5%8F%8D%E8%BD%AC--------.html",
    "爽文": "/show/duanju---%E7%88%BD%E6%96%87--------.html",
    "短剧": "/show/duanju---%E7%9F%AD%E5%89%A7--------.html",
}

# 通过环境变量控制，GitHub Actions 建议设置小一些避免超时
MAX_PER_CATEGORY = int(os.getenv("MAX_PER_CATEGORY", "20"))
DELAY = float(os.getenv("DELAY", "3.0"))
RETRIES = 3
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============== HTTP 请求 ==============
def fetch(url, retries=RETRIES, impersonate="chrome110"):
    for attempt in range(1, retries + 1):
        try:
            kwargs = {"headers": HEADERS, "timeout": 30, "allow_redirects": True}
            if HTTP_BACKEND == "curl_cffi":
                kwargs["impersonate"] = impersonate
            resp = requests.get(url, **kwargs)
            resp.encoding = "utf-8"
            text = resp.text
            print(f"    [HTTP] {resp.status_code}, 长度 {len(text)}")
            
            if resp.status_code == 200:
                if any(k in text for k in ["Checking your browser", "cf-browser-verification", "cf-challenge-running"]):
                    print("    [!] Cloudflare 拦截")
                    return None
                return text
            else:
                print(f"    [!] HTTP 错误: {resp.status_code}")
        except Exception as e:
            print(f"    [!] 请求异常 ({attempt}/{retries}): {e}")
            time.sleep(2 * attempt)
    return None

# ============== 解析函数（保持原逻辑）=============
def parse_list_page(html):
    soup = BeautifulSoup(html, "html.parser")
    dramas = []
    articles = soup.find_all("article", class_="post-grid")
    print(f"    [解析] 找到 {len(articles)} 个 article")
    for article in articles:
        a_tag = article.find("a", href=re.compile(r"/vod/\d+\.html"))
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        title = a_tag.get("title", "").strip()
        img = a_tag.find("img")
        cover = ""
        if img:
            cover = img.get("data-src", "") or img.get("src", "")
            if cover.startswith("data:image"):
                cover = ""
        if href and title:
            dramas.append({"title": title, "vod_url": href, "cover": cover})
    print(f"    [解析] 提取 {len(dramas)} 个短剧")
    return dramas

def get_category_page_url(category_path, page):
    base = category_path[:-5] if category_path.endswith(".html") else category_path
    if page == 1:
        return f"{base}.html"
    else:
        return f"{base[:-8]}-----{page}---.html"

def get_category_dramas(category_path, max_count=100):
    all_dramas = []
    page = 1
    seen_urls = set()
    while len(all_dramas) < max_count:
        page_url = get_category_page_url(category_path, page)
        full_url = urljoin(BASE_URL, page_url)
        print(f"[*] 第{page}页: {full_url}")
        html = fetch(full_url)
        if not html:
            break
        dramas = parse_list_page(html)
        if not dramas:
            break
        for d in dramas:
            if d["vod_url"] not in seen_urls:
                seen_urls.add(d["vod_url"])
                all_dramas.append(d)
                if len(all_dramas) >= max_count:
                    break
        print(f"[*] 已收集: {len(all_dramas)}/{max_count}")
        page += 1
        time.sleep(DELAY)
    return all_dramas[:max_count]

def parse_detail_page(html):
    soup = BeautifulSoup(html, "html.parser")
    detail = {
        "title": "", "category": "", "director": "", "actor": "",
        "area": "", "year": "", "update_time": "", "language": "",
        "intro": "", "play_links": [], "cover": ""
    }
    h1 = soup.find("h1", class_="entry-title")
    if h1:
        for span in h1.find_all("span"):
            span.decompose()
        detail["title"] = h1.get_text(strip=True)
    
    info_container = None
    for tag, cls in [("div", "info-box"), ("ul", "pricing-options"), ("ul", "list-box")]:
        info_container = soup.find(tag, class_=cls)
        if info_container:
            break
    
    if info_container:
        for li in info_container.find_all("li"):
            text = li.get_text(strip=True)
            if text.startswith("分类：") or text.startswith("分类:"):
                detail["category"] = " ".join([a.get_text(strip=True) for a in li.find_all("a")])
            elif text.startswith("导演：") or text.startswith("导演:"):
                detail["director"] = text.replace("导演：", "").replace("导演:", "").strip()
            elif text.startswith("主演：") or text.startswith("演员：") or text.startswith("主演:"):
                detail["actor"] = text.replace("主演：", "").replace("演员：", "").replace("主演:", "").strip()
            elif text.startswith("地区：") or text.startswith("地区:"):
                detail["area"] = text.replace("地区：", "").replace("地区:", "").strip()
            elif text.startswith("年份：") or text.startswith("年份:"):
                detail["year"] = text.replace("年份：", "").replace("年份:", "").strip()
            elif text.startswith("更新：") or text.startswith("更新:"):
                detail["update_time"] = text.replace("更新：", "").replace("更新:", "").strip()
            elif text.startswith("语言：") or text.startswith("语言:"):
                detail["language"] = text.replace("语言：", "").replace("语言:", "").strip()
            elif text.startswith("剧情介绍：") or text.startswith("剧情:"):
                p = li.find("p")
                detail["intro"] = p.get_text(strip=True) if p else text.replace("剧情介绍：", "").replace("剧情:", "").strip()
    
    hero = soup.find("div", class_="hero")
    if hero:
        img = hero.find("img")
        if img:
            detail["cover"] = img.get("data-src", "") or img.get("src", "")
    
    tab_content = soup.find("div", class_="tab-content")
    if tab_content:
        first_tab = tab_content.find("div", class_="tab-pane")
        if first_tab:
            for link in first_tab.find_all("a", href=re.compile(r"/play/\d+-\d+-\d+\.html")):
                detail["play_links"].append({
                    "episode": link.get_text(strip=True),
                    "url": link.get("href", "")
                })
    
    if not detail["intro"]:
        modal_body = soup.find("div", class_="modal-body")
        if modal_body:
            detail["intro"] = modal_body.get_text(strip=True)
    return detail

def get_m3u8_from_play_page(html):
    match = re.search(r'var\s+player_aaaa\s*=\s*(\{.*?\});', html, re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            data = json.loads(json_str)
            url = data.get("url", "")
            if url and ".m3u8" in url:
                return url
        except json.JSONDecodeError:
            url_match = re.search(r'"url":"(https?:(?:\\/|/)\S+?\.m3u8)"', json_str)
            if url_match:
                return url_match.group(1).replace("\\/", "/")
    m3u8_match = re.search(r"(https?://[^\s\"'<>]+?\.m3u8)", html)
    if m3u8_match:
        return m3u8_match.group(1)
    return None

def scrape_drama(vod_url):
    detail_url = urljoin(BASE_URL, vod_url)
    print(f"  [*] 详情页: {detail_url}")
    html = fetch(detail_url)
    if not html:
        return None
    detail = parse_detail_page(html)
    detail["vod_url"] = detail_url
    
    m3u8_url = None
    if detail["play_links"]:
        first_play = detail["play_links"][0]["url"]
        play_url = urljoin(BASE_URL, first_play)
        print(f"  [*] 播放页: {play_url}")
        play_html = fetch(play_url)
        if play_html:
            m3u8_url = get_m3u8_from_play_page(play_html)
            print(f"  [+] m3u8: {m3u8_url}" if m3u8_url else "  [!] 未找到m3u8")
        time.sleep(DELAY)
    else:
        print("  [!] 无播放链接")
    
    detail["m3u8_url"] = m3u8_url
    return detail

# ============== 主流程 ==============
def main():
    print("=" * 60)
    print(f"GitHub Actions 自动抓取 | {datetime.now().isoformat()}")
    print(f"HTTP后端: {HTTP_BACKEND} | 每类最大: {MAX_PER_CATEGORY}")
    print("=" * 60)
    
    all_results = []
    for cat_name, cat_path in CATEGORIES.items():
        print(f"\n[+] 分类: {cat_name}")
        dramas = get_category_dramas(cat_path, MAX_PER_CATEGORY)
        print(f"[*] 获取到 {len(dramas)} 个短剧")
        if not dramas:
            continue
        
        for idx, drama in enumerate(dramas, 1):
            print(f"\n  [{idx}/{len(dramas)}] {drama['title']}")
            result = scrape_drama(drama["vod_url"])
            if result:
                result["category"] = cat_name
                result["list_cover"] = drama.get("cover", "")
                all_results.append(result)
            else:
                print("  [!] 抓取失败")
            time.sleep(DELAY)
        print(f"[*] 当前总计: {len(all_results)}")
    
    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(OUTPUT_DIR, f"duanju2_data_{timestamp}.json")
    csv_path = os.path.join(OUTPUT_DIR, f"duanju2_data_{timestamp}.csv")
    latest_json = os.path.join(OUTPUT_DIR, "duanju2_data_latest.json")
    latest_csv = os.path.join(OUTPUT_DIR, "duanju2_data_latest.csv")
    
    if all_results:
        # 带时间戳版本
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["分类", "标题", "导演", "主演", "地区", "年份", "语言", "更新时间", "m3u8地址", "详情页URL", "封面图", "简介"])
            for r in all_results:
                writer.writerow([
                    r.get("category", ""), r.get("title", ""), r.get("director", ""),
                    r.get("actor", ""), r.get("area", ""), r.get("year", ""),
                    r.get("language", ""), r.get("update_time", ""), r.get("m3u8_url", ""),
                    r.get("vod_url", ""), r.get("list_cover", ""), r.get("intro", "")
                ])
        
        # 最新版本（覆盖）
        import shutil
        shutil.copy(json_path, latest_json)
        shutil.copy(csv_path, latest_csv)
        
        success = sum(1 for r in all_results if r.get("m3u8_url"))
        print(f"\n[+] 成功抓取 {len(all_results)} 个，{success} 个含m3u8")
        print(f"[+] JSON: {json_path}")
        print(f"[+] CSV: {csv_path}")
    else:
        print("\n[!] 未抓取到任何数据")
        # 创建空文件防止 Actions 报错
        open(latest_json, "w").close()
        open(latest_csv, "w").close()

if __name__ == "__main__":
    main()
