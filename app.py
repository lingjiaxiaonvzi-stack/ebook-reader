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

# ---------- HTML 完整版（保持不变，此处省略以节省篇幅，请使用你原代码中的 HTML_CONTENT）----------
HTML_CONTENT = """
... (你原有的 HTML 代码，太长省略，请直接粘贴原来的) ...
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7070))
    print(f"🚀 电子书阅读助手启动成功！访问端口 {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
