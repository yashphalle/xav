import type { Condition, Criticality } from '@/lib/scenarios'

export type { Condition, Criticality }

// ─── Per-scenario data (one entry per scenario in the loop) ─────────────────
export interface ScenarioResponseData {
  scenario_index: number
  scenario_id: string
  condition: Condition
  criticality: Criticality

  video_watched?: boolean

  comp1?: string; comp2?: string; comp3?: string
  comp1_correct?: boolean; comp2_correct?: boolean; comp3_correct?: boolean
  comp_score?: number
  comp_fail?: boolean

  stias1?: number; stias2?: number; stias3?: number
  stias_mean?: number

  tlx_mental?: number; tlx_physical?: number; tlx_temporal?: number
  tlx_performance?: number; tlx_effort?: number; tlx_frustration?: number
  tlx_composite?: number

  mental_model_text?: string
  mental_model_text2?: string

  jian1?: number;  jian2?: number;  jian3?: number
  jian4?: number;  jian5?: number;  jian6?: number
  jian7?: number;  jian8?: number;  jian9?: number
  jian10?: number; jian11?: number; jian12?: number
  jian_order?: number[]
  jian_composite?: number

  // Explanation helpfulness (1-7, null for 'none' condition)
  expl_clear?: number
  expl_helpful?: number
  expl_informed?: number
  expl_mean?: number

  // Anthropomorphism (1-7, all conditions)
  anthropomorphism?: number
}

// ─── Participant-level data (one row in responses table) ────────────────────
export interface SurveyData {
  participant_id: string
  start_time: string
  condition: Condition
  scenario_order: number[]       // randomized display indices, e.g. [2,0,4,1,3]

  audio_ok?: boolean
  exclude_mobile?: boolean

  // Demographics
  age?: string
  gender?: string
  education?: string
  license?: string
  drive_years?: string
  drive_freq?: string
  av_exp?: string
  av_familiarity?: number

  // Baseline trust — Propensity to Trust (1-5)
  pt1?: number; pt2?: number; pt3?: number
  pt4?: number; pt5?: number; pt6?: number
  // AV Attitudes (1-7)
  av1?: number; av2?: number; av3?: number

  // Attention check 1
  ac1?: number
  attn_fail_1?: boolean

  // Attention check 2 (post-loop)
  ac2?: string
  attn_fail_2?: boolean

  // End-of-study
  overall_trust?: number
  debrief_open?: string

  // Exclusion flags
  exclude_final?: boolean

  // Per-scenario data (stored in localStorage, posted to scenario_responses)
  scenarios?: Partial<ScenarioResponseData>[]
}
