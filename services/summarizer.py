import logging

import requests


logger = logging.getLogger(__name__)


def _build_prompt(en_content):
    return f"""以下是一篇英文新聞的全文內容。請將其摘要成繁體中文，約 150～200 字，只輸出摘要內容，不含標題或任何說明。

英文全文：
{en_content}

繁體中文摘要："""


def summarize_article(en_content, base_url, model, timeout, max_tokens):
    """使用主模型將英文全文摘要成繁體中文；失敗時回傳原文。"""
    if not en_content or not en_content.strip():
        return en_content

    prompt = _build_prompt(en_content)
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        summary = response.json()["choices"][0]["message"]["content"].strip()
        if summary:
            return summary
    except Exception:
        logger.exception("摘要生成失敗，退回原文：%s...", en_content[:80])

    return en_content
