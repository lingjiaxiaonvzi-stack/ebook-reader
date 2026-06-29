@app.route('/api/explain', methods=['POST'])
def explain_text():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'explanation': '请求数据格式错误'}), 400

        text = data.get('text', '').strip()
        if not text:
            return jsonify({'explanation': ''})

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
            "max_tokens": 10000
        }

        # 手动序列化为 UTF-8 字节串，彻底避免编码问题
        json_body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        resp = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=headers,
            data=json_body,          # 用 data 参数传入编码后的字节串
            timeout=60
        )

        # 显式用 UTF-8 解码响应内容
        resp.encoding = 'utf-8'

        if resp.status_code == 200:
            result = resp.json()
            explanation = result['choices'][0]['message']['content']
            return jsonify({'explanation': explanation.strip()})
        else:
            error_msg = f"AI接口返回错误 {resp.status_code}：{resp.text}"
            print(error_msg)
            return jsonify({'explanation': error_msg})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'explanation': f'请求失败：{str(e)}'})
