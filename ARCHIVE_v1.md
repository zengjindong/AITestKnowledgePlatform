# v1.0 Archive — 2026-06-18

这是项目第一个稳定版本的存档。本次 commit 包含以下所有变更。

## 一、手动模式浏览器按钮

### 问题
手动模式（`/api/explorer/start`）下，浏览器打开后没有"发送给 Claude 分析"按钮。

### 解决
- 修复 Python `r"""..."""` 原始字符串中嵌入 `"""` 导致截断的 bug
- 把按钮注入逻辑改为 `context.add_init_script()` + 全局变量 `window.__FLASK_API_ENDPOINT__`
- 注入时机：必须在 `new_page()` **之前**调用 `add_init_script`
- 加 init script + 显式 evaluate 双重保险
- 监听 SPA 路由（pushState / replaceState / hashchange / popstate）以在导航后重新注入
- z-index 设为最大值 `2147483647` 保证在最上层
- emoji 改用纯文本"Claude 分析"避免编码问题

### 涉及文件
- `src/knowledge/explorer.py` — PlaywrightExplorer `_inject_analyze_button` 改造为 init_script

## 二、CORS 跨域支持

### 问题
按钮点击后 fetch `http://localhost:5000` 被浏览器跨域策略拦截。

### 解决
- Flask 添加 `after_request` 钩子，自动注入：
  - `Access-Control-Allow-Origin: *`
  - `Access-Control-Allow-Headers: Content-Type, Authorization`
  - `Access-Control-Allow-Methods: GET,PUT,POST,DELETE,OPTIONS`

### 涉及文件
- `web_app.py` — 新增 `@app.after_request` 全局 CORS 头

## 三、分析结果持久化

### 需求
每次分析结果保存到本地，可以在项目里查看历史数据。

### 解决
- 新增存储目录 `data/analysis_history/`
- 每条分析存为 `<uuid8>.json`，包含 id / type / url / summary / raw_data / stats / created_at
- 新增 API：
  - `GET  /api/analysis/history?limit=50` — 列出历史
  - `GET  /api/analysis/<id>` — 详情
  - `DELETE /api/analysis/<id>` — 删除
- `summarize_exploration` 端点改造：manual 与 graph 两种模式都自动保存

### 涉及文件
- `web_app.py` — 新增 `_save_analysis_result` / `_list_analysis_history` / `_get_analysis_detail` / `_delete_analysis` 工具函数 + 三个新端点

## 四、前端历史查看按钮

### 解决
在「探索」卡片中添加两个按钮：
- **📚 分析历史** — `showAnalysisHistory()`：列出所有分析
- **📋 分析详情** — `promptAnalysisDetail()`：输入 ID 后查详情

详情页含：URL、时间、统计、完整 Claude 总结、删除按钮、返回列表按钮。

### 涉及文件
- `templates/index.html` — 按钮 + `showAnalysisHistory` / `promptAnalysisDetail` / `viewAnalysisDetail` / `deleteAnalysis` 四个 JS 函数

## 五、前端源码知识库（FE KB 浏览器）

### 解决
新增「📂 前端源码知识库」卡片，支持：
- 按项目 / 类型 / 关键字筛选 1292 个组件
- 每行展示组件名、类型徽章、文件路径、props/imports/api 计数
- 点击查看详情：props/imports/api_calls/exports 完整列表 + 深色源码预览（前 200 行）
- 页面加载时自动初始化

### 涉及文件
- `web_app.py` — 新增三个端点：
  - `GET /api/sourcecode/list` — 列表
  - `GET /api/sourcecode/detail?project=&name=` — 详情 + 源码
  - `GET /api/sourcecode/file?path=&max_lines=` — 任意源文件读取（仅 KB 注册过的）
- `templates/index.html` — 卡片 UI + `loadSourceCodeList` / `loadSourceCodeDetail` / `initSourceCodeBrowser` / `resetSourceCodeFilter` 函数

## 六、后端源码知识库（BE KB 浏览器）

### 解决
新增「🛠️ 后端源码知识库」卡片，4 个标签切换：
- **⚙️ API** (1448) — 彩色 HTTP 方法徽章（GET 绿 / POST 蓝 / DELETE 红 / 其他橙），支持按方法过滤
- **🧩 Service** (1114) — 方法数 / 依赖数
- **📦 Entity** (503) — 表名 / 字段数
- **🗄️ Repository** (120) — 实体类型 / 表名

详情页含：所有字段展示（数组/对象自动格式化）+ 源码预览。

### 涉及文件
- `web_app.py` — 新增：
  - `GET /api/sourcecode-be/list?category=&query=&method=&limit=` — 列表
  - `GET /api/sourcecode-be/detail?category=&id=` — 详情
  - `_be_item_summary` 辅助函数
- `templates/index.html` — 卡片 + 标签切换 + `setBECategory` / `loadBELibraryList` / `loadBEDetail` / `resetBEFilter` 函数

## 七、需求上下文自动匹配 + 人工文字补充

### 需求
不再人工点选 KB 条目，让 AI 根据需求自动从知识库挑选相关组件/API；同时支持用户用纯文字补充业务规则。

### 解决
- `web_app.py /api/requirement` 改造：
  - 新增 `extra_notes` 字段（人工文字补充，写入证据链）
  - 新增 `auto_context` 字段（默认 true）
  - 内部 `_auto_match_kb_context()`：
    - 中英文 token 提取（`[A-Za-z][A-Za-z0-9_/-]{2,}` + `[一-鿿]{2,}`）
    - 对 1292 FE 组件 + 1448 API + 1114 Service + 503 Entity 打分
    - 返回 top 10 FE / top 10 API / top 5 Service / top 5 Entity
    - 自动 + 手工去重合并
- 新增 `POST /api/requirement/auto-context` 预览接口
- 前端改造：
  - 卡片标题改为「🧠 补充说明 / 知识库上下文（自动）」
  - 顶部加「🤖 自动从 FE/BE 知识库匹配上下文」复选框（默认勾选）
  - 「👀 预览匹配结果」按钮
  - 「📝 人工补充说明」文本框（自然语言）
  - 旧的「+ 加入」搜索功能折叠到「🔧 高级」面板里
  - `submitRequirement` 提交新字段

### 涉及文件
- `web_app.py` — `process_requirement` 改造 + `_auto_match_kb_context` 新增 + `preview_auto_context` 新增
- `templates/index.html` — 卡片改造 + `previewAutoContext` 新增

## 八、其它
- 旧的 `_inject_analyze_button` 方法已删除（被 init_script 替代）
- 修复了 2 个 Python 旧进程残留导致新代码不生效的问题

## 回滚方法

```bash
# 查看本次存档的 tag
git tag -l
# 看到 v1.0-archive

# 完全回滚到本次存档
git checkout v1.0-archive -- .

# 仅回滚某个文件
git checkout v1.0-archive -- web_app.py
git checkout v1.0-archive -- templates/index.html
git checkout v1.0-archive -- src/knowledge/explorer.py
```

## 涉及的所有文件清单

```
.gitignore                       (新增)
ARCHIVE_v1.md                    (新增, 本文件)
web_app.py                       (大改: CORS + 分析历史 + FE/BE KB API + 自动匹配)
templates/index.html             (大改: 历史按钮 + FE/BE 浏览器 + 自动匹配 UI)
src/knowledge/explorer.py        (改: 按钮注入改用 init_script)
```
