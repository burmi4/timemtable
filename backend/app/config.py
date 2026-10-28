"""Настройки приложения."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Источник расписания (ТУСУР)
TIMETABLE_URL = os.getenv(
    "TIMETABLE_URL",
    "https://timetable.tusur.ru/faculties/fb/groups/744-1",
)

# Путь к локальному XML-файлу расписания (для разработки / офлайна).
# Если задан и файл существует — парсер берёт данные из него,
# иначе — скачивает с TIMETABLE_URL.
TIMETABLE_XML_PATH = os.getenv("TIMETABLE_XML_PATH", "")

# База данных
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}")

# Секрет для подписи cookie-сессий
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Интервал автообновления расписания: раз в неделю
REFRESH_INTERVAL_HOURS = int(os.getenv("REFRESH_INTERVAL_HOURS", "168"))  # 7 суток
