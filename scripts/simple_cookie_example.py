#!/usr/bin/env python3
"""
最简单的 Playwright cookie 示例

演示最常用的几种 cookie 设置方式
"""

from playwright.sync_api import sync_playwright

# 方式 1: 直接设置单个 cookie
def example_set_single_cookie():
    print("=== 方式 1: 直接设置单个 cookie ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless=False 显示浏览器
        context = browser.new_context()

        # 添加 cookie (必须先指定 domain)
        context.add_cookies([{
            "name": "session_id",
            "value": "abc123xyz789",
            "domain": ".example.com",    # 必须指定
            "path": "/",                 # 必须指定
        }])

        page = context.new_page()
        page.goto("https://example.com")

        # 读取当前 cookies
        cookies = context.cookies()
        print(f"已设置 {len(cookies)} 个 cookies:")
        for c in cookies:
            print(f"  {c['name']} = {c['value']}")

        browser.close()


# 方式 2: 保存完整的登录状态 (storageState)
def example_save_storage_state():
    print("\n=== 方式 2: 保存完整的登录状态 ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # 先访问网站登录 (这里用 example.com 演示)
        page.goto("https://example.com")

        # 你可以在这里手动登录，或者用脚本自动登录
        # page.fill("#username", "your-username")
        # page.fill("#password", "your-password")
        # page.click("#submit")

        print("登录完成后，保存 storage state...")

        # 保存完整的登录状态 (cookies + localStorage + sessionStorage)
        context.storage_state(path="my_login_state.json")
        print("已保存登录状态到 my_login_state.json")

        browser.close()


# 方式 3: 加载已保存的登录状态
def example_load_storage_state():
    print("\n=== 方式 3: 加载已保存的登录状态 ===")
    import os

    if not os.path.exists("my_login_state.json"):
        print("请先运行 example_save_storage_state() 保存登录状态")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        # 直接加载之前保存的登录状态
        context = browser.new_context(storage_state="my_login_state.json")

        page = context.new_page()
        page.goto("https://example.com")

        print("已加载登录状态，你应该是已登录的！")

        cookies = context.cookies()
        print(f"加载了 {len(cookies)} 个 cookies")

        browser.close()


# 方式 4: 设置多个 cookies
def example_set_multiple_cookies():
    print("\n=== 方式 4: 设置多个 cookies ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        cookies = [
            {"name": "token", "value": "jwt-token-here", "domain": ".example.com", "path": "/"},
            {"name": "user_id", "value": "12345", "domain": ".example.com", "path": "/"},
            {"name": "theme", "value": "dark", "domain": ".example.com", "path": "/"},
        ]

        context.add_cookies(cookies)
        print(f"已设置 {len(cookies)} 个 cookies")

        page = context.new_page()
        page.goto("https://example.com")

        browser.close()


if __name__ == "__main__":
    # 运行所有示例
    example_set_single_cookie()
    example_save_storage_state()
    example_load_storage_state()
    example_set_multiple_cookies()
