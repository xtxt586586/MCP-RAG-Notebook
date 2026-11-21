import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'

import '../App.css'

import NotebookShell, {
  type NotebookView,
} from '../components/NotebookShell'
import { useLanguage } from '../i18n'

import {
  getReviewHistory,
  getReviewQuestion,
  getReviewStats,
  getTodayReviews,
  markReviewDone,
} from '../api/reviews'

import type {
  ReviewHistoryItem,
  ReviewItem,
  ReviewQuestion,
  ReviewStats,
  ReviewTrendItem,
} from '../types/reviews'

type DailyReviewPageProps = {
  email?: string
  onLogout?: () => void
  onNavigate?: (view: NotebookView) => void
}

export default function DailyReviewPage({
  email,
  onLogout,
  onNavigate,
}: DailyReviewPageProps) {
  const { language, t } = useLanguage()
  const [items, setItems] = useState<ReviewItem[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [questions, setQuestions] = useState<
    Record<string, ReviewQuestion>
  >({})
  const [selectedAnswer, setSelectedAnswer] = useState('')
  const [showResult, setShowResult] = useState(false)
  const [loading, setLoading] = useState(true)
  const [questionLoading, setQuestionLoading] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [doneCount, setDoneCount] = useState(0)
  const [stats, setStats] = useState<ReviewStats | null>(null)
  const [history, setHistory] = useState<ReviewHistoryItem[]>([])
  const [trend, setTrend] = useState<ReviewTrendItem[]>([])
  const finishingRef = useRef(false)

  const current = items[currentIndex]
  const currentQuestion = current
    ? questions[current.note_id]
    : undefined

  const loadReviews = useCallback(async () => {
    setLoading(true)
    setErrorMessage('')

    try {
      const response = await getTodayReviews()
      setItems(response.reviews)
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : t('review.loading'),
      )
    } finally {
      setLoading(false)
    }
  }, [t])

  const loadStats = useCallback(async () => {
    try {
      setStats(await getReviewStats())
    } catch {
      // Review cards remain usable when an older backend has no stats route.
      setStats(null)
    }
  }, [])

  const loadHistory = useCallback(async () => {
    try {
      const response = await getReviewHistory()
      setHistory(response.events)
      setTrend(response.daily_counts ?? [])
    } catch {
      setHistory([])
      setTrend([])
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadReviews()
      void loadStats()
      void loadHistory()
    }, 0)

    return () => {
      window.clearTimeout(timer)
    }
  }, [loadHistory, loadReviews, loadStats])

  function formatReviewDate(value: string | null) {
    if (!value) {
      return '暂无安排'
    }

    return new Intl.DateTimeFormat(language, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value))
  }

  async function startQuestion() {
    if (!current) {
      return
    }

    if (questions[current.note_id]) {
      setSelectedAnswer('')
      setShowResult(false)
      return
    }

    setQuestionLoading(true)
    setErrorMessage('')

    try {
      const question = await getReviewQuestion(
        current.note_id,
      )

      setQuestions((previous) => ({
        ...previous,
        [current.note_id]: question,
      }))
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : t('review.generating'),
      )
    } finally {
      setQuestionLoading(false)
    }
  }

  async function finishCurrent() {
    if (!current || finishingRef.current) {
      return
    }

    finishingRef.current = true
    setFinishing(true)
    try {
      await markReviewDone(current.note_id)
      setDoneCount((count) => count + 1)
      void loadStats()
      void loadHistory()

      if (currentIndex >= items.length - 1) {
        setCompleted(true)
        return
      }

      setCurrentIndex((index) => index + 1)
      setSelectedAnswer('')
      setShowResult(false)
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : t('review.finish'),
      )
    } finally {
      finishingRef.current = false
      setFinishing(false)
    }
  }

  function answerQuestion(answer: string) {
    setSelectedAnswer(answer)
    setShowResult(true)
  }

  return (
    <NotebookShell
      activeView="review"
      email={email}
      onNavigate={onNavigate ?? (() => undefined)}
      onLogout={onLogout ?? (() => undefined)}
    >
      <main className="review-page">
        <header className="notebook-page-header">
          <div>
            <p className="eyebrow">{t('review.spaced')}</p>
            <h1>{t('review.title')}</h1>
          </div>

          {!loading && items.length > 0 && (
            <span className="review-progress">
              {t('review.progress')} {doneCount}/{items.length}
            </span>
          )}
        </header>

        {errorMessage && (
          <div className="message error-message">
            {errorMessage}
          </div>
        )}

        {stats && (
          <section className="review-stats" aria-label={t('review.statsLabel')}>
            <article className="review-stat-card">
              <span>{t('review.due')}</span>
              <strong>{stats.due_count}</strong>
              <small>{t('review.notes')}</small>
            </article>
            <article className="review-stat-card">
              <span>{t('review.total')}</span>
              <strong>{stats.total_review_count}</strong>
              <small>{t('review.completions')}</small>
            </article>
            <article className="review-stat-card">
              <span>{t('review.recent')}</span>
              <strong>{stats.recent_reviewed_notes}</strong>
              <small>{t('review.reviewedNotes')}</small>
            </article>
            <article className="review-stat-card review-stat-card-wide">
              <span>{t('review.next')}</span>
              <strong>{formatReviewDate(stats.next_review_at)}</strong>
              <small>
                {t('review.started')} {stats.reviewed_notes}/{stats.tracked_notes} {t('review.notes')}
              </small>
            </article>
          </section>
        )}

        <section className="review-content">
          {loading ? (
            <div className="review-card">
              {t('review.loading')}
            </div>
          ) : completed ? (
            <div className="review-card review-completed">
              <strong>{t('review.completed')}</strong>
              <p>
                {t('review.completedCount')} {doneCount}/{items.length} {t('review.notes')}。
              </p>
            </div>
          ) : !current ? (
            <div className="review-card review-completed">
              <strong>{t('review.none')}</strong>
              <p>{t('review.noneHint')}</p>
            </div>
          ) : !currentQuestion ? (
            <article className="review-card">
              <p className="eyebrow">{t('review.dueToday')}</p>
              <h2>{current.title}</h2>
              <p className="review-meta">
                {current.review_count + 1} {t('review.reviewCount')}
              </p>
              <p className="review-preview">
                {current.content_preview}
              </p>
              <button
                className="primary-button"
                type="button"
                onClick={() => void startQuestion()}
                disabled={questionLoading}
              >
                {questionLoading
                  ? t('review.generating')
                  : t('review.start')}
              </button>
            </article>
          ) : (
            <article className="review-card">
              <p className="eyebrow">{t('review.question')}</p>
              <h2>{currentQuestion.question}</h2>

              <div className="review-options">
                {currentQuestion.choices.map(
                  (choice, index) => {
                    const isCorrect =
                      choice === currentQuestion.answer
                    const isSelected =
                      choice === selectedAnswer

                    let className =
                      'review-option'

                    if (showResult && isCorrect) {
                      className += ' correct'
                    } else if (
                      showResult &&
                      isSelected
                    ) {
                      className += ' wrong'
                    }

                    return (
                      <button
                        className={className}
                        key={choice}
                        type="button"
                        disabled={showResult}
                        onClick={() =>
                          answerQuestion(choice)
                        }
                      >
                        <span>
                          {String.fromCharCode(65 + index)}.
                        </span>
                        {choice}
                      </button>
                    )
                  },
                )}
              </div>

              {showResult && (
                <>
                  <p
                    className={
                      selectedAnswer ===
                      currentQuestion.answer
                        ? 'review-result correct'
                        : 'review-result wrong'
                    }
                  >
                    {selectedAnswer ===
                    currentQuestion.answer
                      ? t('review.correct')
                      : `${t('review.wrong')}${currentQuestion.answer}`}
                  </p>

                  <button
                    className="primary-button"
                    type="button"
                    onClick={() => void finishCurrent()}
                    disabled={finishing}
                  >
                    {finishing ? t('review.finishing') : t('review.finish')}
                  </button>
                </>
              )}
            </article>
          )}
        </section>

        {(history.length > 0 || trend.length > 0) && (
          <section className="review-history" aria-label={t('review.history')}>
            <div className="review-history-heading">
              <div>
                <p className="eyebrow">Recent activity</p>
                <h2>{t('review.history')}</h2>
              </div>
              <span>{t('review.last30')}</span>
            </div>
            {trend.length > 0 && (
              <div className="review-trend" aria-label={t('review.trendLabel')}>
                {trend.map((day) => {
                  const maximum = Math.max(
                    ...trend.map((item) => item.count),
                    1,
                  )
                  const date = new Date(`${day.date}T00:00:00`)

                  return (
                    <div className="review-trend-day" key={day.date}>
                      <div className="review-trend-bar-wrap">
                        <span
                          className="review-trend-bar"
                          style={{
                            height: `${Math.max(8, (day.count / maximum) * 100)}%`,
                          }}
                          title={`${day.date}：${day.count} 次`}
                        />
                      </div>
                      <small>
                        {new Intl.DateTimeFormat('zh-CN', {
                          month: 'numeric',
                          day: 'numeric',
                        }).format(date)}
                      </small>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="review-history-list">
              {history.map((event) => (
                <article className="review-history-row" key={event.event_id}>
                  <div>
                    <strong>{event.title}</strong>
                      <span>
                        {event.review_count} {t('review.reviewCount')} · {t('review.nextInterval')} {event.interval_days} {t('review.days')}
                      </span>
                  </div>
                  <time dateTime={event.reviewed_at}>
                    {formatReviewDate(event.reviewed_at)}
                  </time>
                </article>
              ))}
            </div>
          </section>
        )}
      </main>
    </NotebookShell>
  )
}
