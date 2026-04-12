import type { SurveyData, ScenarioResponseData } from '@/types/survey'

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

// ─── Per-scenario helpers ────────────────────────────────────────────────────

/** Get stored data for a specific scenario display index (0-4) */
export function getScenarioData(
  scenarioIndex: number
): Partial<ScenarioResponseData> {
  const survey = getSurvey()
  return survey.scenarios?.[scenarioIndex] ?? {}
}

/** Merge data into the stored record for a specific scenario display index */
export function setScenarioData(
  scenarioIndex: number,
  data: Partial<ScenarioResponseData>
): void {
  if (typeof window === 'undefined') return
  const survey = getSurvey()
  const scenarios: Partial<ScenarioResponseData>[] = survey.scenarios
    ? [...survey.scenarios]
    : []
  scenarios[scenarioIndex] = { ...scenarios[scenarioIndex], ...data }
  setSurvey({ scenarios })
}
