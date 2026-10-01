"""
Збирач даних відеотеки НБУ для дітей.

Щоночі запускається на GitHub Actions:
  1. читає реєстр джерел (Google-таблиця на спільному диску «Відеотека»);
  2. для кожного увімкненого джерела збирає відео:
       YouTube-плейлист      → YouTube Data API v3 (ключ у секреті YOUTUBE_API_KEY);
       Медіатека: категорія  → RSS-стрічка категорії (без ключів);
  3. додає презентації з вкладки «Презентації»;
  4. застосовує вкладку «Прив'язки» (область на карті, приховати, інша назва);
  5. записує все в data/videos.json, з якого портал будує сторінки.

Якщо якесь джерело не відповіло, для нього лишаються дані з попереднього запуску,
а помилка записується в поле "errors". Портал від цього не ламається.

Запуск вручну (для перевірки):
  YOUTUBE_API_KEY=... REGISTRY_SHEET_ID=... python scripts/collect.py
Доступ до таблиці: стандартні облікові дані Google (на GitHub їх видає
безключове підключення; локально — `gcloud auth application-default login`).
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "data" / "videos.json"

SHEET_ID = os.environ.get("REGISTRY_SHEET_ID", "")
YT_KEY = os.environ.get("YOUTUBE_API_KEY", "")
MEDIATEKA = "https://mediateka.chl.kiev.ua"
UA = {"User-Agent": "NBUkids-videoteka-collector/1.0 (+https://chl.kiev.ua)"}

# Скільки нових відео Медіатеки розпізнавати за один запуск (кожне = 2 запити до сервера
# бібліотеки). Решта доберуться наступної ночі, щоб не навантажувати сервер.
MEDIATEKA_NEW_PER_RUN = int(os.environ.get("MEDIATEKA_NEW_PER_RUN", "150"))

YES = {"так", "yes", "true", "1", "✓"}

OBLASTS = [
    "Автономна Республіка Крим", "Вінницька область", "Волинська область", "Дніпропетровська область",
    "Донецька область", "Житомирська область", "Закарпатська область", "Запорізька область",
    "Івано-Франківська область", "Київ", "Київська область", "Кіровоградська область",
    "Луганська область", "Львівська область", "Миколаївська область", "Одеська область",
    "Полтавська область", "Рівненська область", "Севастополь", "Сумська область",
    "Тернопільська область", "Харківська область", "Херсонська область", "Хмельницька область",
    "Черкаська область", "Чернівецька область", "Чернігівська область",
]

# Основи слів, за якими область впізнається в назві або описі відео.
# Порядок важливий: довші й специфічніші основи перевіряються раніше.
REGION_STEMS = [
    ("івано-франків", "Івано-Франківська область"), ("прикарпат", "Івано-Франківська область"),
    ("кіровоград", "Кіровоградська область"), ("кропивниц", "Кіровоградська область"),
    ("дніпропетров", "Дніпропетровська область"), ("хмельниц", "Хмельницька область"),
    ("тернопіл", "Тернопільська область"), ("чернігів", "Чернігівська область"),
    ("чернівец", "Чернівецька область"), ("буковин", "Чернівецька область"),
    ("закарпат", "Закарпатська область"), ("ужгород", "Закарпатська область"),
    ("житомир", "Житомирська область"), ("запоріз", "Запорізька область"),
    ("миколаїв", "Миколаївська область"), ("херсон", "Херсонська область"),
    ("вінниц", "Вінницька область"), ("волин", "Волинська область"), ("луцьк", "Волинська область"),
    ("рівнен", "Рівненська область"), ("рівне", "Рівненська область"),
    ("полтав", "Полтавська область"), ("харків", "Харківська область"),
    ("черкас", "Черкаська область"), ("львів", "Львівська область"),
    ("одес", "Одеська область"), ("сум", "Сумська область"),
    ("донеч", "Донецька область"), ("донець", "Донецька область"),
    ("луган", "Луганська область"), ("луганщ", "Луганська область"),
    ("київськ", "Київська область"), ("київщ", "Київська область"),
    ("севастопол", "Севастополь"), ("крим", "Автономна Республіка Крим"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def yes(value) -> bool:
    return str(value or "").strip().lower() in YES


def region_from_text(text: str) -> str | None:
    """Знаходить область у довільному тексті: «Сумська обл.», «Рівненщина», «місто Луцьк»."""
    t = (text or "").lower()
    if not t:
        return None
    for stem, oblast in REGION_STEMS:
        # «сум» надто коротке: вимагаємо «сумськ»/«сумщ», щоб не ловити «сумний»
        if stem == "сум":
            if re.search(r"\bсум(ськ|щ)", t):
                return oblast
            continue
        if stem in t:
            return oblast
    return None


# ───────────────────────── Реєстр ─────────────────────────

def sheets_session():
    """Авторизована сесія для Google Sheets API через стандартні облікові дані Google."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    return AuthorizedSession(creds)


