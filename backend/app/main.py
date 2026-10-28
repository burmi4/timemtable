"""API приложения расписания (FastAPI).

Эндпоинты:
  POST /api/auth/register      — создать пользовательскую запись (имя + фамилия)
  POST /api/auth/login         — вход по имени и фамилии (устанавливает cookie-сессию)
  POST /api/auth/logout        — выход
  GET  /api/me                 — текущий пользователь и его записи
  GET  /api/timetable          — расписание на неделю + списки записей на каждую пару
  POST /api/lessons/{id}/signup  — записаться на пару (1-м, 2-м, 3-м ...)
  DELETE /api/lessons/{id}/signup — отменить запись
  POST /api/sync               — принудительная синхронизация с timetable.tusur.ru
  GET  /api/status             — информация о последней синхронизации
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .config import SECRET_KEY
from .database import Base, engine, get_db
from .models import Lesson, Meta, Signup, User
from .sync import sync_timetable

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Расписание 744-1", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

serializer = URLSafeTimedSerializer(SECRET_KEY, salt="session")
COOKIE_NAME = "session_uid"


@app.on_event("startup")
def _startup() -> None:
    from apscheduler.schedulers.background import BackgroundScheduler
    from .sync import ensure_first_sync
    from .config import REFRESH_INTERVAL_HOURS

    ensure_first_sync()

    scheduler = BackgroundScheduler()
    # Обновление расписания каждую неделю
    scheduler.add_job(lambda: sync_timetable(force=False), "interval",
                      hours=REFRESH_INTERVAL_HOURS, id="weekly_sync")
    scheduler.start()
    log.info("Планировщик запущен: обновление раз в %d ч.", REFRESH_INTERVAL_HOURS)


# ---------- Сессии ----------

def create_session(response: Response, user_id: int) -> None:
    token = serializer.dumps({"uid": user_id})
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=86400 * 30)


def current_user_id(request: Request) -> int | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=86400 * 30)
        return int(data["uid"])
    except (BadSignature, KeyError, ValueError):
        return None


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = current_user_id(request)
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(status_code=401, detail="Требуется вход (укажите имя и фамилию)")
    return user


# ---------- Схемы ----------

class UserIn(BaseModel):
    first_name: str = Field(min_length=2, max_length=80, examples=["Иван"])
    last_name: str = Field(min_length=2, max_length=80, examples=["Петров"])


# ---------- Auth ----------

@app.post("/api/auth/register")
def register(data: UserIn, response: Response, db: Session = Depends(get_db)):
    """Регистрирует пользовательскую запись (студент сам себя не выбирает — просто представляется)."""
    first, last = data.first_name.strip().capitalize(), data.last_name.strip().capitalize()
    existing = db.scalars(select(User).where(
        func.lower(User.first_name) == first.lower(),
        func.lower(User.last_name) == last.lower(),
    )).all()
    if existing:
        # Не создаём дублей: авторизуем под существующей записью
        user = min(existing, key=lambda u: (len(u.signups), u.id))
        create_session(response, user.id)
        return {"id": user.id, "firstName": user.first_name, "lastName": user.last_name}
    user = User(first_name=first, last_name=last)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Такая запись уже существует") from None
    db.refresh(user)
    create_session(response, user.id)
    return {"id": user.id, "firstName": user.first_name, "lastName": user.last_name}


@app.post("/api/auth/login")
def login(data: UserIn, response: Response, db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(
        func.lower(User.first_name) == data.first_name.strip().lower(),
        func.lower(User.last_name) == data.last_name.strip().lower(),
    )).all()
    # если дублей нет — входим сразу; иначе выбираем запись с минимальной ценой входа
    user = min(users, key=lambda u: (len(u.signups), u.id)) if users else None
    if not user:
        raise HTTPException(status_code=404, detail="Запись не найдена. Зарегистрируйтесь.")
    create_session(response, user.id)
    return {"id": user.id, "firstName": user.first_name, "lastName": user.last_name}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    uid = current_user_id(request)
    if not uid:
        return {"user": None}
    user = db.get(User, uid)
    if not user:
        return {"user": None}
    my_ids = set(db.scalars(select(Signup.lesson_id).where(Signup.user_id == uid)).all())
    return {
        "user": {"id": user.id, "firstName": user.first_name, "lastName": user.last_name},
        "myLessonIds": sorted(my_ids),
    }


# ---------- Расписание ----------

DAY_RU = {"пн": "Понедельник", "вт": "Вторник", "ср": "Среда", "чт": "Четверг",
          "пт": "Пятница", "сб": "Суббота", "вс": "Воскресенье"}


def lesson_json(ls: Lesson) -> dict:
    signups = [
        {
            "position": s.position,
            "userId": s.user_id,
            "firstName": s.user.first_name,
            "lastName": s.user.last_name,
        }
        for s in sorted(ls.signups, key=lambda x: x.position)
    ]
    return {
        "id": ls.id,
        "uid": ls.uid,
        "dayIso": ls.day_iso,
        "dayName": DAY_RU.get(ls.day_name, ls.day_name),
        "lessonNumber": ls.lesson_number,
        "startTime": ls.start_time,
        "endTime": ls.end_time,
        "discipline": ls.discipline,
        "disciplineShort": ls.discipline_short or ls.discipline,
        "kind": ls.kind,
        "kindType": ls.kind_type,
        "teachers": ls.teachers,
        "auditorium": ls.auditorium,
        "isElective": ls.is_elective,
        "signups": signups,
    }


@app.get("/api/timetable")
def timetable(db: Session = Depends(get_db)):
    lessons = db.scalars(
        select(Lesson).options(joinedload(Lesson.signups).joinedload(Signup.user))
        .order_by(Lesson.day_iso, Lesson.lesson_number, Lesson.id)
    ).unique().all()
    week_start = db.get(Meta, "week_start").value if db.get(Meta, "week_start") else None
    return {
        "weekStart": week_start,
        "lessons": [lesson_json(l) for l in lessons],
    }


# ---------- Записи на пары ----------

@app.post("/api/lessons/{lesson_id}/signup")
def signup(lesson_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Пользователь записывается на пару: первый получает позицию 1, второй — 2 и т.д."""
    lesson = db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Пара не найдена")
    if not lesson.is_elective:
        raise HTTPException(status_code=400,
                            detail="Запись доступна только на практики и лабораторные работы")
    already = db.scalar(select(Signup).where(
        Signup.lesson_id == lesson_id, Signup.user_id == user.id))
    if already:
        raise HTTPException(status_code=409,
                            detail=f"Вы уже записаны (позиция {already.position})")

    max_pos = db.scalar(select(func.max(Signup.position)).where(Signup.lesson_id == lesson_id)) or 0
    s = Signup(lesson_id=lesson_id, user_id=user.id, position=max_pos + 1)
    db.add(s)
    db.commit()
    return {"ok": True, "position": s.position}


