import json
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import redis.asyncio as aioredis
from config import REDIS_HOST, REDIS_PORT
import chat_manager
from state import get_all_active_users, get_history, get_state, clear_user, get_user_info

app = FastAPI(title="ПенШоп Админка")
templates = Jinja2Templates(directory="templates")

_tg_client = None


def set_tg_client(client) -> None:
    global _tg_client
    _tg_client = client


def _redis():
    return aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    users = await get_all_active_users()
    dialogs = []
    for u in users:
        history = await get_history(int(u["user_id"]))
        user_info = await get_user_info(int(u["user_id"]))
        last_entry = history[-1] if history else {}
        last_msg = last_entry.get("content", "")[:100]
        raw_ts = last_entry.get("ts", "")
        if raw_ts:
            last_ts = raw_ts[8:10] + "." + raw_ts[5:7] + " " + raw_ts[11:16]
        else:
            last_ts = ""
        first = user_info.get("first_name", "")
        last = user_info.get("last_name", "")
        display_name = (first + " " + last).strip()
        dialogs.append({
            "user_id": u["user_id"],
            "state": u["state"],
            "last_msg": last_msg,
            "last_ts": last_ts,
            "msg_count": len(history),
            "username": user_info.get("username", ""),
            "display_name": display_name,
        })
    dialogs.sort(key=lambda d: d["state"])
    return templates.TemplateResponse(request, "index.html", {"dialogs": dialogs})


@app.get("/history/{user_id}", response_class=HTMLResponse)
async def view_history(request: Request, user_id: int):
    history = await get_history(user_id)
    state = await get_state(user_id)
    return templates.TemplateResponse(request, "history.html", {
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
    return templates.TemplateResponse(request, "groups.html", {
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


@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request):
    r = _redis()
    seen_raw = await r.hgetall("seen_channels")
    await r.aclose()

    monitored = chat_manager.get()
    channels = []
    for channel_id, raw in seen_raw.items():
        info = json.loads(raw)
        linked = info.get("linked_group_id")
        channels.append({
            "channel_id": channel_id,
            "title": info.get("title", ""),
            "username": info.get("username", ""),
            "linked_group_id": linked,
            "first_seen": info.get("first_seen", ""),
            "is_monitored": linked in monitored if linked else False,
        })
    channels.sort(key=lambda c: c["title"].lower())
    return templates.TemplateResponse(request, "channels.html", {"channels": channels})


@app.post("/channels/monitor")
async def monitor_channel(channel_id: str = Form(...)):
    r = _redis()
    raw = await r.hget("seen_channels", channel_id)
    await r.aclose()

    info = json.loads(raw) if raw else {}
    linked_group_id = info.get("linked_group_id")

    if not linked_group_id and _tg_client:
        try:
            chat = await _tg_client.get_chat(int(channel_id))
            if chat.linked_chat:
                linked_group_id = str(chat.linked_chat.id)
                info["linked_group_id"] = linked_group_id
                r = _redis()
                await r.hset("seen_channels", channel_id, json.dumps(info, ensure_ascii=False))
                await r.aclose()
        except Exception as e:
            print(f"[CHANNELS] Ошибка get_chat {channel_id}: {e}")

    if linked_group_id:
        await chat_manager.add(linked_group_id)
    return RedirectResponse("/channels", status_code=303)


@app.post("/channels/unmonitor")
async def unmonitor_channel(channel_id: str = Form(...)):
    r = _redis()
    raw = await r.hget("seen_channels", channel_id)
    await r.aclose()
    if raw:
        info = json.loads(raw)
        linked_group_id = info.get("linked_group_id")
        if linked_group_id:
            await chat_manager.remove(linked_group_id)
    return RedirectResponse("/channels", status_code=303)