def read_registry(session, sheet_id: str) -> dict[str, list[dict]]:
    """Повертає вкладки реєстру як списки рядків-словників (ключ = назва колонки)."""
    tabs = ["Джерела", "Розділи", "Прив'язки", "Презентації"]
    ranges = "&".join("ranges=" + quote(f"'{t.replace(chr(39), chr(39) * 2)}'!A1:Z") for t in tabs)
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values:batchGet?{ranges}"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    out = {}
    for tab, vr in zip(tabs, r.json().get("valueRanges", [])):
        out[tab] = rows_to_dicts(vr.get("values", []))
    return out


def rows_to_dicts(values: list[list[str]]) -> list[dict]:
    if not values:
        return []
    header = [h.strip() for h in values[0]]
    rows = []
    for raw in values[1:]:
        if not any(str(c).strip() for c in raw):
            continue
        row = {header[i]: (raw[i].strip() if i < len(raw) else "") for i in range(len(header))}
        rows.append(row)
    return rows


def col(row: dict, *prefixes: str) -> str:
    """Значення колонки за початком назви (стійко до «Відео на 01.10.2026» тощо)."""
    for p in prefixes:
        for k, v in row.items():
            if k.lower().startswith(p.lower()):
                return v
    return ""


# ───────────────────────── YouTube ─────────────────────────

def fetch_youtube_playlist(playlist_id: str, key: str, http=requests) -> list[dict]:
    videos, token = [], None
    while True:
        params = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50, "key": key}
        if token:
            params["pageToken"] = token
        r = http.get("https://www.googleapis.com/youtube/v3/playlistItems", params=params, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"YouTube {r.status_code}: {r.text[:200]}")
        data = r.json()
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            vid = it.get("contentDetails", {}).get("videoId") or sn.get("resourceId", {}).get("videoId")
            title = sn.get("title", "")
            if not vid or title in ("Private video", "Deleted video") or not sn.get("thumbnails"):
                continue  # приватні та видалені відео не показуємо
            th = sn["thumbnails"]
            thumb = (th.get("medium") or th.get("high") or th.get("default") or {}).get("url", "")
            videos.append({
                "platform": "youtube",
                "id": vid,
                "title": title,
                "description": (sn.get("description") or "")[:300],
                "thumb": thumb or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                "published": (it.get("contentDetails", {}).get("videoPublishedAt") or sn.get("publishedAt") or "")[:10],
                "url": f"https://youtu.be/{vid}",
            })
        token = data.get("nextPageToken")
        if not token:
            return videos


# ───────────────────────── Медіатека ─────────────────────────

ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
    if not m:
        return ""
    v = m.group(1).strip()
    if v.startswith("<![CDATA["):
        v = v[9:-3]
    return html.unescape(v)


