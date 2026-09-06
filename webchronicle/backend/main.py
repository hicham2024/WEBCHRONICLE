from __future__ import annotations

import hashlib
import os
import html
import ipaddress
import json
import re
import socket
import sqlite3
import string
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel
from playwright.async_api import async_playwright

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
SNAPS = DATA / "snapshots"
SHOTS = DATA / "screenshots"
DB = DATA / "webchronicle.db"
for p in (DATA, SNAPS, SHOTS):
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="WebChronicle API")

def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]

CORS_ORIGINS = env_list(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            original_url TEXT NOT NULL,
            title TEXT,
            archived_at TEXT NOT NULL,
            status_code INTEGER,
            content_hash TEXT,
            html_path TEXT,
            screenshot_path TEXT,
            readable_text TEXT,
            source TEXT DEFAULT 'capture'
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_url ON snapshots(original_url);
        CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(archived_at DESC);
        """)

init_db()

class ArchiveRequest(BaseModel):
    url: str


def short_code(n=5):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(n))


def unique_code():
    while True:
        code = short_code()
        with db() as c:
            if not c.execute("SELECT 1 FROM snapshots WHERE code=?", (code,)).fetchone():
                return code


def validate_public_url(raw: str) -> str:
    raw = raw.strip()
    u = urlparse(raw)
    if u.scheme not in {"http", "https"} or not u.hostname:
        raise HTTPException(400, "URL HTTP(S) valide requise")
    host = u.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise HTTPException(400, "Hôte local interdit")
    try:
        for fam, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise HTTPException(400, "Adresse réseau privée/interne interdite")
    except socket.gaierror:
        raise HTTPException(400, "Nom d'hôte introuvable")
    return raw


def readable_from_html(raw_html: str):
    soup = BeautifulSoup(raw_html, "lxml")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "Sans titre")
    for tag in soup(["script", "style", "noscript", "svg", "canvas"]):
        tag.decompose()
    candidates = soup.find_all(["article", "main"])
    root = candidates[0] if candidates else soup.body or soup
    text = "\n".join(line.strip() for line in root.get_text("\n").splitlines() if line.strip())
    return title, text[:500000]


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/archive")
async def archive_page(req: ArchiveRequest):
    url = validate_public_url(req.url)
    code = unique_code()
    archived_at = datetime.now(timezone.utc).isoformat()
    html_path = SNAPS / f"{code}.html"
    screenshot_path = SHOTS / f"{code}.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent="WebChronicle/1.0 (+public-web-archive)"
        )
        page = await context.new_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response else None
            await page.wait_for_timeout(1500)
            final_url = page.url
            validate_public_url(final_url)
            raw_html = await page.content()
            await page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception as e:
            await browser.close()
            raise HTTPException(502, f"Capture impossible: {type(e).__name__}")
        await browser.close()

    title, readable = readable_from_html(raw_html)
    digest = hashlib.sha256(raw_html.encode("utf-8", errors="ignore")).hexdigest()
    banner = f'''<!-- Archived by WebChronicle at {html.escape(archived_at)} from {html.escape(final_url)} -->\n'''
    html_path.write_text(banner + raw_html, encoding="utf-8")

    with db() as c:
        c.execute("""INSERT INTO snapshots
        (code, original_url, title, archived_at, status_code, content_hash, html_path, screenshot_path, readable_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (code, final_url, title, archived_at, status, digest, str(html_path), str(screenshot_path), readable))

    return {"code": code, "title": title, "url": final_url, "archived_at": archived_at, "status_code": status}


@app.get("/api/snapshot/{code}")
def snapshot_meta(code: str):
    with db() as c:
        row = c.execute("SELECT * FROM snapshots WHERE code=?", (code,)).fetchone()
    if not row:
        raise HTTPException(404, "Snapshot introuvable")
    return dict(row)


@app.get("/s/{code}", response_class=HTMLResponse)
def snapshot_page(code: str):
    with db() as c:
        row = c.execute("SELECT * FROM snapshots WHERE code=?", (code,)).fetchone()
    if not row or not row["html_path"] or not Path(row["html_path"]).exists():
        raise HTTPException(404, "Snapshot HTML introuvable")
    return HTMLResponse(Path(row["html_path"]).read_text(encoding="utf-8"))


@app.get("/shot/{code}")
def screenshot(code: str):
    with db() as c:
        row = c.execute("SELECT screenshot_path FROM snapshots WHERE code=?", (code,)).fetchone()
    if not row or not row["screenshot_path"] or not Path(row["screenshot_path"]).exists():
        raise HTTPException(404, "Capture d'écran introuvable")
    return FileResponse(row["screenshot_path"], media_type="image/png")


@app.get("/api/recent")
def recent(limit: int = 30):
    limit = max(1, min(limit, 100))
    with db() as c:
        rows = c.execute("SELECT code,title,original_url,archived_at,status_code,source FROM snapshots ORDER BY archived_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/history")
def history(url: str):
    with db() as c:
        rows = c.execute("SELECT code,title,original_url,archived_at,status_code FROM snapshots WHERE original_url=? ORDER BY archived_at DESC", (url,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/search")
def search(q: str, limit: int = 50):
    q = q.strip()
    if not q:
        return []
    like = f"%{q}%"
    with db() as c:
        rows = c.execute("""SELECT code,title,original_url,archived_at,status_code
            FROM snapshots
            WHERE title LIKE ? OR original_url LIKE ? OR readable_text LIKE ?
            ORDER BY archived_at DESC LIMIT ?""", (like, like, like, min(limit, 100))).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/read/{code}")
def read_mode(code: str):
    with db() as c:
        row = c.execute("SELECT code,title,original_url,archived_at,readable_text FROM snapshots WHERE code=?", (code,)).fetchone()
    if not row:
        raise HTTPException(404, "Snapshot introuvable")
    return dict(row)


@app.get("/rss")
def rss():
    with db() as c:
        rows = c.execute("SELECT code,title,original_url,archived_at FROM snapshots ORDER BY archived_at DESC LIMIT 50").fetchall()
    items = []
    for r in rows:
        items.append(f"""<item><title>{html.escape(r['title'] or '')}</title><link>{PUBLIC_BASE_URL}/s/{r['code']}</link><guid>{PUBLIC_BASE_URL}/s/{r['code']}</guid><pubDate>{html.escape(r['archived_at'])}</pubDate><description><![CDATA[archived from <a href=\"{html.escape(r['original_url'])}\">{html.escape(r['original_url'])}</a>]]></description></item>""")
    body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss version=\"2.0\"><channel><title>WebChronicle</title><link>{html.escape(FRONTEND_URL)}</link><description>web preservation, page snapshot, screenshot, link rot</description>" + ''.join(items) + "</channel></rss>"
    return Response(body, media_type="application/rss+xml")


@app.post("/api/import-rss")
async def import_rss(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        root = ET.fromstring(raw)
    except Exception:
        raise HTTPException(400, "RSS/XML invalide")
    count = 0
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or datetime.now(timezone.utc).isoformat()).strip()
        desc = item.findtext("description") or ""
        m = re.search(r'archived[^<]*from\s*<a[^>]+href="([^"]+)"', desc, flags=re.I)
        original = html.unescape(m.group(1)) if m else link
        code = unique_code()
        with db() as c:
            c.execute("INSERT INTO snapshots (code, original_url, title, archived_at, source) VALUES (?, ?, ?, ?, 'rss-import')", (code, original, title, pub))
        count += 1
    return {"imported": count}
