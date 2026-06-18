#!/usr/bin/env python3
"""登录状态测试脚本 - Token 认证方式"""

# 配置区
TEST_URL = "https://dbq.asptest.yiye.ai/workbench/"

# Cookie 配置（从浏览器开发者工具 F12 → Application → Cookies 复制）
COOKIES = [
    {"name": "Admin-Token", "value": "Bearer eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ5aXllX2FnZW50X3Rlc3QiLCJ1aWQiOjUzLCJhZ2VudElkIjoiZGJxIiwiYWNjZXNzX3Rva2VuIjoiNjc2ODBhMjRlMTFiNGNlMmI1MzAwZTRkYWExOWVlM2IiLCJ1c2VyX3Rva2VuX3R5cGUiOiJDT01NT05fUk9MRSIsInN5c3RlbV90eXBlIjoiYWdlbnRfcHJpdmF0ZSIsImV4cCI6MTc4MTc1MTEwNH0.0C7ztFvvqpnbjG91AQD-R4HaxY5fqIpfF__mtXtTI0D5m5SxvLSKt6_GiufXAfff4GNhMZ_V2784Qm8xgCf-qg", "domain": "dbq.asptest.yiye.ai", "path": "/"},
]

SHOW_BROWSER = True

import sys
from playwright.sync_api import sync_playwright


def test_cookie_auth():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not SHOW_BROWSER)
        context = browser.new_context()
        context.add_cookies(COOKIES)

        page = context.new_page()
        print(f"正在访问: {TEST_URL}")
        page.goto(TEST_URL, timeout=30000)

        print(f"页面标题: {page.title()}")
        print(f"当前 URL: {page.url}")

        if "login" in page.url.lower() or "signin" in page.url.lower():
            print("✗ 跳转到登录页，Cookie 无效")
            return False
        else:
            print("✓ Cookie 认证成功！")
            if SHOW_BROWSER:
                input("\n按回车键关闭浏览器...")
            return True


if __name__ == "__main__":
    result = test_cookie_auth()
    print("\n" + ("✓ 认证成功" if result else "✗ 认证失败"))
    sys.exit(0 if result else 1)