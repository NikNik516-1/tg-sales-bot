import asyncio
import json
import os
import urllib.parse
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import redis.asyncio as aioredis
from config import REDIS_HOST, REDIS_PORT, CHROMA_HOST, CHROMA_PORT
import chat_manager
from state import get_all_active_users, get_history, get_state, clear_user, get_user_info

DATA_DIR = Path(__file__).parent / "data" / "knowledge_base"
PROMPTS_DIR = Path(__file__).parent / "data" / "prompts"

_KNOWLEDGE_FILES = [
    ("products",      "Каталог товаров",   "products.txt"),
    ("sales_scripts", "Скрипты продаж",    "sales_scripts.txt"),
    ("users",         "Профили клиентов",  "users.txt"),
]
_ALLOWED_FILENAMES = {fname for _, _, fname in _KNOWLEDGE_FILES}

_PROMPT_FILES = [
    ("sales", "Промпт продавца", "sales_prompt.txt"),
    ("judge", "Промпт судьи",    "judge_prompt.txt"),
]
_ALLOWED_PROMPT_FILENAMES = {fname for _, _, fname in _PROMPT_FILES}

app = FastAPI(title="ПенШоп Админка")
app.mount("/static", StaticFiles(directory="static"), name="static")
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
async def clear_dialog(request: Request, user_id: int):
    await clear_user(user_id)
    return RedirectResponse(url=request.url_for("dashboard"), status_code=303)


@app.get("/groups", response_class=HTMLResponse)
async def groups_page(request: Request):
    r = _redis()
    monitored = await r.smembers("monitored_chats")
    seen_raw = await r.hgetall("seen_chats")
    await r.aclose()
    seen = {k: json.loads(v) for k, v in seen_raw.items()}
    return templates.TemplateResponse(request, "groups.html", {
        "monitored": monitored,
        "seen": seen,
    })


@app.post("/groups/add")
async def add_group(request: Request, chat_id: str = Form(...)):
    await chat_manager.add(chat_id.strip())
    return RedirectResponse(url=request.url_for("groups_page"), status_code=303)


@app.post("/groups/remove")
async def remove_group(request: Request, chat_id: str = Form(...)):
    await chat_manager.remove(chat_id.strip())
    return RedirectResponse(url=request.url_for("groups_page"), status_code=303)


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
async def monitor_channel(request: Request, channel_id: str = Form(...)):
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
    return RedirectResponse(url=request.url_for("channels_page"), status_code=303)


@app.post("/channels/unmonitor")
async def unmonitor_channel(request: Request, channel_id: str = Form(...)):
    r = _redis()
    raw = await r.hget("seen_channels", channel_id)
    await r.aclose()
    if raw:
        info = json.loads(raw)
        linked_group_id = info.get("linked_group_id")
        if linked_group_id:
            await chat_manager.remove(linked_group_id)
    return RedirectResponse(url=request.url_for("channels_page"), status_code=303)


@app.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request, status: str = "", tab: str = "", fragments: int = 0, error: str = ""):
    files = []
    for key, label, filename in _KNOWLEDGE_FILES:
        try:
            content = (DATA_DIR / filename).read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""
        files.append({"key": key, "label": label, "filename": filename, "content": content})
    valid_keys = {f["key"] for f in files}
    active_tab = tab if tab in valid_keys else _KNOWLEDGE_FILES[0][0]
    return templates.TemplateResponse(request, "knowledge.html", {
        "files": files,
        "status": status,
        "active_tab": active_tab,
        "fragments": fragments,
        "error": error,
    })


@app.post("/knowledge/save")
async def knowledge_save(
    request: Request,
    filename: str = Form(...),
    content: str = Form(...),
    tab: str = Form(default=""),
):
    if filename not in _ALLOWED_FILENAMES:
        base = str(request.url_for("knowledge_page"))
        return RedirectResponse(url=f"{base}?status=error&error=Недопустимое+имя+файла", status_code=303)
    path = DATA_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    base = str(request.url_for("knowledge_page"))
    return RedirectResponse(url=f"{base}?status=saved&tab={tab}", status_code=303)


