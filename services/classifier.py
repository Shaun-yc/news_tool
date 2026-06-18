import logging

import requests


DEFAULT_TAGS = "排放管理;國際事務"
ALLOWED_TAGS = {
    "排放管理",
    "國際事務",
    "調適韌性",
    "減量交易",
    "碳匯",
    "能源轉型",
    "綠色金融",
    "氣候法規",
    "企業永續",
    "碳足跡",
    "淨零碳排",
    "永續供應鏈",
    "循環經濟",
    "ESG指標",
    "碳邊境稅",
    "氣候科技",
}
logger = logging.getLogger(__name__)


def normalize_tags(result):
    normalized_result = result.replace("\n", ";").replace("；", ";").replace(",", ";").replace("，", ";")
    tags = []
    for tag in [candidate.strip() for candidate in normalized_result.split(";") if candidate.strip()]:
        if tag in ALLOWED_TAGS and tag not in tags:
            tags.append(tag)
    if len(tags) == 1:
        for fallback_tag in DEFAULT_TAGS.split(";"):
            if fallback_tag not in tags:
                tags.append(fallback_tag)
            if len(tags) == 2:
                break
    if 2 <= len(tags) <= 5:
        return ";".join(tags)
    if len(tags) > 5:
        return ";".join(tags[:5])
    return None


def _build_prompt(title, content):
    return f"""
你是一個嚴謹的氣候與減碳數據分析官。請仔細閱讀下方給定新聞的標題與摘要。

【可選標籤池 (共 16 個)】
[排放管理, 國際事務, 調適韌性, 減量交易, 碳匯, 能源轉型, 綠色金融, 氣候法規, 企業永續, 碳足跡, 淨零碳排, 永續供應鏈, 循環經濟, ESG指標, 碳邊境稅, 氣候科技]

【任務限制】
1. 請根據新聞核心內容，從上方標籤池選出 2～5 個最相關的標籤。
2. 標籤之間請一律使用分號「;」隔開。
3. 嚴禁對所有新聞都給出相同的罐頭標籤，請針對具體內容進行差異化分析！
4. 只需要輸出標籤字串，絕對不要包含任何解釋、Markdown、或額外換行。

【範例參考】
輸入標題：歐盟執委會宣布新增 ETS 彈性措施
輸入摘要：歐盟修改碳市場總量管制，釋出免費配額以穩定碳價。
輸出應為：排放管理;減量交易;氣候法規

【當前請分類的新聞】
中文標題：{title}
內容摘要：{content}

輸出結果："""


def _classify_with_vllm(base_url, model_name, prompt, timeout, temperature, max_tokens):
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        headers={"Content-Type": "application/json"},
        json={
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def classify_news(
    title,
    content,
    vllm_base_url,
    vllm_model,
    vllm_timeout,
    vllm_temperature,
    vllm_max_tokens,
):
    """Return tags and whether vLLM produced a valid classification."""
    prompt = _build_prompt(title, content)
    try:
        result = normalize_tags(
            _classify_with_vllm(
                vllm_base_url,
                vllm_model,
                prompt,
                vllm_timeout,
                vllm_temperature,
                vllm_max_tokens,
            )
        )
        if result:
            return result, True
        logger.warning("vLLM returned invalid tags for title: %s", title)
    except Exception:
        logger.exception("vLLM classification failed for title: %s", title)

    return DEFAULT_TAGS, False
