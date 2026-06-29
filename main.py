import json
import pathlib

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

RINKS_FILE = pathlib.Path("rinks.json")
PENDING_FILE = pathlib.Path("pending_rinks.json")


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/api/rinks")
def get_rinks():
    return json.loads(RINKS_FILE.read_text(encoding="utf-8"))


@app.post("/api/rinks/submit")
async def submit_rink(request: Request):
    rink = await request.json()
    data = json.loads(PENDING_FILE.read_text(encoding="utf-8")) if PENDING_FILE.exists() else []
    data.append(rink)
    PENDING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"status": "received"}


app.mount("/static", StaticFiles(directory="static"), name="static")