@app.post("/knowledge/reindex")
async def knowledge_reindex(request: Request, tab: str = Form(default="")):
    try:
        fragments = await asyncio.to_thread(_run_ingest)
        base = str(request.url_for("knowledge_page"))
        return RedirectResponse(url=f"{base}?status=reindexed&tab={tab}&fragments={fragments}", status_code=303)
    except Exception as e:
        base = str(request.url_for("knowledge_page"))
        err = urllib.parse.quote(str(e)[:300])
        return RedirectResponse(url=f"{base}?status=error&tab={tab}&error={err}", status_code=303)


@app.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request, status: str = "", tab: str = ""):
    files = []
    for key, label, filename in _PROMPT_FILES:
        try:
            content = (PROMPTS_DIR / filename).read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""
        files.append({"key": key, "label": label, "filename": filename, "content": content})
    valid_keys = {f["key"] for f in files}
    active_tab = tab if tab in valid_keys else _PROMPT_FILES[0][0]
    return templates.TemplateResponse(request, "prompts.html", {
        "files": files,
        "status": status,
        "active_tab": active_tab,
    })


@app.post("/prompts/save")
async def prompts_save(
    request: Request,
    filename: str = Form(...),
    content: str = Form(...),
    tab: str = Form(default=""),
):
    if filename not in _ALLOWED_PROMPT_FILENAMES:
        base = str(request.url_for("prompts_page"))
        return RedirectResponse(url=f"{base}?status=error&tab={tab}", status_code=303)
    path = PROMPTS_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    base = str(request.url_for("prompts_page"))
    return RedirectResponse(url=f"{base}?status=saved&tab={tab}", status_code=303)


@app.get("/seen-users", response_class=HTMLResponse)
async def seen_users_page(request: Request, q: str = ""):
    r = _redis()
    raw = await r.hgetall("seen_users")
    await r.aclose()
    all_users = []
    for user_id, data in raw.items():
        try:
            info = json.loads(data)
        except Exception:
            continue
        all_users.append({"user_id": user_id, **info})
    if q:
        q_lower = q.lower()
        filtered = [
            u for u in all_users
            if q_lower in u.get("username", "").lower()
            or q_lower in u.get("first_name", "").lower()
            or q_lower in u.get("last_name", "").lower()
            or q_lower in u["user_id"]
            or q_lower in u.get("phone", "").lower()
        ]
    else:
        filtered = all_users
    filtered.sort(key=lambda u: u.get("first_seen", ""), reverse=True)
    return templates.TemplateResponse(request, "seen_users.html", {
        "users": filtered, "q": q, "total": len(all_users),
    })


@app.get("/seen-users/export")
async def seen_users_export():
    import csv
    import io
    from fastapi.responses import StreamingResponse
    r = _redis()
    raw = await r.hgetall("seen_users")
    await r.aclose()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "first_name", "last_name", "phone", "chat_id", "chat_title", "first_seen"])
    for user_id in sorted(raw.keys()):
        try:
            info = json.loads(raw[user_id])
        except Exception:
            continue
        writer.writerow([
            user_id,
            info.get("username", ""),
            info.get("first_name", ""),
            info.get("last_name", ""),
            info.get("phone", ""),
            info.get("chat_id", ""),
            info.get("chat_title", ""),
            info.get("first_seen", ""),
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=seen_users.csv"},
    )


def _run_ingest() -> int:
    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    ef = DefaultEmbeddingFunction()
    try:
        client.delete_collection("sales_knowledge")
    except Exception:
        pass
    collection = client.create_collection("sales_knowledge", embedding_function=ef)

    documents, ids = [], []
    max_chunk = 1200
    _SKIP = {"users.txt", "sales_scripts.txt"}
    for path in sorted(DATA_DIR.glob("*.txt")):
        if path.name in _SKIP:
            continue
        content = path.read_text(encoding="utf-8")
        # Split by double newline to keep each item (product/paragraph) intact
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        k = 0
        for para in paragraphs:
            if len(para) <= max_chunk:
                documents.append(para)
                ids.append(f"{path.name}_{k}")
                k += 1
            else:
                for i in range(0, len(para), max_chunk):
                    sub = para[i : i + max_chunk].strip()
                    if sub:
                        documents.append(sub)
                        ids.append(f"{path.name}_{k}")
                        k += 1
    if documents:
        collection.upsert(documents=documents, ids=ids)
    return len(documents)
