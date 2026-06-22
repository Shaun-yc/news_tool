import logging
import re

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
    # 清除模型常見輸出雜訊：括號、引號、Prompt 回聲
    result = re.sub(r'[【】\[\]「」（）()]', '', result)
    result = re.sub(r'^.*?輸出(?:結果)?[：:]\s*', '', result).strip()
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
你是一個嚴謹的氣候政策與減碳新聞分類器。請根據新聞標題與摘要，從指定標籤池中選出最能代表新聞核心內容的標籤。

【可選標籤池】
[排放管理, 國際事務, 調適韌性, 減量交易, 碳匯, 能源轉型, 綠色金融, 氣候法規, 企業永續, 碳足跡, 淨零碳排, 永續供應鏈, 循環經濟, ESG指標, 碳邊境稅, 氣候科技]

【標籤選擇原則】

* 排放管理：溫室氣體排放盤查、管理、揭露、減排措施。
* 國際事務：國際氣候會議、跨國政策、國際合作或國家間氣候議題。
* 調適韌性：氣候災害調適、風險管理、韌性建設。
* 減量交易：碳權、碳市場、排放交易制度、碳信用。
* 碳匯：森林、土壤、海洋、碳捕捉與碳移除。
* 能源轉型：再生能源、燃煤退場、能源結構轉型。
* 綠色金融：永續金融、綠色債券、氣候融資、金融機構投融資。
* 氣候法規：氣候相關法律、政策、監管與法定要求。
* 企業永續：企業永續策略、永續治理、永續報告。
* 碳足跡：產品或服務生命週期碳排放與碳足跡計算。
* 淨零碳排：淨零目標、碳中和承諾與淨零路徑。
* 永續供應鏈：供應商減碳、供應鏈碳管理與責任採購。
* 循環經濟：資源循環、回收再利用、廢棄物減量。
* ESG指標：ESG評分、指標、揭露準則與績效衡量。
* 碳邊境稅：CBAM、碳關稅與進出口碳成本。
* 氣候科技：減碳技術、碳管理技術、氣候相關創新科技。

【任務限制】

1. 從標籤池選出 2～5 個最相關的標籤。
2. 依相關性由高至低排列。
3. 只選擇新聞中有明確依據的標籤，不要為了湊足數量而加入弱相關標籤。
4. 不得輸出標籤池以外的內容。
5. 標籤之間一律使用半形分號「;」分隔。
6. 只輸出一行標籤字串。
7. 不得輸出解釋、編號、Markdown、引號或額外換行。

【範例】
輸入標題：歐盟執委會宣布新增 ETS 彈性措施
輸入摘要：歐盟修改碳市場總量管制，釋出免費配額以穩定碳價。
輸出：
減量交易;氣候法規;國際事務

【待分類新聞】
中文標題：{title}
內容摘要：{content}

輸出：
"""


def _classify_with_vllm(base_url, model_name, prompt, timeout, temperature, max_tokens):
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        headers={"Content-Type": "application/json"},
        json={
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是嚴格的標籤分類器。只能從用戶指定的標籤池中選取標籤，"
                        "以分號分隔輸出，絕對不輸出任何標籤池以外的文字、解釋或說明。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stop": ["\n\n", "（", "解釋", "說明：", "Note:"],
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
