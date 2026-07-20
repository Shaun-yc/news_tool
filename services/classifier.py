import logging
import re
import time

import requests


REVIEW_REQUIRED = "待人工確認"
MAX_ENGLISH_EVIDENCE_CHARS = 6000
SUMMARY_ALIGNMENT_KEEP_ORIGINAL = "KEEP_ORIGINAL"
VLLM_UNAVAILABLE_COOLDOWN_SECONDS = 300
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
_vllm_unavailable_until = {}


def normalize_tags(result):
    # 清除 Prompt 回聲（模型有時會重複輸出「輸出：」前綴）
    result = re.sub(r'^.*?輸出(?:結果)?[：:]\s*', '', result).strip()
    normalized_result = result.replace("\n", ";").replace("；", ";").replace(",", ";").replace("，", ";")
    if normalized_result.strip().upper() == "NONE":
        return None

    tags = []
    for raw in normalized_result.split(";"):
        # 只去除各標籤頭尾的裝飾字元，保留標籤內部的括號（如 NDC）
        tag = raw.strip().strip('【】[]「」「」\'"')
        if tag in ALLOWED_TAGS and tag not in tags:
            tags.append(tag)
    if 1 <= len(tags) <= 3:
        return ";".join(tags)
    if len(tags) > 3:
        return ";".join(tags[:3])
    return None


def _select_english_evidence(english_content):
    content = (english_content or "").strip()
    if len(content) <= MAX_ENGLISH_EVIDENCE_CHARS:
        return content
    lead_length = 4500
    tail_length = MAX_ENGLISH_EVIDENCE_CHARS - lead_length
    return f"{content[:lead_length]}\n[中段省略]\n{content[-tail_length:]}"


def _build_prompt(title, content, english_content=""):
    english_evidence = _select_english_evidence(english_content)
    return f"""你是嚴謹的氣候政策新聞分類器。請根據中文標題、中文摘要與英文原文證據，從下方標籤池選出最能代表核心內容的標籤。

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
1. 選出 1～3 個最相關標籤，依相關性由高至低排列；理想為 2～3 個，但單一核心主題時只選 1 個。
2. 只選新聞中有明確且屬於核心內容的標籤，不得為達到理想數量而湊標籤。
3. 只能輸出標籤池內的標籤名稱，一字不差。
4. 標籤間以半形分號「;」分隔，只輸出一行，不含任何說明或換行。
5. 若提供的內容無法支持任何一個標籤，輸出 NONE。
6. 不得僅因新聞屬於氣候議題，就預設選擇「溫室氣體減量」或「碳定價」。
7. 中文標題與中文摘要是主要判斷依據；英文原文證據僅用於交叉驗證與補充細節。
8. 每個標籤都必須能在中文標題、中文摘要或英文原文證據中找到明確依據，不得根據原文中的次要背景議題加標籤。

【範例】
標題：歐盟宣布碳邊境調整機制正式啟動
摘要：歐盟 CBAM 自 2026 年起對進口鋼鐵、水泥等課徵碳費，進口商須申報產品碳足跡。
輸出：碳邊境調整機制;碳足跡;氣候法制

【待分類新聞】
中文標題：{title}
中文摘要：{content}
英文原文證據：{english_evidence or "（無可用英文原文）"}
輸出："""


def _build_summary_alignment_prompt(title, content, tags, english_content=""):
    english_evidence = _select_english_evidence(english_content)
    return f"""你是嚴謹的繁體中文新聞編輯。請在不改變事實的前提下，修訂中文摘要，使其更清楚呈現新聞核心與既有分類的明確依據。

【固定分類標籤】
{tags}

【嚴格規則】
1. 分類標籤已固定，不得更名、刪減、增加、重排或在輸出中列出標籤。
2. 只能使用原中文摘要或英文原文證據中可直接支持的事實；不得補充推測、背景常識或原文沒有的細節。
3. 若任一固定標籤找不到足夠事實依據，僅輸出 {SUMMARY_ALIGNMENT_KEEP_ORIGINAL}。
4. 保留原摘要的核心事實、主體、時間與數字；使用繁體中文寫成一段 120 至 500 字摘要。
5. 只輸出修訂後摘要或 {SUMMARY_ALIGNMENT_KEEP_ORIGINAL}，不要說明。

【新聞標題】
{title}

【原中文摘要】
{content}

【英文原文證據】
{english_evidence or "（無可用英文原文）"}
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
                        "以分號分隔輸出；若沒有充分依據則輸出 NONE。"
                        "絕對不輸出其他文字、解釋或說明。"
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


def align_summary_to_tags(
    title,
    content,
    tags,
    vllm_base_url,
    vllm_model,
    vllm_timeout,
    vllm_temperature,
    vllm_max_tokens,
    english_content="",
):
    """Revise a Chinese summary only when fixed tags have source-backed evidence."""
    if not content or not content.strip() or tags == REVIEW_REQUIRED:
        return content, False

    prompt = _build_summary_alignment_prompt(title, content, tags, english_content)
    try:
        response = requests.post(
            f"{vllm_base_url.rstrip('/')}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": vllm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是保守的繁體中文新聞編輯。絕不杜撰、推論或修改固定分類標籤；"
                            "當證據不足時必須輸出 KEEP_ORIGINAL。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": vllm_temperature,
                "max_tokens": vllm_max_tokens,
            },
            timeout=vllm_timeout,
        )
        response.raise_for_status()
        aligned_summary = response.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("Summary alignment failed for title: %s", title)
        return content, False

    if (
        not aligned_summary
        or aligned_summary == SUMMARY_ALIGNMENT_KEEP_ORIGINAL
        or len(aligned_summary) < 120
        or len(aligned_summary) > 500
    ):
        return content, False
    return aligned_summary, aligned_summary != content


def _vllm_key(base_url):
    return (base_url or "").rstrip("/")


def _vllm_unavailable_seconds_remaining(base_url):
    unavailable_until = _vllm_unavailable_until.get(_vllm_key(base_url), 0)
    return max(0, unavailable_until - time.monotonic())


def _mark_vllm_unavailable(base_url):
    _vllm_unavailable_until[_vllm_key(base_url)] = (
        time.monotonic() + VLLM_UNAVAILABLE_COOLDOWN_SECONDS
    )


def _mark_vllm_available(base_url):
    _vllm_unavailable_until.pop(_vllm_key(base_url), None)


def classify_news(
    title,
    content,
    vllm_base_url,
    vllm_model,
    vllm_timeout,
    vllm_temperature,
    vllm_max_tokens,
    english_content="",
):
    """Return tags and whether vLLM produced a valid classification."""
    remaining_seconds = _vllm_unavailable_seconds_remaining(vllm_base_url)
    if remaining_seconds > 0:
        logger.warning(
            "Skipping vLLM classification for title: %s; service temporarily unavailable for %.0f more seconds",
            title,
            remaining_seconds,
        )
        return REVIEW_REQUIRED, False

    prompt = _build_prompt(title, content, english_content)
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
            _mark_vllm_available(vllm_base_url)
            return result, True
        logger.warning("vLLM returned invalid tags for title: %s", title)
    except requests.RequestException:
        _mark_vllm_unavailable(vllm_base_url)
        logger.exception(
            "vLLM classification service unavailable for title: %s; pausing attempts for %s seconds",
            title,
            VLLM_UNAVAILABLE_COOLDOWN_SECONDS,
        )
    except Exception:
        logger.exception("vLLM classification failed for title: %s", title)

    return REVIEW_REQUIRED, False