@app.delete("/api/lessons/{lesson_id}/signup")
def cancel_signup(lesson_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Отмена записи: остальные сдвигаются, чтобы позиции оставались 1..N без пропусков."""
    s = db.scalar(select(Signup).where(Signup.lesson_id == lesson_id, Signup.user_id == user.id))
    if not s:
        raise HTTPException(status_code=404, detail="Вы не записаны на эту пару")
    db.delete(s)
    db.flush()
    remaining = db.scalars(
        select(Signup).where(Signup.lesson_id == lesson_id).order_by(Signup.position)
    ).all()
    for i, item in enumerate(remaining, start=1):
        item.position = i
    db.commit()
    return {"ok": True}


# ---------- Статус / синхронизация ----------

@app.get("/api/status")
def status(db: Session = Depends(get_db)):
    keys = ("last_sync_at", "week_start", "last_sync_error")
    out = {}
    for k in keys:
        row = db.get(Meta, k)
        out[k] = row.value if row else None
    out["nextSyncHint"] = "каждые 7 дней (автоматически)"
    return out


@app.post("/api/sync")
def manual_sync():
    result = sync_timetable(force=True)
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("message", "Ошибка обновления"))
    return result


# ---------- Глобальная обработка ошибок БД ----------

@app.exception_handler(IntegrityError)
def integrity_handler(_: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "Нарушение целостности данных"})
