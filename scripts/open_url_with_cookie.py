#!/usr/bin/env python3
"""
Playwright 脚本 - 打开指定 URL 并携带 cookie

使用方法:
  python scripts/open_url_with_cookie.py <URL>
  python scripts/open_url_with_cookie.py <URL> --cookie "name=value; domain=.example.com"
  python scripts/open_url_with_cookie.py <URL> --storage-state data/storage_states/saved.json
  python scripts/open_url_with_cookie.py <URL> --headless
  python scripts/open_url_with_cookie.py <URL> --save-cookies my_cookies.json
"""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def parse_cookie_string(cookie_str: str, default_domain: str = None) -> dict:
    """解析 cookie 字符串，支持格式: name=value; domain=.example.com; path=/; secure; httponly"""
    parts = [p.strip() for p in cookie_str.split(";")]
    cookie = {}

    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            key = key.strip().lower()
            value = value.strip()

            if key in ["domain", "path", "samesite"]:
                cookie[key] = value
            elif key in ["secure", "httponly"]:
                cookie[key] = value.lower() in ["true", "1", "yes"]
            else:
                cookie["name"] = key
                cookie["value"] = value
        elif part.lower() in ["secure", "httponly"]:
            cookie[part.lower()] = True

    if default_domain and "domain" not in cookie:
        cookie["domain"] = default_domain

    if "path" not in cookie:
        cookie["path"] = "/"

    return cookie


def main():
    parser = argparse.ArgumentParser(description="Playwright 打开 URL 并携带 cookie")
    parser.add_argument("url", help="要打开的 URL")
    parser.add_argument("--cookie", "-c", action="append", help="设置 cookie (格式: name=value; domain=.example.com)")
    parser.add_argument("--storage-state", "-s", help="从 storage state 文件加载 cookies")
    parser.add_argument("--save-cookies", help="将 cookies 保存到文件")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器）")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"], help="浏览器类型")
    parser.add_argument("--timeout", type=int, default=30000, help="页面加载超时时间 (ms)")
    parser.add_argument("--screenshot", help="截图保存路径")
    parser.add_argument("--keep-open", action="store_true", help="保持浏览器打开（仅非无头模式）")

    args = parser.parse_args()

    parsed_url = urlparse(args.url)
    default_domain = parsed_url.hostname

    with sync_playwright() as p:
        # 启动浏览器
        browser_type = getattr(p, args.browser)
        browser = browser_type.launch(headless=args.headless)

        # 创建上下文（浏览器会话）
        context = browser.new_context()

        # 从 storage state 加载 cookies
        if args.storage_state and Path(args.storage_state).exists():
            print(f"加载 storage state: {args.storage_state}")
            context = browser.new_context(storage_state=args.storage_state)
        else:
            context = browser.new_context()

        # 添加自定义 cookies
        if args.cookie:
            cookies_to_add = []
            for c in args.cookie:
                cookie = parse_cookie_string(c, default_domain)
                if "name" in cookie and "value" in cookie:
                    cookies_to_add.append(cookie)
                    print(f"添加 cookie: {cookie['name']}={cookie['value'][:20]}... (domain={cookie.get('domain')})")

            if cookies_to_add:
                context.add_cookies(cookies_to_add)

        # 创建页面并导航
        page = context.new_page()

        print(f"正在打开: {args.url}")
        response = page.goto(args.url, timeout=args.timeout)

        if response:
            print(f"页面加载完成 - 状态码: {response.status}")
            print(f"页面标题: {page.title()}")
            print(f"当前 URL: {page.url}")
        else:
            print("页面加载失败")

        # 截图
        if args.screenshot:
            page.screenshot(path=args.screenshot, full_page=True)
            print(f"截图已保存: {args.screenshot}")

        # 保存 cookies
        if args.save_cookies:
            cookies = context.cookies()
            with open(args.save_cookies, "w", encoding="utf-8") as f:
                json.dump({"cookies": cookies}, f, ensure_ascii=False, indent=2)
            print(f"已保存 {len(cookies)} 个 cookies 到: {args.save_cookies}")

        # 打印当前 cookies
        current_cookies = context.cookies()
        print(f"\n当前共有 {len(current_cookies)} 个 cookies:")
        for ck in current_cookies:
            print(f"  - {ck['name']} = {ck['value'][:30]}... (domain: {ck['domain']})")

        # 保持浏览器打开
        if args.keep_open and not args.headless:
            print("\n按 Ctrl+C 退出...")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        browser.close()
        print("\n完成")


if __name__ == "__main__":
    main()
