import json
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import redis.asyncio as aioredis
from config import REDIS_HOST, REDIS_PORT
import chat_manager
from state import get_all_active_users, get_history, get_state, clear_user

app = FastAPI(title="ПенШоп Админка")
templates = Jinja2Templates(directory="templates")


def _redis():
    return aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    users = await get_all_active_users()
    dialogs = []
    for u in users:
        history = await get_history(int(u["user_id"]))
        last = history[-1]["content"][:100] if history else ""
        dialogs.append({
            "user_id": u["user_id"],
            "state": u["state"],
            "last_msg": last,
            "msg_count": len(history),
        })
    dialogs.sort(key=lambda d: d["state"])
    return templates.TemplateResponse("index.html", {"request": request, "dialogs": dialogs})


@app.get("/history/{user_id}", response_class=HTMLResponse)
async def view_history(request: Request, user_id: int):
    history = await get_history(user_id)
    state = await get_state(user_id)
    return templates.TemplateResponse("history.html", {
        "request": request,
        "user_id": user_id,
        "state": state,
        "history": history,
    })


@app.post("/clear/{user_id}")
async def clear_dialog(user_id: int):
    await clear_user(user_id)
    return RedirectResponse("/", status_code=303)


@app.get("/groups", response_class=HTMLResponse)
async def groups_page(request: Request):
    monitored = chat_manager.get()
    r = _redis()
    seen_raw = await r.hgetall("seen_chats")
    await r.aclose()
    seen = {k: json.loads(v) for k, v in seen_raw.items()}
    return templates.TemplateResponse("groups.html", {
        "request": request,
        "monitored": monitored,
        "seen": seen,
    })


@app.post("/groups/add")
async def add_group(chat_id: str = Form(...)):
    await chat_manager.add(chat_id.strip())
    return RedirectResponse("/groups", status_code=303)


@app.post("/groups/remove")
async def remove_group(chat_id: str = Form(...)):
    await chat_manager.remove(chat_id.strip())
    return RedirectResponse("/groups", status_code=303)
