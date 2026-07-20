FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt
RUN PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 python -m playwright install --with-deps chromium

COPY . .
RUN sed -i 's/\r$//' /app/start.sh \
    && chmod +x /app/start.sh

EXPOSE 8501 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)"

CMD ["/app/start.sh"]
