#!/usr/bin/env node
/**
 * SystemExplorer - Puppeteer based recursive Web system function explorer.
 *
 * Implements:
 * - BFS discovery queue over URL + DOM fingerprints
 * - session persistence (cookies + localStorage) to session.json
 * - auth detection (401/403 and login redirects)
 * - DOM function extraction (<a>, <button>, <form>, semantic clickables)
 * - XHR/fetch API capture and function association
 * - crash-safe append-only JSONL output and Markdown summary
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const readline = require('readline');
const puppeteer = require('puppeteer');

class AuthRequiredError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = 'AUTH_REQUIRED';
    this.code = 'AUTH_REQUIRED';
    this.details = details;
  }
}

class NameInferenceError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = 'NAME_INFERENCE_FAILED';
    this.code = 'NAME_INFERENCE_FAILED';
    this.details = details;
  }
}

/**
 * @typedef {Object} InferredName
 * @property {string} name       Chinese short label, <= 12 chars
 * @property {string} category   Chinese category, e.g. 项目查询/系统设置/用户管理
 */

class ClaudeCliNameInference {
  constructor(options = {}) {
    this.cli = options.cli || 'claude';
    this.model = options.model || null;            // e.g. 'sonnet' if user wants
    this.timeoutMs = options.timeoutMs || 90000;
    this.maxRetries = options.maxRetries ?? 1;
  }

  /**
   * Batch a page's elements through `claude -p`.
   * @param {{url:string,title:string,headings:string[]}} pageContext
   * @param {Array<{xpath:string,type:string,text:string,id?:string,href?:string}>} elements
   * @returns {Promise<InferredName[]>}  one entry per input element, in order
   */
  async inferBatch(pageContext, elements) {
    if (!elements.length) return [];
    const prompt = this.buildPrompt(pageContext, elements);
    const raw = await this.runCli(prompt);
    const parsed = this.extractJson(raw);
    if (!Array.isArray(parsed) || parsed.length !== elements.length) {
      throw new NameInferenceError(
        'claude CLI did not return an array matching element count',
        { expected: elements.length, got: Array.isArray(parsed) ? parsed.length : 'non-array', raw }
      );
    }
    return parsed.map((entry, i) => ({
      name: String(entry?.name || '').trim() || elements[i].text || '未命名功能',
      category: String(entry?.category || '').trim() || '未分类',
    }));
  }

  buildPrompt(pageContext, elements) {
    const ctx = {
      url: pageContext.url,
      title: pageContext.title,
      headings: pageContext.headings || [],
    };
    const items = elements.map((el, i) => ({
      i,
      type: el.type,
      text: el.text || '',
      id: el.id || '',
      href: el.href || '',
      xpath: el.xpath,
    }));
    return [
      '你是一名资深 Web 自动化测试工程师，负责根据 Web 系统的页面上下文为每个可交互功能点推断中文名称与分类。',
      '请阅读下面的页面上下文与功能点候选列表，**只**输出一行严格 JSON，不要任何解释或前后缀。',
      'JSON 必须是长度为 ' + items.length + ' 的数组，元素顺序与候选一致，每个对象形如 {"name":"...","category":"..."}。',
      '- name：<= 12 字中文，描述该功能是做什么的（如"查询项目"、"新增用户"、"导出报表"）。',
      '- category：简短分类，如 项目查询/系统设置/用户管理/数据统计/导航/帮助/其它。',
      '',
      '页面上下文：',
      JSON.stringify(ctx, null, 2),
      '',
      '功能点候选（顺序对齐）：',
      JSON.stringify(items, null, 2),
    ].join('\n');
  }

