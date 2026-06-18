import io
import unittest

from docx import Document

from services.word_parser import parse_word_news


class WordParserTests(unittest.TestCase):
    def test_parse_word_news_reads_table_title_content_and_source(self):
        document = Document()
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "項次"
        table.cell(0, 1).text = "標題"
        table.cell(1, 0).text = "1"
        table.cell(1, 1).text = "歐盟宣布碳市場新措施"
        document.add_paragraph("歐盟宣布碳市場新措施")
        document.add_paragraph("這是一段新聞摘要。")
        document.add_paragraph("出處：https://www.example.com/news/1")
        buffer = io.BytesIO()
        document.save(buffer)
        buffer.seek(0)

        news_list = parse_word_news(buffer)

        self.assertEqual(len(news_list), 1)
        self.assertEqual(news_list[0]["zh_title"], "歐盟宣布碳市場新措施")
        self.assertEqual(news_list[0]["content"], "這是一段新聞摘要。")
        self.assertEqual(news_list[0]["source_url"], "https://www.example.com/news/1")


if __name__ == "__main__":
    unittest.main()

