import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

/* ---------- Вспомогалки ---------- */

const DAY_ORDER = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

function fmtWeekRange(weekStart) {
  if (!weekStart) return ''
  const start = new Date(weekStart + 'T00:00:00')
  const end = new Date(start)
  end.setDate(end.getDate() + 6)
  return `${start.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })} — ${end.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })}`
}

/* ---------- Авторизация (имя + фамилия) ---------- */

function AuthPanel({ onAuthed }) {
  const [mode, setMode] = useState('register') // register | login
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError(''); setBusy(true)
    try {
      const fn = mode === 'register' ? api.register : api.login
      const user = await fn(firstName.trim(), lastName.trim())
      onAuthed(user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-card">
      <h2>Представьтесь</h2>
      <p className="muted">У каждого студента своя пользовательская запись (имя и фамилия).
        Она нужна, чтобы попадать в списки на практики и лабораторные.</p>
      <div className="tabs">
        <button className={mode === 'register' ? 'tab active' : 'tab'} onClick={() => setMode('register')}>
          Создать запись
        </button>
        <button className={mode === 'login' ? 'tab active' : 'tab'} onClick={() => setMode('login')}>
          Войти
        </button>
      </div>
      <form onSubmit={submit} className="auth-form">
        <input placeholder="Фамилия" value={lastName} onChange={(e) => setLastName(e.target.value)} required minLength={2} />
        <input placeholder="Имя" value={firstName} onChange={(e) => setFirstName(e.target.value)} required minLength={2} />
        <button type="submit" disabled={busy} className="btn primary">
          {busy ? '…' : mode === 'register' ? 'Зарегистрироваться' : 'Войти'}
        </button>
        {error && <div className="error">{error}</div>}
      </form>
    </div>
  )
}

/* ---------- Карточка пары ---------- */

function LessonCard({ lesson, user, myLessonIds, onChanged, notify }) {
  const [busy, setBusy] = useState(false)
  const mine = myLessonIds.includes(lesson.id)
  const mySignup = lesson.signups.find((s) => s.userId === user.id)

  const doSignup = async () => {
    setBusy(true)
    try {
      const r = await api.signup(lesson.id)
      notify(`Вы записаны: позиция ${r.position}`, 'ok')
      await onChanged()
    } catch (e) { notify(e.message, 'err') } finally { setBusy(false) }
  }

  const doCancel = async () => {
    setBusy(true)
    try {
      await api.cancelSignup(lesson.id)
      notify('Запись отменена', 'ok')
      await onChanged()
    } catch (e) { notify(e.message, 'err') } finally { setBusy(false) }
  }

  const kindClass = `kind-${lesson.kindType || 'other'}`

  return (
    <div className={`lesson ${lesson.isElective ? 'elective' : ''} ${mine ? 'mine' : ''}`}>
      <div className="lesson-head">
        <span className="lesson-num">№{lesson.lessonNumber}</span>
        <span className="lesson-time">{lesson.startTime}–{lesson.endTime}</span>
        <span className={`lesson-kind ${kindClass}`}>{lesson.kind}</span>
      </div>
      <div className="lesson-title" title={lesson.discipline}>
        {lesson.discipline || lesson.disciplineShort}
      </div>
      <div className="lesson-meta muted">
        {lesson.teachers && <>👤 {lesson.teachers}</>}
        {lesson.auditorium && <> · 🏠 {lesson.auditorium}</>}
      </div>

      {lesson.isElective && (
        <div className="signup-area">
          {lesson.signups.length > 0 ? (
            <ol className="signup-list">
              {lesson.signups.map((s) => (
                <li key={`${s.userId}-${s.position}`} className={s.userId === user.id ? 'me' : ''}>
                  {s.lastName} {s.firstName}
                  {s.userId === user.id && <span className="badge">это вы</span>}
                </li>
              ))}
            </ol>
          ) : (
            <div className="muted small">Записей пока нет — будьте первым!</div>
          )}
          {mine ? (
            <button className="btn danger" onClick={doCancel} disabled={busy}>
              Отменить запись {mySignup ? `(вы №${mySignup.position})` : ''}
            </button>
          ) : (
            <button className="btn primary" onClick={doSignup} disabled={busy}>
              Записаться (следующая позиция: {lesson.signups.length + 1})
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/* ---------- Главное приложение ---------- */

export default function App() {
  const [user, setUser] = useState(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [data, setData] = useState({ weekStart: null, lessons: [] })
  const [myLessonIds, setMyLessonIds] = useState([])
  const [status, setStatus] = useState(null)
  const [toast, setToast] = useState(null)
  const [onlyElective, setOnlyElective] = useState(false)
  const [loading, setLoading] = useState(false)

  const notify = useCallback((text, kind = 'info') => {
    setToast({ text, kind })
    setTimeout(() => setToast(null), 3500)
  }, [])

  const refresh = useCallback(async () => {
    const [tt, meResp, st] = await Promise.all([api.timetable(), api.me(), api.status()])
    setData(tt)
    setStatus(st)
    if (meResp.user) {
      setUser(meResp.user)
      setMyLessonIds(meResp.myLessonIds || [])
    } else {
      setUser(null)
      setMyLessonIds([])
    }
  }, [])

  useEffect(() => {
    refresh()
      .catch((e) => notify(e.message, 'err'))
      .finally(() => setAuthChecked(true))
  }, [refresh, notify])

  const onAuthed = async (u) => {
    setUser(u)
    await refresh()
    notify(`Запись создана/вход выполнен: ${u.lastName} ${u.firstName}`, 'ok')
  }

  const logout = async () => {
    await api.logout()
    setUser(null); setMyLessonIds([])
  }

  const manualSync = async () => {
    setLoading(true)
    try {
      const r = await api.sync()
      notify(r.status === 'ok' ? 'Расписание обновлено' : `Обновление пропущено (${r.status})`, 'ok')
      await refresh()
    } catch (e) { notify(e.message, 'err') } finally { setLoading(false) }
  }

  const byDay = useMemo(() => {
    const map = new Map()
    for (const l of data.lessons) {
      if (onlyElective && !l.isElective) continue
      const key = `${l.dayIso}|${l.dayName}`
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(l)
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [data, onlyElective])

  if (!authChecked) return <div className="page center muted">Загрузка…</div>

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <h1>Расписание группы 744-1</h1>
          <div className="muted small">
            Неделя: {fmtWeekRange(data.weekStart)} · Источник: timetable.tusur.ru ·
            обновление каждую неделю
            {status?.last_sync_at && <> · последняя синхронизация:{' '}
              {new Date(status.last_sync_at + 'Z').toLocaleString('ru-RU')}</>}
          </div>
        </div>
        <div className="top-actions">
          <button className="btn" onClick={manualSync} disabled={loading}>
            {loading ? 'Обновление…' : '⟳ Обновить сейчас'}
          </button>
          {user ? (
            <div className="user-chip">
              <span>👤 {user.lastName} {user.firstName}</span>
              <button className="btn small" onClick={logout}>Выйти</button>
            </div>
          ) : null}
        </div>
      </header>

      {!user ? (
        <AuthPanel onAuthed={onAuthed} />
      ) : (
        <>
          <div className="toolbar">
            <label className="switch">
              <input type="checkbox" checked={onlyElective} onChange={(e) => setOnlyElective(e.target.checked)} />
              Только практики и лабораторные (с записью)
            </label>
            <span className="muted small">
              Вы записаны на пар: {myLessonIds.length}
            </span>
          </div>

          {byDay.length === 0 && <div className="empty">Нет занятий</div>}

          {byDay.map(([key, lessons]) => {
            const [dayIso, dayName] = key.split('|')
            return (
              <section className="day" key={key}>
                <h2>{dayName}, {fmtDate(dayIso)}</h2>
                <div className="day-grid">
                  {lessons
                    .sort((a, b) => a.lessonNumber - b.lessonNumber)
                    .map((l) => (
                      <LessonCard
                        key={l.id}
                        lesson={l}
                        user={user}
                        myLessonIds={myLessonIds}
                        onChanged={refresh}
                        notify={notify}
                      />
                    ))}
                </div>
              </section>
            )
          })}
        </>
      )}

      {toast && <div className={`toast ${toast.kind}`}>{toast.text}</div>}
      <footer className="footer muted small">
        Расписание автоматически обновляется раз в неделю из
        {' '}<a href="https://timetable.tusur.ru/faculties/fb/groups/744-1" target="_blank" rel="noreferrer">tuSUR timetable</a>.
        Списки на каждую практику/лабораторную обнуляются с началом новой учебной недели.
      </footer>
    </div>
  )
}