  async runCli(prompt) {
    // Pass the long prompt via stdin (Claude Code reads its prompt from the
    // positional arg, but Windows shell escaping mangles long args with
    // spaces and CJK characters). Stdin keeps the prompt bytes intact.
    const args = ['-p', '--bare', '--output-format', 'text'];
    if (this.model) {
      args.push('--model', this.model);
    }
    args.push('-');  // tell claude to read the prompt from stdin

    let lastErr;
    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      try {
        const { stdout, stderr } = await this.exec([this.cli, ...args], prompt);
        if (stderr && stderr.trim()) {
          process.stderr.write(`[claude-cli] ${stderr.trim()}\n`);
        }
        const text = (stdout || '').trim();
        if (!text) {
          lastErr = new Error('claude CLI returned empty stdout');
        } else {
          return text;
        }
      } catch (error) {
        lastErr = error;
      }
    }
    throw new NameInferenceError('claude CLI failed after retries', { cause: lastErr && lastErr.message });
  }

  exec(cmd, stdinPayload) {
    return new Promise((resolve, reject) => {
      const child = require('child_process').spawn(cmd[0], cmd.slice(1), {
        stdio: [stdinPayload ? 'pipe' : 'ignore', 'pipe', 'pipe'],
        windowsHide: true,
        // On Windows, `.cmd`/`.bat` shims and npm bin shims live in places
        // node's spawn won't resolve without shell=true.
        shell: process.platform === 'win32',
      });
      let stdout = '';
      let stderr = '';
      const timer = setTimeout(() => {
        child.kill('SIGKILL');
        reject(new Error(`claude CLI timeout after ${this.timeoutMs}ms`));
      }, this.timeoutMs);
      child.stdout.on('data', (chunk) => { stdout += chunk.toString('utf8'); });
      child.stderr.on('data', (chunk) => { stderr += chunk.toString('utf8'); });
      child.on('error', (err) => {
        clearTimeout(timer);
        reject(err);
      });
      if (stdinPayload) {
        child.stdin.setEncoding('utf8');
        child.stdin.end(stdinPayload);
      }
      child.on('close', (code) => {
        clearTimeout(timer);
        if (code === 0) {
          resolve({ stdout, stderr });
        } else {
          reject(new Error(`claude CLI exited with code ${code}: ${stderr.trim().slice(0, 200)}`));
        }
      });
    });
  }

  extractJson(raw) {
    // The CLI may return a JSON array; tolerate surrounding whitespace,
    // a fenced code block, or trailing commentary.
    const fenced = raw.match(/```(?:json)?\s*([\s\S]+?)\s*```/i);
    const candidate = fenced ? fenced[1] : raw;
    const firstBracket = candidate.search(/[\[]/);
    if (firstBracket === -1) {
      throw new NameInferenceError('claude CLI output contained no JSON array', { raw });
    }
    const slice = candidate.slice(firstBracket);
    try {
      return JSON.parse(slice);
    } catch (_) {
      // Try to repair by trimming at the last balanced ']'
      const last = slice.lastIndexOf(']');
      if (last > 0) {
        try {
          return JSON.parse(slice.slice(0, last + 1));
        } catch (e) {
          throw new NameInferenceError('failed to parse JSON array from claude CLI', { raw, cause: e.message });
        }
      }
      throw new NameInferenceError('failed to parse JSON array from claude CLI', { raw });
    }
  }
}

class SystemExplorer {
  constructor(options = {}) {
    this.startUrl = options.startUrl || 'https://dbq.asptest.yiye.ai/pmp/project-profile/?type=pmp&advertiserGroupId=113';
    this.maxDepth = Number(options.maxDepth ?? 3);
    this.maxPages = Number(options.maxPages ?? 100);
    this.headless = options.headless !== false;
    this.executablePath = options.executablePath || process.env.PUPPETEER_EXECUTABLE_PATH || null;
    this.outputDir = path.resolve(options.outputDir || path.join(process.cwd(), 'data', 'explorer'));
    this.sessionPath = path.resolve(options.sessionPath || path.join(this.outputDir, 'session.json'));
    this.jsonlPath = path.resolve(options.jsonlPath || path.join(this.outputDir, 'functions_map.jsonl'));
    this.mdPath = path.resolve(options.mdPath || path.join(this.outputDir, 'SystemFunctions.md'));
    this.safeMode = options.safeMode !== false;
    this.nameInference = options.nameInference || new ClaudeCliNameInference(options.nameInferenceOptions || {});

    this.discoveryQueue = [];
    this.visitedFingerprints = new Set();
    this.functionFingerprints = new Set();
    this.functions = [];
    this.currentFunction = null;
    this.browser = null;
    this.page = null;
    this.stats = {
      pagesVisited: 0,
      statesVisited: 0,
      statesDiscovered: 0,
      actionsDiscovered: 0,
      actionsExecuted: 0,
      actionsSkipped: 0,
      duplicateStates: 0,
      apiCallsAttributed: 0,
      functionsDiscovered: 0,
      apisDiscovered: 0,
      authRequired: false,
      errors: [],
    };

    fs.mkdirSync(this.outputDir, { recursive: true });
  }

