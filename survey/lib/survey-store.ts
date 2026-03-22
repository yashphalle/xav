import type { SurveyData } from '@/types/survey'

const KEY = 'av_survey_v1'

export function getSurvey(): Partial<SurveyData> {
  if (typeof window === 'undefined') return {}
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

export function setSurvey(data: Partial<SurveyData>): void {
  if (typeof window === 'undefined') return
  const current = getSurvey()
  localStorage.setItem(KEY, JSON.stringify({ ...current, ...data }))
}

export function clearSurvey(): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem(KEY)
}
