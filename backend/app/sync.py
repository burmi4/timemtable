"""Сервис синхронизации расписания (раз в неделю) и записей студентов."""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Lesson, Meta, Signup, User
from .parser import fetch_html, parse_timetable

log = logging.getLogger("timetable.sync")


def get_meta(db: Session, key: str, default: str = "") -> str:
    row = db.get(Meta, key)
    return row.value if row else default


def set_meta(db: Session, key: str, value: str) -> None:
    row = db.get(Meta, key)
    if row:
        row.value = value
    else:
        db.add(Meta(key=key, value=value))


def sync_timetable(force: bool = False) -> dict:
    """Обновляет расписание из источника.

    Обычный режим — не чаще раза в неделю (запускается планировщиком).
    force=True позволяет обновить вручную (кнопка в интерфейсе).
    """
    db = SessionLocal()
    try:
        last_raw = get_meta(db, "last_sync_at")
        now = dt.datetime.utcnow()
        if last_raw and not force:
            last = dt.datetime.fromisoformat(last_raw)
            if (now - last).total_seconds() < 6 * 24 * 3600:  # запас в сутки от 7 дней
                return {"status": "skipped", "last_sync_at": last_raw}

        html = fetch_html()
        parsed, week_start = parse_timetable(html)

        old_week = get_meta(db, "week_start")
        new_week = week_start.isoformat()

        if old_week != new_week:
            # Новая неделя: старые занятия удаляем вместе с записями —
            # на новой неделе список записей начинается заново.
            old_ids = db.scalars(
                select(Lesson.id).where(Lesson.week_start != new_week)
            ).all()
            if old_ids:
                db.execute(delete(Signup).where(Signup.lesson_id.in_(old_ids)))
                db.execute(delete(Lesson).where(Lesson.id.in_(old_ids)))

            existing_uids = set(db.scalars(select(Lesson.uid)).all())
            for pl in parsed:
                if pl.uid in existing_uids:
                    continue
                db.add(Lesson(
                    uid=pl.uid,
                    week_start=new_week,
                    day_iso=pl.day_iso,
                    day_name=pl.day_name,
                    lesson_number=pl.lesson_number,
                    start_time=pl.start_time,
                    end_time=pl.end_time,
                    discipline=pl.discipline or "(без названия)",
                    discipline_short=pl.discipline_short,
                    kind=pl.kind,
                    kind_type=pl.kind_type,
                    teachers=", ".join(pl.teachers),
                    auditorium=pl.auditorium,
                    is_elective=pl.is_elective,
                ))

        set_meta(db, "week_start", new_week)
        set_meta(db, "last_sync_at", now.isoformat(timespec="seconds"))
        db.commit()

        log.info("Расписание обновлено: %d занятий, неделя %s", len(parsed), new_week)
        return {"status": "ok", "lessons": len(parsed), "week_start": new_week,
                "synced_at": now.isoformat(timespec="seconds")}
    except Exception as exc:  # noqa: BLE001
        log.exception("Ошибка синхронизации расписания")
        set_meta_safe("last_sync_error", str(exc)[:200])
        return {"status": "error", "message": str(exc)}
    finally:
        db.close()


def set_meta_safe(key: str, value: str) -> None:
    db = SessionLocal()
    try:
        set_meta(db, key, value)
        db.commit()
    finally:
        db.close()


def ensure_first_sync() -> None:
    """Синхронизация при старте приложения, если данных ещё нет или пора обновляться."""
    db = SessionLocal()
    try:
        count = db.scalar(select(func.count(Lesson.id))) or 0
    finally:
        db.close()
    sync_timetable(force=(count == 0))