  async explore() {
    const launchOptions = {
      headless: this.headless,
      defaultViewport: { width: 1440, height: 1000 },
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    };
    if (this.executablePath) launchOptions.executablePath = this.executablePath;
    this.browser = await puppeteer.launch(launchOptions);

    this.page = await this.browser.newPage();
    await this.restoreSession(this.page);
    await this.installNetworkHooks(this.page);
    await this.applyAuthCookieSidecar(this.page);

    this.discoveryQueue.push({ url: this.startUrl, depth: 0, parent: null });

    try {
      while (this.discoveryQueue.length && this.stats.pagesVisited < this.maxPages) {
        const task = this.discoveryQueue.shift();
        if (task.depth > this.maxDepth) continue;
        await this.visitTask(task);
      }
      await this.generateMarkdown();
      return this.toResult();
    } finally {
      await this.saveSession(this.page).catch(() => {});
      if (this.browser) await this.browser.close().catch(() => {});
    }
  }

  async visitTask(task) {
    let response;
    try {
      response = await this.page.goto(task.url, { waitUntil: 'networkidle2', timeout: 45000 });
      await this.assertAuthenticated(response, this.page.url(), task.url);
      await this.waitForStableDom();
    } catch (error) {
      if (error.code === 'AUTH_REQUIRED') throw error;
      this.stats.errors.push({ url: task.url, error: error.message });
      return;
    }

    const urlPattern = this.normalizeUrl(this.page.url());
    const domHash = await this.computeDomHash(this.page);
    const pageFingerprint = `${urlPattern}#${domHash}`;
    if (this.visitedFingerprints.has(pageFingerprint)) {
      this.stats.duplicateStates += 1;
      return;
    }
    this.visitedFingerprints.add(pageFingerprint);
    this.stats.pagesVisited += 1;
    this.stats.statesVisited += 1;
    this.stats.statesDiscovered += 1;

    const context = await this.extractPageContext(this.page);
    const elements = await this.extractInteractiveElements(this.page);
    const forms = await this.extractForms(this.page);

    // Track actions discovered on this page (links + buttons + forms).
    this.stats.actionsDiscovered += elements.length + forms.length;

    // One CLI call per page: ask the local `claude` CLI to infer Chinese
    // names + categories for every candidate (links, buttons, forms).
    const candidates = [];
    elements.forEach((el) => candidates.push({
      source: 'element', xpath: el.xpath, type: el.type, text: el.text || '',
      id: el.id || '', href: el.href || '',
    }));
    forms.forEach((f) => candidates.push({
      source: 'form', xpath: f.xpath, type: 'form', text: f.text || '',
      id: f.id || '', href: f.action || '',
    }));

    let inferred = [];
    if (candidates.length) {
      try {
        inferred = await this.nameInference.inferBatch(context, candidates);
      } catch (error) {
        // Per requirement: must succeed or fail loudly.
        throw error;
      }
    }

    let cursor = 0;
    for (const element of elements) {
      const label = inferred[cursor] || { name: '', category: '' };
      cursor += 1;
      const functionPoint = this.createFunctionPoint(element, context, task, pageFingerprint);
      if (label.name) functionPoint.name = label.name;
      if (label.category) functionPoint.category = label.category;
      this.recordFunction(functionPoint);

      // Track executed vs skipped actions. Links are always treated as
      // 'discovered but not clicked' (we navigate to them as a new BFS
      // task, not as an in-page click). Buttons are either safe-to-
      // click (executed -> tryClickForApiAssociation) or skipped
      // (destructive / unsafe).
      if (element.type === 'button' && this.safeToClick(element)) {
        this.stats.actionsExecuted += 1;
      } else if (element.type === 'button') {
        this.stats.actionsSkipped += 1;
      }

      if (element.type === 'link' && element.href) {
        const nextUrl = new URL(element.href, this.page.url()).toString();
        if (this.isSameOrigin(nextUrl) && task.depth + 1 <= this.maxDepth) {
          this.discoveryQueue.push({ url: nextUrl, depth: task.depth + 1, parent: functionPoint.id });
        }
      }

      if (element.type === 'button' && this.safeToClick(element)) {
        await this.tryClickForApiAssociation(element, functionPoint);
      }
    }

    for (const form of forms) {
      const label = inferred[cursor] || { name: '', category: '' };
      cursor += 1;
      const point = this.createFunctionPoint(form, context, task, pageFingerprint);
      if (label.name) point.name = label.name;
      if (label.category) point.category = label.category;
      point.parameters = form.fields;
      this.recordFunction(point);
    }
  }

