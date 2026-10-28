"""Модели базы данных."""
from datetime import datetime

from sqlalchemy import (
    String, Integer, ForeignKey, DateTime, Boolean, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    """Пользовательская запись: имя и фамилия студента."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    group_name: Mapped[str] = mapped_column(String(40), default="744-1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signups: Mapped[list["Signup"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return f"{self.last_name} {self.first_name}"


class Lesson(Base):
    """Занятие из расписания (актуальная неделя).

    Уникальность занятия в пределах недели задаётся ключом uid —
    комбинацией дня, номера пары, дисциплины и вида занятия.
    Записи (signup list) привязаны к занятию и живут до следующей
    синхронизации расписания (раз в неделю).
    """
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(200), unique=True, index=True)

    week_start: Mapped[str] = mapped_column(String(10), index=True)   # ISO-дата понедельника
    day_iso: Mapped[str] = mapped_column(String(10))                  # дата занятия
    day_name: Mapped[str] = mapped_column(String(20))                 # пн/вт/...
    lesson_number: Mapped[int] = mapped_column(Integer)               # номер пары (1..7)
    start_time: Mapped[str] = mapped_column(String(10))
    end_time: Mapped[str] = mapped_column(String(10))

    discipline: Mapped[str] = mapped_column(String(255))              # полное название
    discipline_short: Mapped[str] = mapped_column(String(80), default="")
    kind: Mapped[str] = mapped_column(String(60))                     # Практика / Лабораторная работа / ...
    kind_type: Mapped[str] = mapped_column(String(40), default="")    # practice / laboratory / lecture ...
    teachers: Mapped[str] = mapped_column(String(255), default="")
    auditorium: Mapped[str] = mapped_column(String(80), default="")

    is_elective: Mapped[bool] = mapped_column(Boolean, default=False)  # отмечена как практика/лаба

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signups: Mapped[list["Signup"]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan",
        order_by="Signup.position",
    )


class Signup(Base):
    """Запись пользователя на пару. position = 1 для первого, 2 для второго и т.д."""
    __tablename__ = "signups"
    __table_args__ = (
        UniqueConstraint("lesson_id", "user_id", name="uq_signup_lesson_user"),
        Index("ix_signup_lesson_pos", "lesson_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lesson: Mapped[Lesson] = relationship(back_populates="signups")
    user: Mapped[User] = relationship(back_populates="signups")


class Meta(Base):
    """Служебная информация (дата последней синхронизации и т.п.)."""
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