def parse_mediateka_feed(xml: str) -> list[dict]:
    items = []
    for block in ITEM_RE.findall(xml):
        link = _tag(block, "link")
        slug = (re.search(r"[?&]slg=([^&]+)", link) or re.search(r"/video/([^/?#]+)", link) or [None, ""])[1]
        desc_html = _tag(block, "description")
        img = re.search(r'<img[^>]+src="([^"]+)"', desc_html)
        thumb = re.sub(r"(?<!:)//+", "/", img.group(1)) if img else ""
        text = re.sub(r"<[^>]+>", " ", desc_html)
        items.append({
            "platform": "mediateka",
            "id": slug,
            "title": _tag(block, "title"),
            # Опис не зберігаємо: у марафонах там ім'я та вік дитини. Беремо лише область.
            "region_hint": region_from_text(text),
            "thumb": thumb,
            "published": _parse_rfc822(_tag(block, "pubDate")),
            "url": link,
        })
    return items


def _parse_rfc822(s: str) -> str:
    try:
        return datetime.strptime(s.strip(), "%a, %d %b %Y %H:%M:%S %z").date().isoformat()
    except Exception:
        return ""


def fetch_mediateka_category(slug: str, http=requests, max_pages: int = 200) -> list[dict]:
    seen, out = set(), []
    for page in range(max_pages):
        url = f"{MEDIATEKA}/videoteka/{slug}?format=feed&type=rss&limitstart={page * 20}"
        r = http.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        batch = [v for v in parse_mediateka_feed(r.text) if v["id"] and v["id"] not in seen]
        if not batch:
            break
        for v in batch:
            seen.add(v["id"])
            out.append(v)
        time.sleep(0.3)
    return out


def resolve_mediateka_mp4(page_url: str, http=requests) -> str | None:
    """Сторінка відео → номер плеєра → пряма адреса MP4 (для власного плеєра порталу)."""
    r = http.get(page_url, headers=UA, timeout=30)
    r.raise_for_status()
    m = re.search(r"view=player(?:&|&amp;)id=(\d+)", r.text)
    if not m:
        return None
    p = http.get(f"{MEDIATEKA}/index.php?option=com_allvideoshare&view=player&id={m.group(1)}&format=raw",
                 headers=UA, timeout=30)
    p.raise_for_status()
    s = re.search(r'<source[^>]+src="([^"]+\.mp4)"', p.text)
    if not s:
        return None
    src = s.group(1)
    return src if src.startswith("http") else MEDIATEKA + "/" + src.lstrip("/")


# ───────────────────────── Збирання ─────────────────────────