  async installNetworkHooks(page) {
    page.on('response', async (response) => {
      // Don't flag authRequired on every 401: many endpoints return 401
      // only for unauthenticated resource sub-requests. The real test
      // is whether the *top-level* navigation lands on a login path,
      // which we check separately in assertAuthenticated(). We still
      // record 401/403 for diagnostics but don't promote them to
        // authRequired.
      const status = response.status();
      if ((status === 401 || status === 403) && this.isLoginUrl(response.url())) {
        this.stats.authRequired = true;
      }
    });

    page.on('request', (request) => {
      const type = request.resourceType();
      if (type !== 'xhr' && type !== 'fetch') return;
      const url = request.url();
      if (!this.isSameOrigin(url)) return;
      const payloadSchema = this.payloadSchema(request.postData());
      const normalized = this.normalizeUrl(url);
      const apiFingerprint = this.fingerprint(`${request.method()} ${normalized} ${JSON.stringify(payloadSchema)}`);
      const api = {
        fingerprint: apiFingerprint,
        url,
        normalized_url: normalized,
        method: request.method(),
        payload_schema: payloadSchema,
        associated_function_id: this.currentFunction?.id || null,
        associated_function_name: this.currentFunction?.name || null,
      };

      if (this.currentFunction) {
        this.currentFunction.apis.push(api);
        this.stats.apiCallsAttributed += 1;
      }

      if (!this.functionFingerprints.has(apiFingerprint)) {
        this.functionFingerprints.add(apiFingerprint);
        this.stats.apisDiscovered += 1;
      }
    });
  }

  async assertAuthenticated(response, finalUrl, requestedUrl) {
    const status = response ? response.status() : null;
    if (status === 401 || status === 403 || this.isLoginUrl(finalUrl)) {
      this.stats.authRequired = true;
      throw new AuthRequiredError('AUTH_REQUIRED: login session is missing or expired', {
        requestedUrl,
        finalUrl,
        status,
      });
    }
  }

  async saveSession(page = this.page) {
    if (!page) return;
    const cookies = await page.cookies();
    const localStorage = await page.evaluate(() => {
      const values = {};
      for (let i = 0; i < window.localStorage.length; i += 1) {
        const key = window.localStorage.key(i);
        values[key] = window.localStorage.getItem(key);
      }
      return values;
    }).catch(() => ({}));

    fs.mkdirSync(path.dirname(this.sessionPath), { recursive: true });
    fs.writeFileSync(this.sessionPath, JSON.stringify({ cookies, localStorage }, null, 2), 'utf8');
  }

  async restoreSession(page = this.page) {
    if (!page || !fs.existsSync(this.sessionPath)) return false;
    const raw = fs.readFileSync(this.sessionPath, 'utf8');
    const session = JSON.parse(raw);
    if (Array.isArray(session.cookies) && session.cookies.length) {
      await page.setCookie(...session.cookies);
    }
    await page.evaluateOnNewDocument((savedLocalStorage) => {
      for (const [key, value] of Object.entries(savedLocalStorage || {})) {
        window.localStorage.setItem(key, value);
      }
    }, session.localStorage || {});
    return true;
  }

