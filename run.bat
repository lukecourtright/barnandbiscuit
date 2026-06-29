@echo off
start http://localhost:8000
python -m uvicorn main:app --port 8000 --reload
