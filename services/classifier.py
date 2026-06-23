import logging
import re

import requests


DEFAULT_TAGS = "溫室氣體減量;碳定價"
ALLOWED_TAGS = {
    "溫室氣體減量",
    "氣候變遷調適",
    "公約會議及進展",
    "各國減碳目標(NDC)",
    "碳定價",
    "總量管制排放交易",
    "碳信用額度",
    "溫室氣體排放清冊",
    "碳邊境調整機制",
    "國際碳權合作",
    "碳足跡",
    "綠色成長",
    "淨零科技",
    "氣候變遷科學報告",
    "氣候變遷教育",
    "氣候法制",
}
logger = logging.getLogger(__name__)


def normalize_tags(result):
    # 清除 Prompt 回聲（模型有時會重複輸出「輸出：」前綴）
    result = re.sub(r'^.*?輸出(?:結果)?[：:]\s*', '', result).strip()
    normalized_result = result.replace("\n", ";").replace("；", ";").replace(",", ";").replace("，", ";")
    tags = []
    for raw in normalized_result.split(";"):
        # 只去除各標籤頭尾的裝飾字元，保留標籤內部的括號（如 NDC）
        tag = raw.strip().strip('【】[]「」「」\'"')
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
    return f"""你是嚴謹的氣候政策新聞分類器。請根據新聞標題與摘要，從下方標籤池選出最能代表核心內容的標籤。

【標籤池（共 16 個）】
溫室氣體減量, 氣候變遷調適, 公約會議及進展, 各國減碳目標(NDC), 碳定價, 總量管制排放交易, 碳信用額度, 溫室氣體排放清冊, 碳邊境調整機制, 國際碳權合作, 碳足跡, 綠色成長, 淨零科技, 氣候變遷科學報告, 氣候變遷教育, 氣候法制

【各標籤說明】
溫室氣體減量：企業或國家的減排措施、行動、技術與成效。
氣候變遷調適：因應氣候衝擊的調適策略、韌性建設、災害風險管理。
公約會議及進展：UNFCCC、COP、IPCC 等國際氣候會議與談判進展。
各國減碳目標(NDC)：各國國家自定貢獻、氣候承諾目標更新與落實。
碳定價：碳稅、碳費、碳定價制度設計與實施。
總量管制排放交易：ETS 排放交易制度、碳市場運作與配額管理。
碳信用額度：自願性碳市場、碳信用、碳抵換、VCS、Gold Standard。
溫室氣體排放清冊：排放盤查、MRV 機制、排放資料統計與報告。
碳邊境調整機制：CBAM、碳關稅、進出口碳成本與貿易影響。
國際碳權合作：巴黎協定第六條、雙邊碳權交易合作機制。
碳足跡：產品或組織生命週期碳排放計算與標示。
綠色成長：綠色經濟、永續發展、ESG、企業永續策略。
淨零科技：CCUS、氫能、再生能源、淨零相關創新技術。
氣候變遷科學報告：IPCC 報告、氣候科學研究與觀測數據。
氣候變遷教育：氣候意識推廣、公眾教育與人才培育。
氣候法制：氣候相關立法、法規制定、氣候訴訟與司法判決。

【任務規則】
1. 選出 2～5 個最相關標籤，依相關性由高至低排列。
2. 只選新聞中有明確依據的標籤，不湊數量。
3. 只能輸出標籤池內的標籤名稱，一字不差。
4. 標籤間以半形分號「;」分隔，只輸出一行，不含任何說明或換行。

【範例】
標題：歐盟宣布碳邊境調整機制正式啟動
摘要：歐盟 CBAM 自 2026 年起對進口鋼鐵、水泥等課徵碳費，進口商須申報產品碳足跡。
輸出：碳邊境調整機制;碳足跡;氣候法制

【待分類新聞】
標題：{title}
摘要：{content}
輸出："""


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