  async applyAuthCookieSidecar(page) {
    // The Yiye back end's JwtFilter only reads the `Authorization` header,
    // not cookies. The SPA stores the JWT inside an `Admin-Token` cookie
    // (whose value is often URL-encoded and prefixed with `Bearer `).
    // Read the sidecar that the Python login helper wrote, strip the
    // `Bearer ` prefix, and set it as a request-level header so the next
    // exploration run actually authenticates against the API.
    if (!page) return;
    const sidecar = this.sessionPath + '.auth.cookies.json';
    if (!fs.existsSync(sidecar)) return;
    let cookies = [];
    try {
      cookies = JSON.parse(fs.readFileSync(sidecar, 'utf-8'));
    } catch (e) {
      return;
    }
    if (!Array.isArray(cookies)) return;
    for (const c of cookies) {
      if (c && c.name === 'Admin-Token' && c.value) {
        let token = decodeURIComponent(String(c.value)).trim();
        if (token.toLowerCase().startsWith('bearer ')) {
          token = token.slice(7).trim();
        }
        if (token) {
          try {
            await page.setExtraHTTPHeaders({ Authorization: `Bearer ${token}` });
            console.log('[auth-sidecar] Applied Authorization header from Admin-Token cookie');
          } catch (e) {
            console.log(`[auth-sidecar] Failed to set Authorization header: ${e.message}`);
          }
        }
        break;
      }
    }
  }

  async promptLogin() {
    if (this.browser) await this.browser.close().catch(() => {});
    this.browser = await puppeteer.launch({
      headless: false,
      defaultViewport: null,
      args: ['--no-sandbox'],
      ...(this.executablePath ? { executablePath: this.executablePath } : {}),
    });
    this.page = await this.browser.newPage();
    await this.page.goto(this.startUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });

    await new Promise((resolve) => {
      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
      rl.question('请在打开的浏览器中完成登录，然后按 Enter 继续保存 session.json ... ', () => {
        rl.close();
        resolve();
      });
    });

