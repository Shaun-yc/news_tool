from datetime import datetime
import hashlib
import logging
import re

import streamlit as st

from services.config import get_settings
from services.excel_exporter import build_excel_report
from services.processor import process_news
from services.word_parser import parse_word_news


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="週新聞彙整系統", page_icon="📰", layout="centered")


def get_week_date(filename):
    date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", filename)
    return "".join(date_match.groups()) if date_match else datetime.now().strftime("%Y%m%d")


def show_processing_summary(summary):
    st.subheader("處理摘要")
    columns = st.columns(3)
    columns[0].metric("新聞總數", summary.total_count)
    columns[1].metric("來源擷取失敗", summary.scrape_failed_count)
    columns[2].metric("分類使用預設標籤", summary.classification_fallback_count)

    if summary.scrape_failed_count:
        st.warning("部分來源網站無法自動擷取，Excel 已保留來源網址與人工確認提示。")
    if summary.classification_fallback_count:
        st.warning("部分新聞無法由 vLLM 完成分類，Excel 已套用預設標籤，請於下載後確認。")


settings = get_settings()

st.title("週新聞彙整系統")
st.write("上傳週新聞 Word 檔案後，系統將擷取來源資訊、執行分類，並產出標準格式 Excel。")

with st.sidebar:
    st.subheader("系統狀態")
    st.success("分類模式：vLLM")
    st.caption(f"vLLM：`{settings.vllm_base_url}`")
    st.caption(f"vLLM 模型：`{settings.vllm_model}`")
    st.caption(
        "模型參數："
        f"`temperature={settings.vllm_temperature}`, "
        f"`max_tokens={settings.vllm_max_tokens}`"
    )

uploaded_file = st.file_uploader("上傳週新聞 Word 檔案", type=["docx"])

if uploaded_file is not None:
    uploaded_file_id = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
    if st.session_state.get("uploaded_file_id") != uploaded_file_id:
        for key in ("report", "output_filename", "summary"):
            st.session_state.pop(key, None)
        st.session_state["uploaded_file_id"] = uploaded_file_id

    week_date = get_week_date(uploaded_file.name)
    output_filename = f"永智週新聞csv_{week_date}.xlsx"

    st.info(f"來源檔案：`{uploaded_file.name}`\n\n預計產出：`{output_filename}`")
    if not re.search(r"\d{4}\.\d{2}\.\d{2}", uploaded_file.name):
        st.warning("檔名未包含 `YYYY.MM.DD` 日期，輸出檔名將使用系統日期。")

    if st.button("開始處理", type="primary"):
        try:
            with st.spinner("正在解析 Word 檔案..."):
                news_list = parse_word_news(uploaded_file)
            if not news_list:
                st.error("無法辨識新聞資料。請確認 Word 檔案包含標題總表、摘要與來源網址。")
                st.stop()

            scrape_progress = st.progress(0, text="準備擷取來源網站")
            classify_progress = st.progress(0, text="等待分類")

            def update_scrape_progress(current, total, news):
                scrape_progress.progress(
                    current / total,
                    text=f"擷取來源網站：{current}/{total} - {news['zh_title'][:24]}",
                )

            def update_classify_progress(current, total, news):
                classify_progress.progress(
                    current / total,
                    text=f"執行新聞分類：{current}/{total} - {news['zh_title'][:24]}",
                )

            summary = process_news(
                news_list,
                settings,
                on_scrape_progress=update_scrape_progress,
                on_classify_progress=update_classify_progress,
            )
            with st.spinner("正在產出 Excel 報告..."):
                report = build_excel_report(news_list, week_date)

            st.session_state["report"] = report.getvalue()
            st.session_state["output_filename"] = output_filename
            st.session_state["summary"] = summary
            st.success("報告已產出。")
        except Exception:
            logger.exception("Weekly news report generation failed")
            st.error("處理失敗。請確認檔案格式與系統設定，或聯絡系統管理者查看服務日誌。")

if "report" in st.session_state:
    show_processing_summary(st.session_state["summary"])
    st.download_button(
        label="下載 Excel 報告",
        data=st.session_state["report"],
        file_name=st.session_state["output_filename"],
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
