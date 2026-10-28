"""Парсер расписания с сайта timetable.tusur.ru.

Сайт отдаёт HTML с таблицей вида "пары × дни недели".
Каждое занятие лежит в <div class="training training_type_...">:
  - data-lesson-id — идентификатор занятия
  - abbr[js-tooltip][title] — полное название дисциплины
  - span.kind — вид занятия (Лекция / Практика / Лабораторная работа ...)
  - ссылки на преподавателей и аудитории.

Занятия, отмеченные как практика или лабораторная работа, помечаются
is_elective=True — на них можно записаться.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from .config import TIMETABLE_URL, TIMETABLE_XML_PATH

log = logging.getLogger("timetable.parser")

DAY_MAP = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
MONTH_MAP = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
ELECTIVE_KINDS = ("практика", "лабораторная работа", "лабораторная")
USER_AGENT = "Mozilla/5.0 (compatible; ScheduleBot/1.0; student schedule app)"


@dataclass
class ParsedLesson:
    lesson_id: str
    day_iso: str
    day_name: str
    lesson_number: int
    start_time: str
    end_time: str
    discipline: str
    discipline_short: str
    kind: str
    kind_type: str
    teachers: list[str] = field(default_factory=list)
    auditorium: str = ""
    is_elective: bool = False

    @property
    def uid(self) -> str:
        """Стабильный идентификатор занятия на неделю."""
        raw = f"{self.day_iso}|{self.lesson_number}|{self.discipline}|{self.kind}"
        h = hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]
        return f"{self.lesson_id}-{h}"


_LOCAL_SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "timetable_sample.html"
)


def fetch_html(url: str | None = None) -> str:
    """Возвращает HTML расписания.

    Приоритет источников:
      1. Локальный файл TIMETABLE_XML_PATH (если задан);
      2. Сайт timetable.tusur.ru;
      3. Резервная локальная копия страницы (data/timetable_sample.html),
         чтобы приложение работало и при недоступности сети.
    """
    if TIMETABLE_XML_PATH and os.path.exists(TIMETABLE_XML_PATH):
        log.info("Читаю расписание из локального файла %s", TIMETABLE_XML_PATH)
        with open(TIMETABLE_XML_PATH, encoding="utf-8") as f:
            return f.read()
    try:
        resp = requests.get(url or TIMETABLE_URL, timeout=30, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        if os.path.exists(_LOCAL_SAMPLE):
            log.warning("Сайт недоступен (%s), использую резервную копию расписания", exc)
            with open(_LOCAL_SAMPLE, encoding="utf-8") as f:
                return f.read()
        raise


def _parse_day_header(text: str, week_start: dt.date) -> tuple[str, str] | None:
    """'пн, 26 окт.' -> (day_name, iso_date) с привязкой к неделе week_start."""
    m = re.match(r"(пн|вт|ср|чт|пт|сб|вс),?\s+(\d{1,2})\s+([а-яё]{3})", text.strip(), re.I)
    if not m:
        return None
    day_name, dom, mon = m.group(1).lower(), int(m.group(2)), MONTH_MAP.get(m.group(3).lower())
    if not mon:
        return None
    # дата занятия = понедельник недели + смещение по дню недели
    date = week_start + dt.timedelta(days=DAY_MAP[day_name])
    # подстраховка: если день месяца не совпадает (переход через год) — берём месяц
    if date.day != dom:
        year = date.year
        try:
            date = dt.date(year, mon, dom)
            if abs((date - week_start).days) > 10:
                date = dt.date(year + (1 if mon < week_start.month else -1), mon, dom)
        except ValueError:
            pass
    return day_name, date.isoformat()


def parse_timetable(html: str) -> tuple[list[ParsedLesson], dt.date]:
    """Парсит десктопную таблицу расписания.

    Возвращает список занятий и дату понедельника недели расписания.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.table-lessons.hidden-xs") or soup.select_one("table.table-lessons")
    if table is None:
        raise RuntimeError("Не найдена таблица расписания на странице")

    # Дни недели из заголовка
    days: list[tuple[str, str]] = []
    for th in table.select("thead th"):
        parsed = _parse_day_header(th.get_text(" ", strip=True), dt.date.today())
        if parsed:
            days.append(parsed)
    if not days:
        raise RuntimeError("Не удалось распознать дни недели в таблице")

    # Уточняем дату понедельника по первому дню таблицы
    first_day_name, first_day_iso = days[0]
    first_date = dt.date.fromisoformat(first_day_iso)
    week_start = first_date - dt.timedelta(days=DAY_MAP[first_day_name])
    # пересчитываем все даты от week_start
    days = [(dn, (week_start + dt.timedelta(days=DAY_MAP[dn])).isoformat()) for dn, _ in days]

    lessons: list[ParsedLesson] = []
    for row in table.select("tr[class^=lesson_]"):
        try:
            lesson_number = int(row["class"][-1].split("_")[1])
        except (KeyError, IndexError, ValueError):
            continue
        tds = row.find_all("td")
        for col, td in enumerate(tds):
            if col >= len(days):
                break
            day_name, day_iso = days[col]
            for tr_div in td.select("div.training"):
                cls = " ".join(tr_div.get("class", []))
                km = re.search(r"training_type_(\w+)", cls)
                kind_type = km.group(1) if km else ""

                lid_el = tr_div.select_one("[data-lesson-id]")
                hidden = tr_div.select_one("span.hidden")
                lesson_id = (
                    lid_el.get("data-lesson-id") if lid_el else
                    (hidden.get_text(strip=True) if hidden else "?")
                )

                abbr = tr_div.select_one("abbr")
                discipline = (abbr.get("title") or abbr.get_text(strip=True)) if abbr else ""
                short = abbr.get_text(strip=True) if abbr else discipline

                kind_el = tr_div.select_one("span.kind")
                kind = kind_el.get_text(" ", strip=True) if kind_el else ""

                teachers = [a.get_text(strip=True)
                            for a in tr_div.select("span.group a")]
                aud_el = tr_div.select_one("span.auditoriums a")
                auditorium = ""
                if aud_el:
                    href = aud_el.get("href", "")
                    m = re.search(r"auditoriums/(\w+)", href)
                    num = m.group(1) if m else ""
                    title = aud_el.select_one("[title]")
                    bld = ""
                    if title and title.get("title"):
                        bld = title["title"].split(",")[0]
                    auditorium = f"{bld} №{num}" if num else title.get_text(strip=True) if title else num

                is_elective = kind.lower().startswith(ELECTIVE_KINDS) or kind_type in (
                    "practice", "laboratory",
                )

                lessons.append(ParsedLesson(
                    lesson_id=lesson_id or "?",
                    day_iso=day_iso,
                    day_name=day_name,
                    lesson_number=lesson_number,
                    start_time="",
                    end_time="",
                    discipline=discipline,
                    discipline_short=short,
                    kind=kind,
                    kind_type=kind_type,
                    teachers=teachers,
                    auditorium=auditorium,
                    is_elective=is_elective,
                ))

    # Времена пар — из левого столбца (<th class='time'>) той же таблицы
    times_by_row: dict[int, tuple[str, str]] = {}
    for row in table.select("tr[class^=lesson_]"):
        try:
            ln = int(row["class"][-1].split("_")[1])
        except (KeyError, IndexError, ValueError):
            continue
        spans = row.select("th.time span") or row.select("th span")
        if len(spans) >= 2:
            times_by_row[ln] = (spans[0].get_text(strip=True), spans[1].get_text(strip=True))
    for ls in lessons:
        st, en = times_by_row.get(ls.lesson_number, ("", ""))
        ls.start_time, ls.end_time = st, en

    # Дедупликация: мобильные/дублирующиеся копии одних и тех же занятий
    seen: set[str] = set()
    unique: list[ParsedLesson] = []
    for ls in sorted(lessons, key=lambda x: (x.day_iso, x.lesson_number, x.uid)):
        key = f"{ls.day_iso}|{ls.lesson_number}|{ls.lesson_id}|{ls.discipline}|{ls.kind}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(ls)

    return unique, week_start
