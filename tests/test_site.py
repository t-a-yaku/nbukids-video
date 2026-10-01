"""Перевірка зібраного сайту: усі внутрішні посилання ведуть на існуючі сторінки,
у кожної сторінки є заголовок, опис і правильна розмітка для пошуковиків.
Запуск: python tests/test_site.py [папка_сайту]  (без аргументу збирає сайт у тимчасову папку)."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

ROOT = Path(__file__).resolve().parent.parent

if len(sys.argv) > 1:
    site = Path(sys.argv[1])
else:
    site = Path(tempfile.mkdtemp()) / "site"
    for index_flag in ("так", "ні"):   # обидва режими мають збиратися без помилок
        env = {**os.environ, "SITE_OUT": str(site), "SITE_INDEX": index_flag,
               "SITE_URL": "https://example.org/videoteka/"}
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, env=env)

problems = []
pages = sorted(site.rglob("*.html"))
legacy = {"nbukids_hub.html"}
base = "https://example.org/videoteka/"

for page in pages:
    rel = page.relative_to(site).as_posix()
    if rel in legacy or rel == "404.html":
        continue
    html = page.read_text(encoding="utf-8")
    page_url = urljoin(base, rel[:-len("index.html")] if rel.endswith("index.html") else rel)
    if html.count("<h1") != 1:
        problems.append(f"{rel}: заголовків h1 — {html.count('<h1')}")
    if not re.search(r"<title>[^<]{5,}</title>", html):
        problems.append(f"{rel}: немає title")
    if 'name="description"' not in html and "poshuk" not in rel:
        problems.append(f"{rel}: немає опису")
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    if not canon:
        problems.append(f"{rel}: немає canonical")
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            json.loads(block)
        except ValueError as e:
            problems.append(f"{rel}: зламаний JSON-LD ({e})")
    for href in re.findall(r'(?:href|src)="([^"#?]*)', html):
        if not href or href.startswith(("http:", "https:", "mailto:", "data:")):
            continue
        target = urlparse(urljoin(page_url, href)).path
        if not target.startswith("/videoteka/"):
            problems.append(f"{rel}: посилання за межі сайту {href}")
            continue
        local = site / unquote(target[len("/videoteka/"):])
        if target.endswith("/"):
            local = local / "index.html"
        if not local.exists():
            problems.append(f"{rel}: бите посилання {href}")

regions = [p for p in (site / "oblast").iterdir() if (p / "index.html").exists()]
if len(regions) != 27:
    problems.append(f"сторінок регіонів {len(regions)}, а має бути 27")
for slug in ("krym", "sevastopol", "donetska", "luhanska", "kyiv"):
    if not (site / "oblast" / slug / "index.html").exists():
        problems.append(f"немає сторінки регіону {slug}")
home = (site / "index.html").read_text(encoding="utf-8")
if len(re.findall(r'href="oblast/[a-z-]+/" aria-label', home)) < 27:
    problems.append("на карті головної сторінки не всі 27 регіонів")

for p in problems[:40]:
    print("ПОМИЛКА", p)
print(f"Перевірено сторінок: {len(pages)}; проблем: {len(problems)}")
sys.exit(1 if problems else 0)
