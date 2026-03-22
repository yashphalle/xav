export interface SurveyData {
  participant_id: string
  start_time: string
  condition: string

  // Page 2
  audio_ok?: boolean

  // Page 3 — Demographics
  age?: string
  gender?: string
  education?: string
  license?: string
  drive_years?: string
  drive_freq?: string
  av_exp?: string
  av_familiarity?: number

  // Page 4 — Baseline trust (1-5) + AV attitudes (1-7)
  pt1?: number; pt2?: number; pt3?: number
  pt4?: number; pt5?: number; pt6?: number
  av1?: number; av2?: number; av3?: number

  // Page 5 — Attention check 1
  ac1?: number

  // Page 6A — Video
  video_watched?: boolean

  // Page 6B — Comprehension
  comp1?: string; comp2?: string; comp3?: string
  comp1_correct?: boolean; comp2_correct?: boolean; comp3_correct?: boolean
  comp_score?: number
  comp_fail?: boolean

  // Page 6C — S-TIAS
  stias1?: number; stias2?: number; stias3?: number
  stias_mean?: number

  // Page 6D — NASA-TLX
  tlx_mental?: number; tlx_physical?: number; tlx_temporal?: number
  tlx_performance?: number; tlx_effort?: number; tlx_frustration?: number
  tlx_composite?: number

  // Page 6E — Mental model
  mental_model_text?: string
  mental_model_text2?: string

  // Page 7 — Jian (12 items, 1-7)
  jian1?: number; jian2?: number; jian3?: number
  jian4?: number; jian5?: number; jian6?: number
  jian7?: number; jian8?: number; jian9?: number
  jian10?: number; jian11?: number; jian12?: number
  jian_order?: number[]
  jian_composite?: number

  // Page 8
  ac2?: number
  debrief_open?: string

  // Derived flags
  exclude_mobile?: boolean
  attn_fail_1?: boolean
  attn_fail_2?: boolean
  exclude_final?: boolean
}
