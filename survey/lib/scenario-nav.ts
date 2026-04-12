import type { Condition } from './scenarios'

/**
 * Ordered steps within a single scenario loop.
 * 'reflection' shows explanation helpfulness (non-none) + anthropomorphism.
 */
const SCENARIO_STEPS = [
  'video',
  'comprehension',
  's-tias',
  'nasa-tlx',
  'mental-model',
  'jian-trust',
  'reflection',
] as const

export type ScenarioStep = (typeof SCENARIO_STEPS)[number]

export const TOTAL_SCENARIO_STEPS = SCENARIO_STEPS.length   // 7
export const TOTAL_SCENARIOS = 5

/**
 * Returns the next URL path after completing `currentStep` for `scenarioIndex`.
 * After the last scenario's last step, returns '/attention-debrief'.
 */
export function nextScenarioPath(
  scenarioIndex: number,
  currentStep: ScenarioStep,
): string {
  const idx = SCENARIO_STEPS.indexOf(currentStep)
  const nextStep = SCENARIO_STEPS[idx + 1]

  if (nextStep) {
    return `/scenario/${scenarioIndex}/${nextStep}`
  }

  // End of this scenario
  if (scenarioIndex < TOTAL_SCENARIOS - 1) {
    return `/scenario/${scenarioIndex + 1}/video`
  }

  return '/attention-debrief'
}

/** Step number (1-indexed) within a scenario, for progress display */
export function scenarioStepNumber(step: ScenarioStep): number {
  return SCENARIO_STEPS.indexOf(step) + 1
}
