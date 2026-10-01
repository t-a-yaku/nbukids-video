"""
Будує статичний сайт відеотеки з data/videos.json.

Кожен розділ, серія, область і кожне відео отримують власну сторінку з описом
і розміткою для пошукових систем; додаються карта сайту і robots.txt.
Усі внутрішні посилання відносні, тому той самий набір файлів працює
і на піддомені (video.chl.kiev.ua), і в папці (chl.kiev.ua/videoteka/).

Налаштування (змінні середовища):
  SITE_URL    повна адреса, де лежатиме сайт, зі скісною в кінці
              (за замовчуванням https://t-a-yaku.github.io/nbukids-video/)
  SITE_INDEX  «так» — дозволити пошуковикам індексувати сайт;
              будь-що інше — демоверсія: сторінки закриті від індексу і
              вгорі показано смужку «Демонстраційна версія».
  SITE_OUT    куди складати готові файли (за замовчуванням _site)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site_src"
DATA_FILE = ROOT / "data" / "videos.json"
MAP_FILE = ROOT / "_ukraine_map.html"
LEGACY_PAGES = ["nbukids_hub.html"]          # старі адреси, які вже могли поширити

SITE_URL = os.environ.get("SITE_URL", "https://t-a-yaku.github.io/nbukids-video/").strip()
if not SITE_URL.endswith("/"):
    SITE_URL += "/"
INDEXABLE = os.environ.get("SITE_INDEX", "ні").strip().lower() in {"так", "yes", "true", "1"}
OUT = Path(os.environ.get("SITE_OUT", ROOT / "_site"))

SITE_NAME = "Відеотека НБУ для дітей"
LIBRARY = "Національна бібліотека України для дітей"
LIBRARY_URL = "https://chl.kiev.ua/"
CHANNEL_URL = "https://www.youtube.com/@nbukids"

# 27 регіонів у кордонах України 1991 року; slug збігається з data-region на карті.
REGIONS = [
    ("Автономна Республіка Крим", "krym", "АР Крим"),
    ("Вінницька область", "vinnytska", "Вінницька"),
    ("Волинська область", "volynska", "Волинська"),
    ("Дніпропетровська область", "dnipropetrovska", "Дніпропетровська"),
    ("Донецька область", "donetska", "Донецька"),
    ("Житомирська область", "zhytomyrska", "Житомирська"),
    ("Закарпатська область", "zakarpatska", "Закарпатська"),
    ("Запорізька область", "zaporizka", "Запорізька"),
    ("Івано-Франківська область", "ivano-frankivska", "Івано-Франківська"),
    ("Київ", "kyiv", "Київ"),
    ("Київська область", "kyivska", "Київська"),
    ("Кіровоградська область", "kirovohradska", "Кіровоградська"),
    ("Луганська область", "luhanska", "Луганська"),
    ("Львівська область", "lvivska", "Львівська"),
    ("Миколаївська область", "mykolaivska", "Миколаївська"),
    ("Одеська область", "odeska", "Одеська"),
    ("Полтавська область", "poltavska", "Полтавська"),
    ("Рівненська область", "rivnenska", "Рівненська"),
    ("Севастополь", "sevastopol", "Севастополь"),
    ("Сумська область", "sumska", "Сумська"),
    ("Тернопільська область", "ternopilska", "Тернопільська"),
    ("Харківська область", "kharkivska", "Харківська"),
    ("Херсонська область", "khersonska", "Херсонська"),
    ("Хмельницька область", "khmelnytska", "Хмельницька"),
    ("Черкаська область", "cherkaska", "Черкаська"),
    ("Чернівецька область", "chernivetska", "Чернівецька"),
    ("Чернігівська область", "chernihivska", "Чернігівська"),
]

MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня",
          "серпня", "вересня", "жовтня", "листопада", "грудня"]

# Офіційна транслітерація (постанова КМУ № 55 від 27.01.2010)
_TR = {"а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh",
       "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
       "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
       "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "'": "", "’": "", "ʼ": ""}
_TR_START = {"є": "ye", "ї": "yi", "й": "y", "ю": "yu", "я": "ya"}


def slugify(text: str) -> str:
    out = []
    for word in re.split(r"[^\w'’ʼ]+", text.lower()):
        word = word.replace("зг", "zgh")
        w = "".join(_TR_START.get(ch, _TR.get(ch, ch)) if i == 0 else _TR.get(ch, ch)
                    for i, ch in enumerate(word))
        w = re.sub(r"[^a-z0-9]+", "", w)
        if w:
            out.append(w)
    return "-".join(out)[:60].strip("-") or "rozdil"


def human_date(iso: str) -> str:
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def videos_word(n: int) -> str:
    return plural(n, "відео", "відео", "відео")


def short_text(text: str, limit: int = 155) -> str:
    text = re.sub(r"https?://\S+|#\S+", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:—-")
    return cut + "…"


def jsonld(obj) -> Markup:
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return Markup(s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


# ───────────────────────── дані ─────────────────────────

def load_map_paths() -> list[dict]:
    """Контури областей з _ukraine_map.html; Київ і Севастополь малюються останніми (поверх сусідів)."""
    html = MAP_FILE.read_text(encoding="utf-8")
    paths = [{"slug": m.group(1), "d": m.group(2)}
             for m in re.finditer(r'<path data-region="([a-z-]+)"[^>]*?\sd="([^"]+)"', html)]
    small = {"kyiv", "sevastopol"}
    paths.sort(key=lambda p: p["slug"] in small)
    found = {p["slug"] for p in paths}
    missing = [slug for _, slug, _ in REGIONS if slug not in found]
    if missing:
        raise SystemExit(f"На карті бракує регіонів: {', '.join(missing)}")
    return paths


def prepare(data: dict) -> dict:
    sources = {s["id"]: s for s in data.get("sources", [])}
    regions = OrderedDict()
    for name, slug, label in REGIONS:
        regions[name] = {"name": name, "slug": slug, "label": label, "url": f"oblast/{slug}/",
                         "videos": [], "presentations": []}

    sections = OrderedDict()
    used_slugs = set()
    for s in data.get("sections", []):
        slug = slugify(s["name"])
        while slug in used_slugs:
            slug += "-2"
        used_slugs.add(slug)
        sections[s["name"]] = {**s, "slug": slug, "url": f"rozdil/{slug}/", "series": OrderedDict(),
                               "videos": [], "presentations": []}

    videos = OrderedDict()                 # одне відео — одна сторінка, навіть якщо воно в кількох серіях
    lower_ids = {}
    for raw in data.get("videos", []):
        sec = sections.get(raw.get("section"))
        if not sec:
            continue
        src = sources.get(raw.get("source_id"), {})
        series_title = src.get("title") or sec["name"]
        series = sec["series"].get(series_title)
        if series is None:
            sslug = slugify(series_title)
            if sslug == sec["slug"] or any(x["slug"] == sslug for x in sec["series"].values()):
                sslug += "-seriia"
            series = sec["series"][series_title] = {"title": series_title, "slug": sslug,
                                                    "url": f"{sec['url']}{sslug}/", "videos": [],
                                                    "section": sec}
        key = ("m-" if raw.get("platform") == "mediateka" else "") + raw["id"]
        v = videos.get(key)
        if v is None:
            if key.lower() in lower_ids:   # на серверах Windows регістр літер в адресі не розрізняється
                key = key + "-2"
            lower_ids[key.lower()] = key
            v = videos[key] = {**raw, "key": key, "url": f"video/{key}/", "section_obj": sec,
                               "series_list": [], "date_h": human_date(raw.get("published", ""))}
            sec["videos"].append(v)
            reg = regions.get(raw.get("region") or "")
            v["region_obj"] = reg
            if reg:
                reg["videos"].append(v)
        if series not in v["series_list"]:
            v["series_list"].append(series)
            series["videos"].append(v)

    for v in videos.values():
        v["series"] = v["series_list"][0]
        if v.get("platform") == "mediateka":
            v["embed"] = None
            v["watch_url"] = v.get("url")
        else:
            v["embed"] = f"https://www.youtube-nocookie.com/embed/{v['id']}?rel=0"
            v["watch_url"] = f"https://www.youtube.com/watch?v={v['id']}"
            v["thumb_big"] = f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg"
        v.setdefault("thumb_big", v.get("thumb"))
        v["desc_short"] = short_text(v.get("description", ""))

    geo_section = None
    for p in data.get("presentations", []):
        reg = regions.get(p.get("region") or "")
        p = {**p, "region_obj": reg}
        if reg:
            reg["presentations"].append(p)
        for s in data.get("sources", []):
            if s.get("type", "").startswith("Google Drive") and s.get("section") in sections:
                geo_section = sections[s["section"]]
                break
        if geo_section is not None:
            geo_section["presentations"].append(p)
    # розділ з картою — той, у якого є прив'язки до областей
    map_section = geo_section
    if map_section is None:
        counts = Counter(v["section"] for v in videos.values() if v.get("region_obj"))
        if counts:
            map_section = sections[counts.most_common(1)[0][0]]

    for reg in regions.values():
        reg["count"] = len(reg["videos"]) + len(reg["presentations"])
    return {"sections": sections, "videos": videos, "regions": regions, "map_section": map_section,
            "generated_at": data.get("generated_at", "")}


# ───────────────────────── сторінки ─────────────────────────

class Site:
    def __init__(self, model: dict, map_paths: list[dict]):
        self.m = model
        self.map_paths = map_paths
        self.pages: list[tuple[str, str]] = []   # (шлях, дата для sitemap)
        self.env = Environment(loader=FileSystemLoader(SRC / "templates"),
                               autoescape=select_autoescape(["html", "xml"]),
                               trim_blocks=True, lstrip_blocks=True)
        self.env.filters["plural"] = lambda n, a, b, c: plural(n, a, b, c)
        self.env.filters["tojson_ld"] = jsonld
        gen = model["generated_at"][:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.today = gen
        self.common = {
            "site_name": SITE_NAME, "library": LIBRARY, "library_url": LIBRARY_URL,
            "channel_url": CHANNEL_URL, "indexable": INDEXABLE, "site_url": SITE_URL,
            "sections": list(model["sections"].values()), "regions": list(model["regions"].values()),
            "map_section": model["map_section"], "updated_h": human_date(gen),
            "total_videos": len(model["videos"]), "map_paths": map_paths,
        }

    def abs(self, path: str) -> str:
        return SITE_URL + path

    def render(self, template: str, path: str, *, sitemap: bool = True, lastmod: str | None = None,
               root: str | None = None, **ctx):
        depth = path.count("/")
        ctx = {**self.common, **ctx, "path": path, "canonical": self.abs(path),
               "root": root if root is not None else "../" * depth}
        ctx.setdefault("robots_index", True)
        ctx.setdefault("active", ctx.get("sec") or (ctx.get("v") or {}).get("section_obj"))
        html = self.env.get_template(template).render(**ctx)
        html = re.sub(r"\n\s*\n+", "\n", html)
        target = OUT / (path + "index.html" if path.endswith("/") or path == "" else path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        if sitemap and INDEXABLE and ctx["robots_index"]:
            self.pages.append((path, lastmod or self.today))

    def crumbs(self, *items) -> list[dict]:
        out = [{"title": "Бібліотека", "url": LIBRARY_URL, "abs": LIBRARY_URL},
               {"title": "Відеотека", "url": "", "abs": SITE_URL}]
        for title, url in items:
            out.append({"title": title, "url": url, "abs": self.abs(url) if url is not None else None})
        return out

    @staticmethod
    def crumbs_ld(crumbs: list[dict]) -> dict:
        return {"@context": "https://schema.org", "@type": "BreadcrumbList",
                "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": c["title"],
                                     **({"item": c["abs"]} if c.get("abs") else {})}
                                    for i, c in enumerate(crumbs)]}

    def item_list_ld(self, name: str, url: str, videos: list[dict]) -> dict:
        return {"@context": "https://schema.org", "@type": "CollectionPage", "name": name,
                "url": self.abs(url), "inLanguage": "uk",
                "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": SITE_URL},
                "mainEntity": {"@type": "ItemList", "numberOfItems": len(videos),
                               "itemListElement": [{"@type": "ListItem", "position": i + 1,
                                                    "url": self.abs(v["url"]), "name": v["title"]}
                                                   for i, v in enumerate(videos)]}}

    def video_ld(self, v: dict) -> dict:
        ld = {"@context": "https://schema.org", "@type": "VideoObject", "name": v["title"],
              "description": short_text(v.get("description", ""), 500) or
              f"Відео з серії «{v['series']['title']}» — {LIBRARY}.",
              "thumbnailUrl": [v["thumb_big"]] if v.get("thumb_big") else [],
              "inLanguage": "uk", "isFamilyFriendly": True, "url": self.abs(v["url"]),
              "publisher": {"@type": "Organization", "name": LIBRARY, "url": LIBRARY_URL}}
        if v.get("published"):
            ld["uploadDate"] = v["published"]
        if v.get("embed"):
            ld["embedUrl"] = f"https://www.youtube.com/embed/{v['id']}"
        if v.get("mp4"):
            ld["contentUrl"] = v["mp4"]
        if v.get("region_obj"):
            ld["contentLocation"] = {"@type": "Place", "name": v["region_obj"]["name"] + ", Україна"}
        return ld

    # ─── окремі сторінки ───

    def build(self):
        m = self.m
        sections = list(m["sections"].values())
        all_videos = list(m["videos"].values())
        latest = sorted(all_videos, key=lambda v: v.get("published", ""), reverse=True)[:8]

        website_ld = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME,
                      "url": SITE_URL, "inLanguage": "uk",
                      "publisher": {"@type": "Organization", "name": LIBRARY, "url": LIBRARY_URL},
                      "potentialAction": {"@type": "SearchAction",
                                          "target": SITE_URL + "poshuk/?q={search_term_string}",
                                          "query-input": "required name=search_term_string"}}
        self.render("home.html", "", title=f"Відеотека для дітей: казки, подорожі Україною, професії | {LIBRARY}",
                    description=f"{videos_word(len(all_videos)).capitalize()} Національної бібліотеки України для дітей в одному місці: "
                                "казки на ніч, віртуальні подорожі областями України, розповіді про професії. "
                                "Пошук за темою, серією й областю на карті.",
                    ld=[website_ld], latest=latest, map=self.map_ctx(), home=True)

        for sec in sections:
            series = list(sec["series"].values())
            crumbs = self.crumbs((sec["name"], None))
            single = len(series) <= 1
            is_map = sec is m["map_section"]
            self.render("section.html", sec["url"], title=f"{sec['name']} — відео для дітей | {SITE_NAME}",
                        description=short_text(f"{sec['name']}: {sec.get('description') or ''}. "
                                               f"{videos_word(len(sec['videos'])).capitalize()} від {LIBRARY}."),
                        sec=sec, series=series, single=single, crumbs=crumbs,
                        map=self.map_ctx() if is_map else None,
                        ld=[self.crumbs_ld(crumbs), self.item_list_ld(sec["name"], sec["url"], sec["videos"])])
            if not single:
                for se in series:
                    c = self.crumbs((sec["name"], sec["url"]), (se["title"], None))
                    self.render("series.html", se["url"], title=f"{se['title']} — {sec['name']} | {SITE_NAME}",
                                description=short_text(f"Усі {videos_word(len(se['videos']))} серії «{se['title']}» "
                                                       f"({sec['name'].lower()}) від {LIBRARY}."),
                                sec=sec, se=se, crumbs=c,
                                ld=[self.crumbs_ld(c), self.item_list_ld(se["title"], se["url"], se["videos"])])

        regions = list(m["regions"].values())
        map_sec = m["map_section"]
        suggest = sorted(map_sec["videos"], key=lambda v: v.get("published", ""), reverse=True)[:4] if map_sec else []
        for reg in regions:
            parent = (map_sec["name"], map_sec["url"]) if map_sec else ("Області", None)
            c = self.crumbs(parent, (reg["name"], None))
            has = reg["count"] > 0
            what = []
            if reg["videos"]:
                what.append(videos_word(len(reg["videos"])))
            if reg["presentations"]:
                what.append(plural(len(reg["presentations"]), "презентація", "презентації", "презентацій"))
            self.render("region.html", reg["url"], title=f"{reg['name']}: відео для дітей | {SITE_NAME}",
                        description=(f"{reg['name']} для дітей: {' і '.join(what)} — міста, природа, історія. "
                                     f"Віртуальні подорожі від {LIBRARY}." if has else
                                     f"{reg['name']}: матеріали для дітей у відеотеці {LIBRARY}."),
                        reg=reg, crumbs=c, what=" і ".join(what), suggest=suggest,
                        ld=[self.crumbs_ld(c)] + ([self.item_list_ld(reg["name"], reg["url"], reg["videos"])]
                                                  if reg["videos"] else []))

        for v in all_videos:
            se = v["series"]
            sec = v["section_obj"]
            parts = [(sec["name"], sec["url"])]
            if len(sec["series"]) > 1:
                parts.append((se["title"], se["url"]))
            parts.append((v["title"], None))
            c = self.crumbs(*parts)
            idx = se["videos"].index(v)
            neighbours = (se["videos"][idx + 1:] + se["videos"][:idx])[:8]
            same_region = [x for x in (v["region_obj"]["videos"] if v.get("region_obj") else [])
                           if x is not v and x not in neighbours][:4]
            desc = v.get("description", "") or ""
            truncated = len(desc) in (300, 1000)   # збирач обрізає опис до цієї довжини
            if truncated and " " in desc:
                desc = desc.rsplit(" ", 1)[0].rstrip(",.;:—-– ")
            self.render("video.html", v["url"], lastmod=v.get("published") or None,
                        title=f"{v['title']} | {SITE_NAME}",
                        description=v["desc_short"] or f"Відео з серії «{se['title']}» — {LIBRARY}.",
                        og_image=v.get("thumb_big"), og_type="video.other",
                        v=v, crumbs=c, neighbours=neighbours, same_region=same_region,
                        desc_paragraphs=[p for p in re.split(r"\n\s*\n|\n", desc) if p.strip()],
                        desc_truncated=truncated,
                        next_v=se["videos"][idx + 1] if idx + 1 < len(se["videos"]) else None,
                        prev_v=se["videos"][idx - 1] if idx > 0 else None,
                        ld=[self.crumbs_ld(c), self.video_ld(v)])

        c = self.crumbs(("Пошук", None))
        self.render("search.html", "poshuk/", sitemap=False, robots_index=False,
                    title=f"Пошук | {SITE_NAME}", description="Пошук відео у відеотеці НБУ для дітей.", crumbs=c, ld=[])
        c = self.crumbs(("Про відеотеку", None))
        self.render("about.html", "pro/", title=f"Про відеотеку | {SITE_NAME}",
                    description=f"Що таке відеотека {LIBRARY}, звідки відео і як часто вони оновлюються.",
                    crumbs=c, ld=[self.crumbs_ld(c)])
        base_path = urlparse(SITE_URL).path or "/"
        self.render("404.html", "404.html", sitemap=False, robots_index=False, root=base_path,
                    title=f"Сторінку не знайдено | {SITE_NAME}", description="", crumbs=[], ld=[])

        self.write_search_index(all_videos)
        self.write_sitemap()
        self.copy_assets()

    def map_ctx(self) -> dict:
        regs = {r["slug"]: r for r in self.m["regions"].values()}
        return {"paths": [{**p, "reg": regs[p["slug"]]} for p in self.map_paths if p["slug"] in regs]}

    def write_search_index(self, videos):
        secs = list(self.m["sections"].keys())
        items = [{"t": v["title"], "u": v["url"], "th": v.get("thumb", ""), "d": v.get("published", ""),
                  "s": secs.index(v["section"]), "p": " · ".join(s["title"] for s in v["series_list"]),
                  "r": v["region_obj"]["name"] if v.get("region_obj") else "",
                  "x": short_text(v.get("description", ""), 200)}
                 for v in videos]
        (OUT / "search.json").write_text(
            json.dumps({"sections": secs, "items": items}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

    def write_sitemap(self):
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for path, lastmod in self.pages:
            lines.append(f"  <url><loc>{self.abs(path)}</loc><lastmod>{lastmod[:10]}</lastmod></url>")
        lines.append("</urlset>")
        (OUT / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        robots = ["User-agent: *", "Allow: /"]
        if INDEXABLE:
            robots.append(f"Sitemap: {SITE_URL}sitemap.xml")
        (OUT / "robots.txt").write_text("\n".join(robots) + "\n", encoding="utf-8")

    def copy_assets(self):
        shutil.copytree(SRC / "assets", OUT / "assets", dirs_exist_ok=True)
        # контурна карта для маленьких мап на сторінках областей (одна на всіх, кешується браузером)
        paths = "".join(f'<path d="{p["d"]}"/>' for p in self.map_paths)
        (OUT / "assets" / "map-base.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 530">'
            '<g fill="#efe3e1" stroke="#fff" stroke-width="1.2">' + paths + "</g></svg>", encoding="utf-8")
        for name in LEGACY_PAGES:
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, OUT / name)


def main() -> int:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    model = prepare(data)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    site = Site(model, load_map_paths())
    site.build()
    n_pages = sum(1 for _ in OUT.rglob("*.html"))
    print(f"Готово: {n_pages} сторінок у {OUT}; адреса {SITE_URL}; "
          f"індексація {'увімкнена' if INDEXABLE else 'вимкнена (демоверсія)'}; "
          f"у карті сайту {len(site.pages)} адрес.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
