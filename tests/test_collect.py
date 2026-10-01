"""Перевірка збирача на зразкових даних, без мережі."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import collect  # noqa: E402

collect.time.sleep = lambda s: None  # без пауз у тестах

FEED_P1 = """<rss><channel><title>x</title>
<item><title>0925. Еліна Заржицька &quot;Пригоди динозавриків&quot;</title>
<link>https://mediateka.chl.kiev.ua/index.php?option=com_allvideoshare&amp;view=video&amp;slg=0925-dino</link>
<description><![CDATA[<div class="feed-description"><p>Іван, 10 років</p><p>Сумська обл.</p><p><img src="https://mediateka.chl.kiev.ua//images/video/nbu/marafon2026/0925.jpg" /></p></div>]]></description>
<pubDate>Wed, 08 Apr 2026 10:00:00 +0300</pubDate></item>
<item><title>0904. Стонадцять халеп</title>
<link>https://mediateka.chl.kiev.ua/index.php?option=com_allvideoshare&amp;view=video&amp;slg=0904-khalepy</link>
<description><![CDATA[<p>Марія, 9 років</p><p>Рівненщина</p>]]></description>
<pubDate>Tue, 07 Apr 2026 10:00:00 +0300</pubDate></item>
</channel></rss>"""
FEED_EMPTY = "<rss><channel><title>x</title></channel></rss>"
PAGE = '<iframe src="https://mediateka.chl.kiev.ua/index.php?option=com_allvideoshare&amp;view=player&amp;id=827&amp;format=raw"></iframe>'
PLAYER = '<video id="player"><source type="video/mp4" src="/images/video/nbu/0925.mp4" /></video>'


class Resp:
    def __init__(self, status=200, text="", js=None):
        self.status_code, self.text, self._js = status, text, js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def yt_item(vid, title, desc=""):
    return {"snippet": {"title": title, "description": desc, "publishedAt": "2025-01-01T00:00:00Z",
                        "thumbnails": {"medium": {"url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"}}},
            "contentDetails": {"videoId": vid, "videoPublishedAt": "2024-05-05T00:00:00Z"}}


class FakeHTTP:
    calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if "playlistItems" in url:
            pl, tok = params["playlistId"], params.get("pageToken")
            if pl == "PL_BROKEN":
                return Resp(403, "quotaExceeded")
            if pl == "PL_WOW" and not tok:
                return Resp(js={"items": [yt_item("AAA", "Ужгород — перлина Закарпаття"),
                                          yt_item("PRIV", "Private video"),
                                          yt_item("HID", "Сховане відео")], "nextPageToken": "p2"})
            if pl == "PL_WOW" and tok == "p2":
                return Resp(js={"items": [yt_item("BBB", "Замки Рівненщини")]})
            return Resp(js={"items": [yt_item("TALE1", "Казка про Колобка")]})
        if "videoteka/marafon" in url:
            return Resp(text=FEED_P1 if url.endswith("limitstart=0") else (FEED_P1 if url.endswith("=20") else FEED_EMPTY))
        if "view=player" in url:
            return Resp(text=PLAYER)
        if "slg=" in url:
            return Resp(text=PAGE)
        return Resp(404)


REGISTRY = {
    "Розділи": [
        {"Розділ": "Географія України", "Іконка": "🗺️", "Колір": "#3B82F6", "Порядок": "1", "Показувати": "так", "Опис": "Карта"},
        {"Розділ": "Казки", "Іконка": "🧚", "Колір": "#A855F7", "Порядок": "2", "Показувати": "так", "Опис": ""},
        {"Розділ": "Марафони читання", "Іконка": "🏃", "Колір": "#EF4444", "Порядок": "5", "Показувати": "так", "Опис": ""},
        {"Розділ": "Службове", "Іконка": "", "Колір": "", "Порядок": "99", "Показувати": "ні", "Опис": ""},
    ],
    "Джерела": [
        {"Показувати": "так", "Розділ порталу": "Географія України", "Назва на порталі": "Мандруємо Україною",
         "Тип джерела": "YouTube-плейлист", "Ідентифікатор": "PL_WOW", "Карта": "вручну (вкладка «Прив'язки»)", "Відео на 01.10.2026": "81"},
        {"Показувати": "так", "Розділ порталу": "Казки", "Назва на порталі": "Казка на ніч",
         "Тип джерела": "YouTube-плейлист", "Ідентифікатор": "PL_TALES", "Карта": "ні"},
        {"Показувати": "так", "Розділ порталу": "Казки", "Назва на порталі": "Зламаний плейлист",
         "Тип джерела": "YouTube-плейлист", "Ідентифікатор": "PL_BROKEN", "Карта": "ні"},
        {"Показувати": "так", "Розділ порталу": "Марафони читання", "Назва на порталі": "Марафон 2026",
         "Тип джерела": "Медіатека: категорія", "Ідентифікатор": "marafon", "Карта": "область з опису"},
        {"Показувати": "так", "Розділ порталу": "Службове", "Назва на порталі": "Анонси",
         "Тип джерела": "YouTube-плейлист", "Ідентифікатор": "PL_SERV", "Карта": "ні"},
        {"Показувати": "ні", "Розділ порталу": "Казки", "Назва на порталі": "Вимкнене",
         "Тип джерела": "YouTube-плейлист", "Ідентифікатор": "PL_OFF", "Карта": "ні"},
        {"Показувати": "так", "Розділ порталу": "Географія України", "Назва на порталі": "Презентації",
         "Тип джерела": "Google Drive: папка", "Ідентифікатор": "FOLDER", "Карта": "вручну"},
    ],
    "Прив'язки": [
        {"Ідентифікатор відео": "AAA", "Область на карті": "Закарпатська область"},
        {"Ідентифікатор відео": "BBB", "Область на карті": "Рівненська область", "Назва замість оригінальної": "Замки Рівненщини (оновлено)"},
        {"Ідентифікатор відео": "HID", "Приховати": "так"},
        {"Ідентифікатор відео": "TALE1", "Область на карті": "Атлантида"},
    ],
    "Презентації": [
        {"Назва": "Найцікавіші міста Львівщини", "Ідентифікатор файлу": "1xFK", "Область на карті": "Львівська область", "Показувати": "так"},
        {"Назва": "Вимкнена", "Ідентифікатор файлу": "zzz", "Область на карті": "", "Показувати": "ні"},
    ],
}

PREVIOUS = {"videos": [{"platform": "youtube", "id": "OLD1", "title": "Стара казка", "source_id": "PL_BROKEN",
                        "section": "Казки", "region": None, "thumb": "", "published": "", "url": ""}]}

data = collect.build(REGISTRY, "test-key", PREVIOUS, FakeHTTP())
by_id = {v["id"]: v for v in data["videos"]}

checks = {
    "розділи: лише увімкнені, за порядком": [s["name"] for s in data["sections"]] == ["Географія України", "Казки", "Марафони читання"],
    "YouTube: обидві сторінки плейлиста": {"AAA", "BBB"} <= by_id.keys(),
    "YouTube: приватні відео відкинуто": "PRIV" not in by_id,
    "Прив'язки: приховане відео відкинуто": "HID" not in by_id,
    "Прив'язки: область вручну": by_id["AAA"]["region"] == "Закарпатська область",
    "Прив'язки: нова назва": by_id["BBB"]["title"] == "Замки Рівненщини (оновлено)",
    "збій джерела: лишились минулі дані": "OLD1" in by_id and by_id["OLD1"]["source_id"] == "PL_BROKEN",
    "збій джерела: записано помилку": any("Зламаний плейлист" in e and "403" in e for e in data["errors"]),
    "збій джерела: позначено ok=false": next(s for s in data["sources"] if s["id"] == "PL_BROKEN")["ok"] is False,
    "Медіатека: дві сторінки без дублів": sum(1 for v in data["videos"] if v["platform"] == "mediateka") == 2,
    "Медіатека: область з опису (Сумська)": by_id["0925-dino"]["region"] == "Сумська область",
    "Медіатека: область з «Рівненщина»": by_id["0904-khalepy"]["region"] == "Рівненська область",
    "Медіатека: імені дитини немає у даних": "Іван" not in json.dumps(data, ensure_ascii=False) and "Марія" not in json.dumps(data, ensure_ascii=False),
    "Медіатека: пряма адреса MP4": by_id["0925-dino"]["mp4"] == "https://mediateka.chl.kiev.ua/images/video/nbu/0925.mp4",
    "Медіатека: обкладинка без подвійного слеша": "//images" not in by_id["0925-dino"]["thumb"],
    "Медіатека: дата публікації": by_id["0925-dino"]["published"] == "2026-04-08",
    "вимкнене джерело пропущено": not any(s["id"] == "PL_OFF" for s in data["sources"]),
    "джерело у вимкненому розділі: попередження": any("Службове" in e for e in data["errors"]),
    "невідома область: попередження": any("Атлантида" in e for e in data["errors"]),
    "презентації: лише увімкнені": [p["file_id"] for p in data["presentations"]] == ["1xFK"],
    "презентації: адреса перегляду": data["presentations"][0]["preview"].endswith("/1xFK/preview"),
}

# Друга ніч: MP4 уже відомі, сторінки відео повторно не запитуються
FakeHTTP.calls = []
data2 = collect.build(REGISTRY, "test-key", data, FakeHTTP())
checks["друга ніч: MP4 з кешу, без зайвих запитів"] = not any("slg=" in u or "view=player" in u for u in FakeHTTP.calls)
checks["друга ніч: той самий результат"] = {k: v for k, v in data2.items() if k != "generated_at"} == {k: v for k, v in data.items() if k != "generated_at"}

# Без ключа YouTube: помилка, але Медіатека працює
data3 = collect.build(REGISTRY, "", data, FakeHTTP())
checks["без ключа: помилка названа"] = any("YOUTUBE_API_KEY" in e for e in data3["errors"])
checks["без ключа: YouTube з минулих даних"] = "AAA" in {v["id"] for v in data3["videos"]}

checks["пошук області: «сумний» ≠ Сумщина"] = collect.region_from_text("Сумний їжачок") is None
checks["пошук області: Луцьк → Волинь"] = collect.region_from_text("Місто Луцьк") == "Волинська область"

failed = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("OK   " if ok else "FAIL ") + k)
print(f"\n{len(checks) - len(failed)}/{len(checks)} перевірок пройдено")
sys.exit(1 if failed else 0)