def load_previous() -> dict:
    try:
        return json.loads(OUT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build(registry: dict, yt_key: str, previous: dict, http=requests) -> dict:
    errors: list[str] = []
    prev_by_source: dict[str, list[dict]] = {}
    prev_mp4: dict[str, str] = {}
    for v in previous.get("videos", []):
        prev_by_source.setdefault(v.get("source_id", ""), []).append(v)
        if v.get("platform") == "mediateka" and v.get("mp4"):
            prev_mp4[v["id"]] = v["mp4"]

    # Розділи
    sections = []
    for r in registry.get("Розділи", []):
        if not yes(col(r, "Показувати")):
            continue
        try:
            order = float(col(r, "Порядок") or 99)
        except ValueError:
            order = 99
        sections.append({"name": col(r, "Розділ"), "icon": col(r, "Іконка"), "color": col(r, "Колір"),
                         "order": order, "description": col(r, "Опис")})
    sections.sort(key=lambda s: s["order"])
    active_sections = {s["name"] for s in sections}

    # Прив'язки: ідентифікатор відео → уточнення
    overrides = {}
    for r in registry.get("Прив'язки", []):
        vid = col(r, "Ідентифікатор")
        if vid:
            overrides[vid] = {"region": col(r, "Область") or None, "hide": yes(col(r, "Приховати")),
                              "title": col(r, "Назва замість")}

    sources, videos = [], []
    new_mp4_budget = MEDIATEKA_NEW_PER_RUN
    for r in registry.get("Джерела", []):
        if not yes(col(r, "Показувати")):
            continue
        typ, sid = col(r, "Тип джерела"), col(r, "Ідентифікатор")
        section, title, map_mode = col(r, "Розділ"), col(r, "Назва на порталі"), col(r, "Карта").lower()
        if not sid or section not in active_sections:
            if sid and section not in active_sections:
                errors.append(f"«{title}»: розділ «{section}» вимкнено або не існує на вкладці «Розділи»")
            continue
        src = {"id": sid, "title": title, "section": section, "type": typ, "map": map_mode, "ok": True}
        try:
            if typ.startswith("YouTube"):
                if not yt_key:
                    raise RuntimeError("немає ключа YOUTUBE_API_KEY")
                items = fetch_youtube_playlist(sid, yt_key, http)
            elif typ.startswith("Медіатека"):
                items = fetch_mediateka_category(sid, http)
                for v in items:
                    if v["id"] in prev_mp4:
                        v["mp4"] = prev_mp4[v["id"]]
                    elif new_mp4_budget > 0:
                        new_mp4_budget -= 1
                        try:
                            v["mp4"] = resolve_mediateka_mp4(v["url"], http)
                        except Exception:
                            v["mp4"] = None
                        time.sleep(0.3)
            elif typ.startswith("Google Drive"):
                sources.append(src)   # презентації описані окремою вкладкою
                continue
            else:
                raise RuntimeError(f"невідомий тип джерела «{typ}»")
        except Exception as e:  # джерело не відповіло: беремо минулі дані
            src["ok"] = False
            src["error"] = str(e)[:300]
            errors.append(f"«{title}»: {src['error']}")
            items = [dict(v) for v in prev_by_source.get(sid, [])]

        for v in items:
            v["source_id"], v["section"] = sid, section
            if not src["ok"]:
                v.setdefault("region", None)      # минулі дані: область уже визначена тоді
            else:
                if "вручну" in map_mode:
                    v["region"] = None
                elif "назв" in map_mode:
                    v["region"] = region_from_text(v["title"])
                elif "опис" in map_mode:
                    v["region"] = v.get("region_hint") or region_from_text(v.get("description", ""))
                else:
                    v["region"] = None
            v.pop("region_hint", None)
            o = overrides.get(v["id"])
            if o:
                if o["hide"]:
                    continue
                if o["region"]:
                    v["region"] = o["region"]
                if o["title"]:
                    v["title"] = o["title"]
            videos.append(v)
        src["count"] = len(items)
        sources.append(src)

    presentations = []
    for r in registry.get("Презентації", []):
        fid = col(r, "Ідентифікатор")
        if fid and yes(col(r, "Показувати") or "так"):
            presentations.append({"title": col(r, "Назва"), "file_id": fid, "region": col(r, "Область") or None,
                                  "preview": f"https://docs.google.com/presentation/d/{fid}/preview"})

    unknown = sorted({v["region"] for v in videos if v.get("region") and v["region"] not in OBLASTS})
    if unknown:
        errors.append("невідомі назви областей у «Прив'язках»: " + ", ".join(unknown))

    return {"generated_at": now_iso(), "sections": sections, "sources": sources,
            "videos": videos, "presentations": presentations, "errors": errors}


def write_summary(data: dict) -> None:
    """Короткий звіт у підсумку запуску GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = [f"### Відеотека: {len(data['videos'])} відео, {len(data['presentations'])} презентацій", ""]
    for s in data["sources"]:
        mark = "✅" if s.get("ok") else "⚠️"
        lines.append(f"- {mark} {s['title']}: {s.get('count', '—')}" + (f" — {s['error']}" if s.get("error") else ""))
    if data["errors"]:
        lines += ["", "**Потребує уваги:**"] + [f"- {e}" for e in data["errors"]]
    text = "\n".join(lines)
    print(text)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main() -> int:
    if not SHEET_ID:
        print("Не задано REGISTRY_SHEET_ID", file=sys.stderr)
        return 2
    registry = read_registry(sheets_session(), SHEET_ID)   # без реєстру працювати немає сенсу
    previous = load_previous()
    data = build(registry, YT_KEY, previous)
    same = {k: v for k, v in data.items() if k != "generated_at"} == \
           {k: v for k, v in previous.items() if k != "generated_at"}
    if not same:   # без змін файл не переписуємо, щоб не було порожніх щонічних комітів
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_summary(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
