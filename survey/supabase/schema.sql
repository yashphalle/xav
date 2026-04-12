-- AV Survey — Full Schema
-- v1: responses table (participant-level)
-- v2: scenario_responses table (per scenario, 5 rows per participant) + responses additions
-- Run the full file in your Supabase SQL editor to set up or re-apply the schema.

-- ─── Migrations for existing responses table ────────────────────────────────
-- Safe to re-run; adds columns only if missing.
ALTER TABLE responses ADD COLUMN IF NOT EXISTS scenario_order  INTEGER[];
ALTER TABLE responses ADD COLUMN IF NOT EXISTS overall_trust   INTEGER;
ALTER TABLE responses ADD COLUMN IF NOT EXISTS debrief_open    TEXT;
ALTER TABLE responses ADD COLUMN IF NOT EXISTS exclude_final   BOOLEAN;
ALTER TABLE responses ADD COLUMN IF NOT EXISTS ac2             TEXT;
ALTER TABLE responses ADD COLUMN IF NOT EXISTS attn_fail_2     BOOLEAN;

-- ─── Helper trigger function ────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── responses table (participant-level data) ───────────────────────────────
CREATE TABLE IF NOT EXISTS responses (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  participant_id  UUID UNIQUE NOT NULL,
  condition       TEXT,                       -- none | template | vlm_descriptive | vlm_teleological
  scenario_order  INTEGER[],                  -- randomized display order, e.g. [2,0,4,1,3]
  start_time      TIMESTAMPTZ,
  end_time        TIMESTAMPTZ,
  completed       BOOLEAN DEFAULT FALSE,

  -- Tech check
  exclude_mobile  BOOLEAN,
  audio_ok        BOOLEAN,

  -- Demographics
  age             TEXT,
  gender          TEXT,
  education       TEXT,
  license         TEXT,
  drive_years     TEXT,
  drive_freq      TEXT,
  av_exp          TEXT,
  av_familiarity  INTEGER,

  -- Baseline trust — Propensity to Trust (1-5)
  pt1 INTEGER, pt2 INTEGER, pt3 INTEGER,
  pt4 INTEGER, pt5 INTEGER, pt6 INTEGER,
  -- AV Attitudes (1-7)
  av1 INTEGER, av2 INTEGER, av3 INTEGER,

  -- Attention check 1
  ac1         INTEGER,
  attn_fail_1 BOOLEAN,

  -- Attention check 2 (post-loop)
  ac2          TEXT,
  attn_fail_2  BOOLEAN,

  -- End-of-study
  overall_trust INTEGER,   -- 1-7, single item after all scenarios
  debrief_open  TEXT,

  -- Exclusion flags
  exclude_final BOOLEAN,

  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE responses ENABLE ROW LEVEL SECURITY;

DROP TRIGGER IF EXISTS responses_updated_at ON responses;
CREATE TRIGGER responses_updated_at
  BEFORE UPDATE ON responses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── scenario_responses table (per-scenario data, 5 rows per participant) ───
CREATE TABLE IF NOT EXISTS scenario_responses (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  participant_id   UUID NOT NULL REFERENCES responses(participant_id) ON DELETE CASCADE,
  scenario_index   INTEGER NOT NULL,   -- display position: 0..4
  scenario_id      TEXT NOT NULL,      -- e.g. 'S1_JaywalkingAdult'
  condition        TEXT NOT NULL,      -- denormalized for easy GROUP BY
  criticality      TEXT NOT NULL,      -- HIGH | MEDIUM | LOW

  -- Video
  video_watched    BOOLEAN,

  -- Comprehension (3 MCQ)
  comp1            TEXT,
  comp2            TEXT,
  comp3            TEXT,
  comp1_correct    BOOLEAN,
  comp2_correct    BOOLEAN,
  comp3_correct    BOOLEAN,
  comp_score       INTEGER,
  comp_fail        BOOLEAN,

  -- S-TIAS / Perceived Transparency (1-7)
  stias1     INTEGER,
  stias2     INTEGER,
  stias3     INTEGER,
  stias_mean REAL,

  -- NASA-TLX (0-100)
  tlx_mental      INTEGER,
  tlx_physical    INTEGER,
  tlx_temporal    INTEGER,
  tlx_performance INTEGER,
  tlx_effort      INTEGER,
  tlx_frustration INTEGER,
  tlx_composite   REAL,

  -- Mental Model (open-ended)
  mental_model_text  TEXT,
  mental_model_text2 TEXT,

  -- Jian Trust (1-7)
  jian1  INTEGER, jian2  INTEGER, jian3  INTEGER,
  jian4  INTEGER, jian5  INTEGER, jian6  INTEGER,
  jian7  INTEGER, jian8  INTEGER, jian9  INTEGER,
  jian10 INTEGER, jian11 INTEGER, jian12 INTEGER,
  jian_order     INTEGER[],
  jian_composite REAL,

  -- Explanation Helpfulness (1-7, NULL for 'none' condition)
  expl_clear    INTEGER,
  expl_helpful  INTEGER,
  expl_informed INTEGER,
  expl_mean     REAL,

  -- Anthropomorphism (1-7, all conditions)
  anthropomorphism INTEGER,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE (participant_id, scenario_index)
);

ALTER TABLE scenario_responses ENABLE ROW LEVEL SECURITY;

DROP TRIGGER IF EXISTS scenario_responses_updated_at ON scenario_responses;
CREATE TRIGGER scenario_responses_updated_at
  BEFORE UPDATE ON scenario_responses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_sr_participant ON scenario_responses(participant_id);
CREATE INDEX IF NOT EXISTS idx_sr_condition   ON scenario_responses(condition);
CREATE INDEX IF NOT EXISTS idx_sr_scenario_id ON scenario_responses(scenario_id);