    await this.saveSession(this.page);
    await this.browser.close();
  }

  async extractPageContext(page) {
    return page.evaluate(() => ({
      url: location.href,
      title: document.title,
      headings: Array.from(document.querySelectorAll('h1,h2,h3,[role="heading"]')).map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 10),
      bodyText: (document.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 500),
    }));
  }

  async extractInteractiveElements(page) {
    return page.evaluate(() => {
      const visible = (el) => {
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const xpathOf = (el) => {
        if (el.id) return `//*[@id="${el.id}"]`;
        const parts = [];
        while (el && el.nodeType === Node.ELEMENT_NODE) {
          let index = 1;
          let sib = el.previousElementSibling;
          while (sib) {
            if (sib.tagName === el.tagName) index += 1;
            sib = sib.previousElementSibling;
          }
          parts.unshift(`${el.tagName.toLowerCase()}[${index}]`);
          el = el.parentElement;
        }
        return '/' + parts.join('/');
      };
      const labelOf = (el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('id') || el.getAttribute('class') || '').trim().replace(/\s+/g, ' ').slice(0, 100);
      const nodes = Array.from(document.querySelectorAll('a[href], button, [role="button"], [onclick], [role="menuitem"], [role="tab"]'));
      return nodes.filter(visible).slice(0, 100).map((el, index) => ({
        type: el.tagName.toLowerCase() === 'a' ? 'link' : 'button',
        tag: el.tagName.toLowerCase(),
        text: labelOf(el),
        id: el.id || '',
        className: typeof el.className === 'string' ? el.className : '',
        href: el.getAttribute('href') || '',
        role: el.getAttribute('role') || '',
        xpath: xpathOf(el),
        index,
      }));
    });
  }

  async extractForms(page) {
    return page.evaluate(() => Array.from(document.querySelectorAll('form')).slice(0, 30).map((form, index) => {
      const fields = Array.from(form.querySelectorAll('input, textarea, select')).map(field => ({
        name: field.getAttribute('name') || field.getAttribute('id') || '',
        type: field.getAttribute('type') || field.tagName.toLowerCase(),
        required: field.hasAttribute('required'),
      }));
      return {
        type: 'form',
        text: form.getAttribute('name') || form.getAttribute('id') || `form_${index + 1}`,
        action: form.getAttribute('action') || location.href,
        method: (form.getAttribute('method') || 'GET').toUpperCase(),
        xpath: `//form[${index + 1}]`,
        fields,
      };
    }));
  }

  createFunctionPoint(element, context, task, pageFingerprint) {
    const normalizedUrl = this.normalizeUrl(element.href || element.action || context.url);
    const payloadSchema = element.fields || {};
    const fingerprint = this.fingerprint(`${element.type}:${element.xpath}:${normalizedUrl}:${JSON.stringify(payloadSchema)}`);
    return {
      id: fingerprint,
      page_path: this.normalizeUrl(context.url),
      depth: task.depth,
      parent: task.parent,
      type: element.type,
      name: element.text || '',
      category: '未分类',
      text: element.text || '',
      xpath: element.xpath,
      normalized_url: normalizedUrl,
      method: element.method || (element.type === 'form' ? 'GET' : 'UI'),
      payload_schema: payloadSchema,
      fingerprint,
      page_fingerprint: pageFingerprint,
      apis: [],
      discovered_at: new Date().toISOString(),
    };
  }

  async inferFunctionName(element, context) {
    if (this.nameInference) {
      return this.nameInference(element, context);
    }
    const text = (element.text || '').trim();
    if (text) return text;
    if (element.type === 'form') return `提交表单：${element.method || 'GET'} ${element.action || ''}`;
    if (element.href) return `打开页面：${element.href}`;
    const heading = context.headings?.[0] || context.title || '页面功能';
    return `${heading} - ${element.type}`;
  }

  recordFunction(point) {
    if (this.functionFingerprints.has(point.fingerprint)) return;
    this.functionFingerprints.add(point.fingerprint);
    this.functions.push(point);
    this.stats.functionsDiscovered += 1;
    fs.appendFileSync(this.jsonlPath, `${JSON.stringify(point)}\n`, 'utf8');
  }

  async tryClickForApiAssociation(element, functionPoint) {
    this.currentFunction = functionPoint;
    try {
      const loc = this.page.locator('xpath=' + element.xpath);
      const count = loc.count();
      if (count === 0) return;
      await loc.first().click({ delay: 30 });
      await this.page.waitForNetworkIdle({ idleTime: 500, timeout: 3000 }).catch(() => {});
    } catch (error) {
      this.stats.errors.push({ function: functionPoint.name, error: error.message });
    } finally {
      this.currentFunction = null;
    }
  }

  safeToClick(element) {
    if (!this.safeMode) return true;
    const text = `${element.text || ''} ${element.id || ''} ${element.className || ''}`.toLowerCase();
    return !/(delete|remove|save|submit|create|add|edit|update|publish|approve|reject|confirm|pay|refund|删除|移除|保存|提交|创建|新增|添加|编辑|更新|发布|审批|确认|支付|退款)/i.test(text);
  }

  async computeDomHash(page) {
    const signature = await page.evaluate(() => {
      const strip = (s) => (s || '').replace(/\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|\b\d{10,}\b/g, '{dynamic}').replace(/\s+/g, ' ').trim();
      const main = document.querySelector('main, #app, #root, .app, body');
      const clone = main.cloneNode(true);
      clone.querySelectorAll('script,style,iframe,canvas,svg,.ad,.ads,[class*=advert],[id*=advert]').forEach(el => el.remove());
      return strip(clone.innerText || clone.textContent || clone.outerHTML || '');
    }).catch(() => '');
    return this.fingerprint(signature.slice(0, 5000));
  }

  normalizeUrl(url) {
    try {
      const u = new URL(url, this.startUrl);
      const keptParams = [];
      for (const [key, value] of u.searchParams.entries()) {
        if (/^(t|time|timestamp|random|_)=?$/i.test(key)) continue;
        if (/^\d{8,}$/.test(value)) continue;
        keptParams.push([key, value]);
      }
      const normalizedPath = u.pathname
        .replace(/\/[0-9a-f]{8,}(?=\/|$)/gi, '/{id}')
        .replace(/\/\d+(?=\/|$)/g, '/{id}');
      const query = keptParams.sort(([a], [b]) => a.localeCompare(b)).map(([k]) => `${k}={value}`).join('&');
      return `${u.origin}${normalizedPath}${query ? '?' + query : ''}`;
    } catch (_) {
      return String(url || '');
    }
  }

  payloadSchema(postData) {
    if (!postData) return {};
    try {
      const parsed = JSON.parse(postData);
      return this.schemaOf(parsed);
    } catch (_) {
      return { raw: typeof postData };
    }
  }

  schemaOf(value) {
    if (Array.isArray(value)) return [value.length ? this.schemaOf(value[0]) : 'unknown'];
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, this.schemaOf(v)]));
    }
    return typeof value;
  }

  isSameOrigin(url) {
    try {
      return new URL(url, this.startUrl).origin === new URL(this.startUrl).origin;
    } catch (_) {
      return false;
    }
  }

  isLoginUrl(url) {
    try {
      return /\/(login|signin|sso|auth|oauth|saml)(\/|\?|#|$)/i.test(new URL(url, this.startUrl).pathname);
    } catch (_) {
      return false;
    }
  }

  fingerprint(input) {
    return crypto.createHash('sha1').update(String(input)).digest('hex');
  }

  async waitForStableDom() {
    await new Promise((r) => setTimeout(r, 300)).catch(() => {});
  }

  async generateMarkdown() {
    const lines = ['# System Functions', '', `Start URL: ${this.startUrl}`, '', '## Summary', '', `- Pages visited: ${this.stats.pagesVisited}`, `- Functions discovered: ${this.stats.functionsDiscovered}`, `- APIs discovered: ${this.stats.apisDiscovered}`, '', '## Functions', ''];
    for (const fn of this.functions) {
      lines.push(`### ${fn.name}`);
      lines.push('');
      lines.push(`- 分类: ${fn.category || '未分类'}`);
      lines.push(`- 页面路径: ${fn.page_path}`);
      lines.push(`- 类型: ${fn.type}`);
      lines.push(`- XPath: \`${fn.xpath || ''}\``);
      lines.push(`- 指纹: \`${fn.fingerprint}\``);
      if (fn.apis.length) {
        lines.push('- 对应 API 接口:');
        for (const api of fn.apis) {
          lines.push(`  - ${api.method} ${api.normalized_url}`);
          lines.push(`    - 参数结构: \`${JSON.stringify(api.payload_schema)}\``);
        }
      } else {
        lines.push('- 对应 API 接口: 无捕获');
      }
      if (fn.parameters && Object.keys(fn.parameters).length) {
        lines.push(`- 参数结构: \`${JSON.stringify(fn.parameters)}\``);
      }
      lines.push('');
    }
    fs.writeFileSync(this.mdPath, lines.join('\n'), 'utf8');
  }

  toResult() {
    return {
      status: 'success',
      stats: this.stats,
      output: {
        jsonl: this.jsonlPath,
        markdown: this.mdPath,
        session: this.sessionPath,
      },
      functions: this.functions,
    };
  }
}

async function main() {
  const args = Object.fromEntries(process.argv.slice(2).map((arg, index, arr) => {
    if (!arg.startsWith('--')) return [];
    const key = arg.slice(2);
    const value = arr[index + 1] && !arr[index + 1].startsWith('--') ? arr[index + 1] : true;
    return [key, value];
  }).filter(Boolean));

  const explorer = new SystemExplorer({
    startUrl: args.url,
    maxDepth: args.maxDepth,
    maxPages: args.maxPages,
    headless: args.headless !== 'false',
    outputDir: args.outputDir,
    sessionPath: args.sessionPath,
    safeMode: args.safeMode !== 'false',
    executablePath: args.executablePath,
  });

  try {
    const result = await explorer.explore();
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    if (error.code === 'AUTH_REQUIRED') {
      console.error(JSON.stringify({ status: 'needs_reauth', error: error.message, details: error.details }, null, 2));
      process.exit(2);
    }
    console.error(JSON.stringify({ status: 'error', error: error.message, stack: error.stack }, null, 2));
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { SystemExplorer, AuthRequiredError, NameInferenceError, ClaudeCliNameInference };
