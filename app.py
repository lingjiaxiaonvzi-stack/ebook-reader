#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
电子书阅读助手 - EPUB阅读器 + AI解读 + 笔记管理
部署在 Zeabur 上，跨设备同步阅读进度和笔记。
"""

import os
import json
import uuid
import sys
import traceback
import requests
from datetime import datetime
from flask import Flask, request, jsonify, send_file, Response

# ---------- 配置 ----------
BASE_DIR = os.environ.get("DATA_DIR", "/data")
BOOKS_DIR = os.path.join(BASE_DIR, "books")
NOTES_DIR = os.path.join(BASE_DIR, "notes")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(NOTES_DIR, exist_ok=True)

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "你的默认key")
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-v4-pro"

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

# ---------- 状态管理 ----------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(book_id, cfi):
    state = {
        "book_id": book_id,
        "cfi": cfi,
        "timestamp": datetime.now().isoformat()
    }
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ---------- 笔记管理 ----------
def get_note_path(book_id):
    return os.path.join(NOTES_DIR, f"{book_id}.json")

def load_notes(book_id):
    path = get_note_path(book_id)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"highlights": [], "bookmarks": [], "ideas": []}

def save_notes(book_id, data):
    path = get_note_path(book_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- 路由 ----------
@app.route('/')
def index():
    return HTML_CONTENT

@app.route('/api/upload', methods=['POST'])
def upload_epub():
    try:
        if 'file' not in request.files:
            return jsonify({'error': '未上传文件'}), 400
        file = request.files['file']
        if file.filename == '' or not file.filename.lower().endswith('.epub'):
            return jsonify({'error': '仅支持.epub文件'}), 400

        book_id = uuid.uuid4().hex
        filename = f"{book_id}.epub"
        save_path = os.path.join(BOOKS_DIR, filename)
        file.save(save_path)
        print(f"📥 电子书已保存: {save_path}")
        return jsonify({'book_id': book_id, 'filename': filename})
    except Exception as e:
        print(f"[UPLOAD FATAL] 异常: {type(e).__name__} - {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': f'保存文件失败: {str(e)}'}), 500

@app.route('/api/books/<book_id>/epub')
def serve_epub(book_id):
    filepath = os.path.join(BOOKS_DIR, f"{book_id}.epub")
    if not os.path.exists(filepath):
        return "File not found", 404
    return send_file(filepath, mimetype='application/epub+zip')

@app.route('/api/state', methods=['GET'])
def get_state():
    return jsonify(load_state())

@app.route('/api/state', methods=['PUT'])
def update_state():
    data = request.get_json()
    book_id = data.get('book_id', '')
    cfi = data.get('cfi', '')
    if book_id:
        save_state(book_id, cfi)
        filepath = os.path.join(BOOKS_DIR, f"{book_id}.epub")
        if not os.path.exists(filepath):
            return jsonify({'error': '书籍文件不存在'}), 404
        return jsonify({'status': 'saved'})
    return jsonify({'error': '缺少 book_id'}), 400

@app.route('/api/notes/<book_id>', methods=['GET'])
def get_notes(book_id):
    return jsonify(load_notes(book_id))

@app.route('/api/notes/<book_id>', methods=['PUT'])
def update_notes(book_id):
    data = request.get_json()
    save_notes(book_id, data)
    return jsonify({'status': 'saved'})

@app.route('/api/explain', methods=['POST'])
def explain_text():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'explanation': '请求数据格式错误'}), 400

        text = data.get('text', '').strip()
        if not text:
            return jsonify({'explanation': ''})

        # 详细日志：记录请求文本长度
        print(f"[EXPLAIN] 收到解读请求，文本长度: {len(text)}", file=sys.stderr)

        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一位善于用通俗语言讲解复杂知识的阅读导师，请用中文详细解读用户提供的文本。"
                },
                {"role": "user", "content": text}
            ],
            "temperature": 0.5,
            "max_tokens": 4096  # 降低到 4096，减少生成时间和内存占用
        }

        json_body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        # 增加 requests 超时到 180 秒（连接超时 10 秒，读取超时 180 秒）
        resp = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=headers,
            data=json_body,
            timeout=(10, 180)
        )

        resp.encoding = 'utf-8'

        if resp.status_code == 200:
            result = resp.json()
            explanation = result['choices'][0]['message']['content']
            print(f"[EXPLAIN] 成功获取解读，回复长度: {len(explanation)}", file=sys.stderr)
            return jsonify({'explanation': explanation.strip()})
        else:
            error_msg = f"AI接口返回错误 {resp.status_code}：{resp.text[:500]}"
            print(f"[EXPLAIN ERROR] {error_msg}", file=sys.stderr)
            return jsonify({'explanation': error_msg})

    except requests.exceptions.Timeout:
        print("[EXPLAIN FATAL] 请求 AI 接口超时", file=sys.stderr)
        return jsonify({'explanation': 'AI 请求超时，请稍后重试或缩短选文'})
    except Exception as e:
        print(f"[EXPLAIN FATAL] 异常类型: {type(e).__name__}", file=sys.stderr)
        print(f"[EXPLAIN FATAL] 详细信息: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({'explanation': f'请求失败：{str(e)}'})

@app.route('/api/export/<book_id>', methods=['GET'])
def export_notes(book_id):
    notes = load_notes(book_id)
    export_lines = [f"# 阅读笔记 - {book_id}", f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    if notes['bookmarks']:
        export_lines.append("## 书签")
        for bm in notes['bookmarks']:
            export_lines.append(f"- {bm.get('label','')} (位置: {bm.get('cfi','')})")
    if notes['highlights']:
        export_lines.append("\n## 划线笔记")
        for hl in notes['highlights']:
            export_lines.append(f"\n### 原文")
            export_lines.append(f"> {hl.get('text','')}")
            export_lines.append(f"**AI解读**: {hl.get('ai_explanation','')}")
            if hl.get('note'):
                export_lines.append(f"**我的想法**: {hl['note']}")
    if notes['ideas']:
        export_lines.append("\n## 独立想法")
        for idea in notes['ideas']:
            export_lines.append(f"- {idea.get('content','')} (关联: {idea.get('ref','')})")
    content = "\n".join(export_lines)
    return Response(content, mimetype='text/markdown', headers={
        "Content-Disposition": f"attachment; filename=notes_{book_id}.md"
    })

# ---------- HTML 完整版（你原来的前端代码，一字未改）----------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>电子书阅读助手</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/epub.js/0.3.93/epub.min.js"></script>
  <script>
    if (typeof ePub === 'undefined') {
      document.write('<script src="https://cdn.jsdelivr.net/npm/epubjs@0.3.93/dist/epub.min.js"><\\/script>');
    }
  </script>
  <script>
    window._markedReady = false;
    function loadMarked() {
      return new Promise((resolve) => {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
        script.onload = () => {
          if (typeof marked !== 'undefined') {
            marked.setOptions({ breaks: true, gfm: true });
            window._markedReady = true;
          }
          resolve();
        };
        script.onerror = () => resolve();
        document.head.appendChild(script);
      });
    }
  </script>
  <style>
    #viewer {
      width: 100%;
      height: calc(100vh - 64px);
      overflow: hidden;
      background: #f8fafc;
    }
    #viewer iframe {
      width: 100%;
      height: 100%;
      border: none;
    }
    .highlight-yellow { background-color: #fef08a; cursor: pointer; }
    .highlight-blue { background-color: #bfdbfe; cursor: pointer; }
    .highlight-green { background-color: #bbf7d0; cursor: pointer; }
    .highlight-pink { background-color: #fbcfe8; cursor: pointer; }
    .note-panel { height: calc(100vh - 64px); overflow-y: auto; }
    .toc-item { cursor: pointer; padding: 4px 8px; border-radius: 4px; }
    .toc-item:hover { background: #f1f5f9; }
    .toc-item.active { background: #dbeafe; color: #1e40af; }
    .loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; }
    .progress-bar-indeterminate { animation: progress-move 1.5s ease-in-out infinite; }
    @keyframes progress-move {
      0% { left: -30%; width: 30%; }
      50% { left: 50%; width: 40%; }
      100% { left: 100%; width: 30%; }
    }
    .note-content p { margin-bottom: 0.5rem; }
    .note-content strong { font-weight: 700; color: #1e3a8a; }
    .note-content ul, .note-content ol { padding-left: 1.5rem; margin-bottom: 0.5rem; }
    .note-content li { list-style: disc; }
    .font-control-btn {
      width: 28px;
      height: 28px;
      border-radius: 6px;
      background: #f3f4f6;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      color: #374151;
      user-select: none;
    }
    .font-control-btn:hover { background: #e5e7eb; }
  </style>
</head>
<body class="bg-gray-50 font-sans">

  <!-- 顶部工具栏 -->
  <nav class="bg-white shadow-sm border-b border-gray-200 h-16 flex items-center px-6 justify-between">
    <div class="flex items-center gap-4">
      <h1 class="text-xl font-bold text-gray-800">📖 电子书阅读助手</h1>
      <span id="bookTitle" class="text-sm text-gray-500 hidden"></span>
      <button id="tocBtn" class="bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded text-sm hidden">目录</button>
    </div>
    <div class="flex items-center gap-3">
      <div id="fontControls" class="flex items-center gap-1.5 hidden">
        <button class="font-control-btn" onclick="changeFontSize(-1)">A−</button>
        <span id="fontSizeDisplay" class="text-xs text-gray-500 w-10 text-center">16</span>
        <button class="font-control-btn" onclick="changeFontSize(1)">A+</button>
      </div>
      <input type="file" id="epubInput" accept=".epub" class="hidden" />
      <button onclick="document.getElementById('epubInput').click()" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-md text-sm font-medium transition">导入 EPUB</button>
      <button id="exportBtn" onclick="exportNotes()" class="bg-gray-200 hover:bg-gray-300 text-gray-700 px-4 py-2 rounded-md text-sm font-medium transition disabled:opacity-50" disabled>导出笔记</button>
    </div>
  </nav>

  <!-- 目录侧边栏 -->
  <div id="tocSidebar" class="fixed left-0 top-16 h-full w-64 bg-white shadow-lg border-r border-gray-200 transform -translate-x-full transition-transform z-40">
    <div class="p-4 border-b border-gray-200 flex justify-between items-center">
      <h2 class="font-bold text-sm text-gray-700">📑 目录</h2>
      <button onclick="toggleToc()" class="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
    </div>
    <div id="tocList" class="overflow-y-auto p-3 text-sm" style="height: calc(100vh - 160px);">
      <p class="text-gray-400">加载中...</p>
    </div>
  </div>

  <!-- 主内容区 -->
  <div class="flex">
    <div class="w-4/5 border-r border-gray-200 relative">
      <div id="viewer">
        <div class="loading-container">
          <div class="w-56 h-2 bg-gray-200 rounded-full overflow-hidden relative">
            <div class="absolute top-0 h-full bg-blue-500 rounded-full progress-bar-indeterminate"></div>
          </div>
          <p class="mt-4 text-sm text-gray-500">正在检查阅读进度...</p>
        </div>
      </div>
      <div id="selectionToolbar" class="absolute bg-white shadow-lg rounded-lg p-2 flex gap-1 hidden" style="top:0; left:0; z-index:30;">
        <button onclick="addHighlight('yellow')" class="w-6 h-6 rounded bg-yellow-200" title="黄色标记"></button>
        <button onclick="addHighlight('blue')" class="w-6 h-6 rounded bg-blue-200" title="蓝色标记"></button>
        <button onclick="addHighlight('green')" class="w-6 h-6 rounded bg-green-200" title="绿色标记"></button>
        <button onclick="addHighlight('pink')" class="w-6 h-6 rounded bg-pink-200" title="粉色标记"></button>
        <button onclick="addBookmark()" class="text-xs bg-gray-100 hover:bg-gray-200 px-2 py-1 rounded" title="添加书签">🔖</button>
        <button onclick="writeIdea()" class="text-xs bg-gray-100 hover:bg-gray-200 px-2 py-1 rounded" title="写想法">💡</button>
      </div>
    </div>

    <!-- 右侧笔记面板 -->
    <div class="w-1/5 bg-white note-panel border-l border-gray-200 flex flex-col">
      <div class="flex border-b border-gray-200">
        <button onclick="switchTab('highlights')" class="tab-btn flex-1 py-3 text-sm font-medium border-b-2 border-blue-600 text-blue-600" data-tab="highlights">划线</button>
        <button onclick="switchTab('bookmarks')" class="tab-btn flex-1 py-3 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700" data-tab="bookmarks">书签</button>
        <button onclick="switchTab('ideas')" class="tab-btn flex-1 py-3 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700" data-tab="ideas">想法</button>
      </div>
      <div id="tabContent" class="flex-1 overflow-y-auto p-3 space-y-3"></div>
    </div>
  </div>

  <!-- 想法弹窗 -->
  <div id="ideaModal" class="fixed inset-0 bg-black/30 flex items-center justify-center hidden z-50">
    <div class="bg-white rounded-xl shadow-xl p-6 w-96">
      <h3 class="font-bold text-lg mb-3">记录想法</h3>
      <textarea id="ideaText" class="w-full border rounded p-2 text-sm" rows="4" placeholder="输入你的想法..."></textarea>
      <div class="flex justify-end gap-2 mt-4">
        <button onclick="closeIdeaModal()" class="px-4 py-1.5 text-sm bg-gray-100 rounded hover:bg-gray-200">取消</button>
        <button onclick="saveIdea()" class="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">保存</button>
      </div>
    </div>
  </div>

  <script>
    loadMarked();

    let book = null, rendition = null, currentBookId = null;
    let notesData = { highlights: [], bookmarks: [], ideas: [] };
    let tempSelection = null, pendingCfi = null;
    let currentFontSize = 16;
    let autoSaveInterval = null;

    const toolbar = document.getElementById('selectionToolbar');
    const viewerDiv = document.getElementById('viewer');
    const tocList = document.getElementById('tocList');
    const fontControls = document.getElementById('fontControls');
    const fontSizeDisplay = document.getElementById('fontSizeDisplay');

    window.addEventListener('load', () => {
      if (typeof ePub === 'undefined') {
        viewerDiv.innerHTML = '<div class="flex items-center justify-center h-full text-red-500">⚠️ epub.js 库加载失败，请检查网络后刷新</div>';
        return;
      }
      // 自动恢复上次进度
      restoreLastSession();
    });

    function showLoading(msg) {
      viewerDiv.innerHTML = `<div class="loading-container">
        <div class="w-56 h-2 bg-gray-200 rounded-full overflow-hidden relative">
          <div class="absolute top-0 h-full bg-blue-500 rounded-full progress-bar-indeterminate"></div>
        </div>
        <p class="mt-4 text-sm text-gray-600">${msg}</p>
      </div>`;
      fontControls.classList.add('hidden');
      document.getElementById('tocBtn').classList.add('hidden');
      document.getElementById('bookTitle').classList.add('hidden');
      document.getElementById('exportBtn').disabled = true;
    }

    function showError(msg) {
      viewerDiv.innerHTML = `<div class="flex items-center justify-center h-full text-red-500">⚠️ ${msg}</div>`;
      fontControls.classList.add('hidden');
    }

    // ---------- 自动恢复上次进度 ----------
    async function restoreLastSession() {
      showLoading('正在检查上次阅读进度...');
      try {
        const resp = await fetch('/api/state');
        const state = await resp.json();
        if (state && state.book_id) {
          // 检查书籍文件是否存在
          const checkResp = await fetch(`/api/books/${state.book_id}/epub`, { method: 'HEAD' });
          if (!checkResp.ok) {
            showLoading('点击「导入 EPUB」开始阅读');
            return;
          }
          showLoading('正在恢复上次阅读进度...');
          const epubResp = await fetch(`/api/books/${state.book_id}/epub`);
          const arrayBuffer = await epubResp.arrayBuffer();
          currentBookId = state.book_id;
          document.getElementById('bookTitle').textContent = '已恢复的书籍';
          document.getElementById('bookTitle').classList.remove('hidden');
          document.getElementById('tocBtn').classList.remove('hidden');
          document.getElementById('exportBtn').disabled = false;
          await loadBookFromArrayBuffer(arrayBuffer, state.cfi || null);
        } else {
          showLoading('点击「导入 EPUB」开始阅读');
        }
      } catch (e) {
        showLoading('点击「导入 EPUB」开始阅读');
      }
    }

    // ---------- 核心加载函数 ----------
    async function loadBookFromArrayBuffer(arrayBuffer, savedCfi) {
      if (rendition) { rendition.destroy(); rendition = null; }
      if (book) { book.destroy(); }

      try {
        book = ePub(arrayBuffer);
        await book.ready;
        renderToc();

        viewerDiv.innerHTML = '';
        rendition = book.renderTo("viewer", {
          width: '100%',
          height: '100%',
          spread: 'none',
          flow: 'scrolled-doc'
        });

        await rendition.display();
        currentFontSize = 16;
        rendition.themes.fontSize('16px');
        fontSizeDisplay.textContent = currentFontSize;
        fontControls.classList.remove('hidden');

        // 跳转到上次位置
        if (savedCfi) {
          rendition.display(savedCfi);
        }

        // 加载笔记
        const resp = await fetch(`/api/notes/${currentBookId}`);
        notesData = await resp.json();
        applySavedHighlights();

        // 事件监听
        rendition.on('selected', (cfiRange, contents) => {
          const range = rendition.getRange(cfiRange);
          if (range) {
            tempSelection = { cfiRange, text: range.toString() };
            const rect = contents.window.getSelection().getRangeAt(0).getBoundingClientRect();
            const viewerRect = viewerDiv.getBoundingClientRect();
            toolbar.style.left = Math.min(rect.left - viewerRect.left + rect.width/2, viewerDiv.offsetWidth - 150) + 'px';
            toolbar.style.top = Math.min(rect.top - viewerRect.top - 40, viewerDiv.offsetHeight - 50) + 'px';
            toolbar.classList.remove('hidden');
          }
        });

        rendition.on('relocated', (location) => {
          toolbar.classList.add('hidden');
          // 自动保存位置
          saveReadingPosition();
        });

        rendition.on('displayError', (err) => {
          console.error('displayError:', err);
          showError('页面渲染出错: ' + (err.message || ''));
        });

        // 启动定时自动保存（每5秒）
        startAutoSave();
      } catch (error) {
        console.error('加载失败:', error);
        showError('加载失败: ' + (error.message || '未知错误'));
      }
    }

    async function loadBookFromFile(file) {
      const arrayBuffer = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('文件读取失败'));
        reader.readAsArrayBuffer(file);
      });
      await loadBookFromArrayBuffer(arrayBuffer, null);
    }

    // ---------- 位置保存 ----------
    async function saveReadingPosition() {
      if (!currentBookId || !rendition) return;
      try {
        const location = rendition.currentLocation();
        if (location && location.start) {
          const cfi = location.start.cfi;
          await fetch('/api/state', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ book_id: currentBookId, cfi: cfi })
          });
        }
      } catch (e) { /* 静默失败 */ }
    }

    function startAutoSave() {
      if (autoSaveInterval) clearInterval(autoSaveInterval);
      autoSaveInterval = setInterval(() => {
        saveReadingPosition();
      }, 5000);
    }

    // 页面关闭前保存
    window.addEventListener('beforeunload', () => {
      if (autoSaveInterval) clearInterval(autoSaveInterval);
      saveReadingPosition();
    });

    // ---------- 其他功能保持不变 ----------
    function toggleToc() {
      document.getElementById('tocSidebar').classList.toggle('-translate-x-full');
    }
    document.getElementById('tocBtn').addEventListener('click', toggleToc);

    function changeFontSize(delta) {
      if (!rendition) return;
      currentFontSize = Math.min(32, Math.max(12, currentFontSize + delta));
      rendition.themes.fontSize(currentFontSize + 'px');
      fontSizeDisplay.textContent = currentFontSize;
    }

    document.getElementById('epubInput').addEventListener('change', async function(e) {
      const file = e.target.files[0];
      if (!file) return;
      const formData = new FormData();
      formData.append('file', file);
      showLoading('正在上传存档...');
      try {
        const resp = await fetch('/api/upload', { method:'POST', body:formData });
        const data = await resp.json();
        if (data.book_id) {
          currentBookId = data.book_id;
          document.getElementById('bookTitle').textContent = file.name.replace('.epub','');
          document.getElementById('bookTitle').classList.remove('hidden');
          document.getElementById('tocBtn').classList.remove('hidden');
          document.getElementById('exportBtn').disabled = false;
          await loadBookFromFile(file);
        } else {
          showError('上传失败: ' + (data.error || '未知错误'));
        }
      } catch(e) {
        showError('网络错误：' + e.message);
      }
    });

    function renderToc() {
      const nav = book.navigation;
      if (!nav || !nav.toc || nav.toc.length === 0) {
        tocList.innerHTML = '<p class="text-gray-400">无目录数据</p>';
        return;
      }
      function buildList(items, level = 0) {
        return items.map(item => {
          const label = item.label || '未命名';
          const children = item.subitems ? buildList(item.subitems, level + 1) : '';
          return `<div class="toc-item" data-href="${item.href}" style="padding-left: ${level * 16 + 8}px">${label}${children ? `<div class="ml-0">${children}</div>` : ''}</div>`;
        }).join('');
      }
      tocList.innerHTML = buildList(nav.toc);
      tocList.querySelectorAll('.toc-item').forEach(el => {
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          const href = el.getAttribute('data-href');
          if (href && rendition) {
            rendition.display(href);
            if (window.innerWidth < 1024) toggleToc();
            document.querySelectorAll('.toc-item').forEach(i => i.classList.remove('active'));
            el.classList.add('active');
          }
        });
      });
    }

    function applySavedHighlights() {
      if (!rendition) return;
      rendition.annotations.remove('highlight', 'highlight');
      notesData.highlights.forEach(hl => {
        try {
          rendition.annotations.add('highlight', hl.cfiRange, {}, null, 'hl', {
            'class': `highlight-${hl.color}`,
            'data-id': hl.id
          });
        } catch(e) {}
      });
    }

    async function addHighlight(color) {
      if (!tempSelection || !currentBookId) { toolbar.classList.add('hidden'); return; }
      const { cfiRange, text } = tempSelection;
      const id = Date.now().toString(36);
      notesData.highlights.push({ id, cfiRange, text, color, note: '', ai_explanation: '', created_at: new Date().toISOString() });
      await saveNotes();
      rendition.annotations.add('highlight', cfiRange, {}, null, 'hl', { 'class': `highlight-${color}`, 'data-id': id });
      toolbar.classList.add('hidden');
      renderTab();
    }

    async function requestExplanation(hlId) {
      const hl = notesData.highlights.find(h => h.id === hlId);
      if (!hl || hl.ai_explanation === '解读中...') return;
      hl.ai_explanation = '解读中...';
      saveNotes();
      renderTab();
      try {
        const resp = await fetch('/api/explain', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: hl.text })
        });
        const data = await resp.json();
        hl.ai_explanation = data.explanation || '无法获取解读';
      } catch (e) {
        hl.ai_explanation = 'AI请求失败，请检查网络';
      }
      saveNotes();
      renderTab();
    }

    function addBookmark() {
      if (!currentBookId || !rendition) return;
      const loc = rendition.currentLocation();
      if (!loc) return;
      notesData.bookmarks.push({ id: Date.now().toString(36), cfi: loc.start.cfi, label: `书签 ${notesData.bookmarks.length+1}`, created_at: new Date().toISOString() });
      saveNotes();
      toolbar.classList.add('hidden');
      renderTab();
    }

    function goToCfi(cfi) { if (rendition) rendition.display(cfi); }

    function writeIdea() {
      if (!currentBookId || !rendition) return;
      const loc = rendition.currentLocation();
      pendingCfi = loc ? loc.start.cfi : '';
      document.getElementById('ideaModal').classList.remove('hidden');
      toolbar.classList.add('hidden');
    }
    function closeIdeaModal() { document.getElementById('ideaModal').classList.add('hidden'); }
    function saveIdea() {
      const content = document.getElementById('ideaText').value.trim();
      if (!content) return;
      notesData.ideas.push({ id: Date.now().toString(36), content, ref: pendingCfi || '', created_at: new Date().toISOString() });
      saveNotes();
      closeIdeaModal();
      renderTab();
    }

    function addNoteToHighlight(hlId) {
      const note = prompt('输入你的想法:');
      if (note === null) return;
      const hl = notesData.highlights.find(h => h.id === hlId);
      if (hl) { hl.note = note; saveNotes(); renderTab(); }
    }

    let currentTab = 'highlights';
    function switchTab(tab) {
      currentTab = tab;
      document.querySelectorAll('.tab-btn').forEach(btn => {
        const active = btn.dataset.tab === tab;
        btn.classList.toggle('border-blue-600', active);
        btn.classList.toggle('text-blue-600', active);
        btn.classList.toggle('border-transparent', !active);
        btn.classList.toggle('text-gray-500', !active);
      });
      renderTab();
    }

    function renderMarkdown(mdText) {
      if (!mdText) return '';
      if (window._markedReady && typeof marked !== 'undefined') {
        return marked.parse(mdText);
      }
      return mdText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\\n/g, '<br>');
    }

    function renderTab() {
      const container = document.getElementById('tabContent');
      if (!notesData) { container.innerHTML = ''; return; }
      if (currentTab === 'highlights') {
        container.innerHTML = notesData.highlights.length === 0
          ? '<p class="text-sm text-gray-400 text-center mt-8">选中文字划线</p>'
          : notesData.highlights.map(hl => `
            <div class="bg-gray-50 rounded p-3 border border-gray-100 hover:shadow-sm cursor-pointer" onclick="goToCfi('${hl.cfiRange}')">
              <div class="flex justify-between text-xs text-gray-500 mb-1">
                <span class="bg-${hl.color}-200 px-1.5 py-0.5 rounded">${hl.color}</span>
                <span class="cursor-pointer text-blue-500" onclick="event.stopPropagation();addNoteToHighlight('${hl.id}')">✏️</span>
              </div>
              <p class="text-sm line-clamp-2">${hl.text}</p>
              ${hl.ai_explanation === ''
                ? `<button onclick="event.stopPropagation();requestExplanation('${hl.id}')" class="text-xs text-blue-500 mt-1 hover:underline">💡 AI解读</button>`
                : (hl.ai_explanation === '解读中...'
                  ? '<p class="text-xs text-gray-400 mt-1">⏳ 解读中...</p>'
                  : `<div class="mt-2 p-2 bg-blue-50 rounded text-xs note-content">${renderMarkdown(hl.ai_explanation)}</div>`)
              }
              ${hl.note ? `<p class="text-xs text-purple-600 mt-1">📝 ${hl.note}</p>` : ''}
            </div>`).join('');
      } else if (currentTab === 'bookmarks') {
        container.innerHTML = notesData.bookmarks.length === 0
          ? '<p class="text-sm text-gray-400 text-center mt-8">暂无书签</p>'
          : notesData.bookmarks.map(bm => `
            <div class="bg-gray-50 rounded p-3 border border-gray-100 cursor-pointer hover:bg-gray-100" onclick="goToCfi('${bm.cfi}')">
              <span class="text-sm">🔖 ${bm.label}</span>
            </div>`).join('');
      } else {
        container.innerHTML = notesData.ideas.length === 0
          ? '<p class="text-sm text-gray-400 text-center mt-8">暂无想法</p>'
          : notesData.ideas.map(idea => `
            <div class="bg-yellow-50 rounded p-3 border border-yellow-100">
              <p class="text-sm">${idea.content}</p>
              ${idea.ref ? `<button onclick="goToCfi('${idea.ref}')" class="text-xs text-blue-500 mt-1">📍 跳转位置</button>` : ''}
            </div>`).join('');
      }
    }

    async function saveNotes() {
      if (!currentBookId) return;
      try {
        await fetch(`/api/notes/${currentBookId}`, {
          method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(notesData)
        });
      } catch(e) { console.error('保存笔记失败', e); }
    }

    function exportNotes() {
      if (!currentBookId) return;
      window.open(`/api/export/${currentBookId}`, '_blank');
    }

    renderTab();

    document.addEventListener('click', (e) => {
      if (!toolbar.contains(e.target) && !e.target.closest('#selectionToolbar')) toolbar.classList.add('hidden');
    });
  </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7070))
    print(f"🚀 电子书阅读助手启动成功！访问端口 {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
