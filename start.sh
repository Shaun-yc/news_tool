#!/bin/sh
set -e

uvicorn api:app --host 0.0.0.0 --port 8001 --no-access-log &
exec streamlit run app.py
