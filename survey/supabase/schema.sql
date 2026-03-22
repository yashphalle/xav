-- AV Survey responses table
-- Run this in your Supabase SQL editor

CREATE TABLE IF NOT EXISTS responses (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  participant_id  UUID UNIQUE NOT NULL,
  condition       TEXT DEFAULT 'vlm_descriptive',
  start_time      TIMESTAMPTZ,
  end_time        TIMESTAMPTZ,
  completed       BOOLEAN DEFAULT FALSE,

  -- Page 2
  exclude_mobile  BOOLEAN,
  audio_ok        BOOLEAN,

  -- Page 3 — Demographics
  age             TEXT,
  gender          TEXT,
  education       TEXT,
  license         TEXT,
  drive_years     TEXT,
  drive_freq      TEXT,
  av_exp          TEXT,
  av_familiarity  INTEGER,

  -- Page 4 — Baseline trust (1-5)
  pt1 INTEGER, pt2 INTEGER, pt3 INTEGER,
  pt4 INTEGER, pt5 INTEGER, pt6 INTEGER,
  -- AV attitudes (1-7)
  av1 INTEGER, av2 INTEGER, av3 INTEGER,

  -- Page 5 — Attention check 1
  ac1         INTEGER,
  attn_fail_1 BOOLEAN,

  -- Page 6A — Video
  video_watched BOOLEAN,

  -- Page 6B — Comprehension
  comp1           TEXT,
  comp2           TEXT,
  comp3           TEXT,
  comp1_correct   BOOLEAN,
  comp2_correct   BOOLEAN,
  comp3_correct   BOOLEAN,
  comp_score      INTEGER,
  comp_fail       BOOLEAN,

  -- Page 6C — S-TIAS (1-7)
  stias1    INTEGER,
  stias2    INTEGER,
  stias3    INTEGER,
  stias_mean REAL,

  -- Page 6D — NASA-TLX (0-100)
  tlx_mental      INTEGER,
  tlx_physical    INTEGER,
  tlx_temporal    INTEGER,
  tlx_performance INTEGER,
  tlx_effort      INTEGER,
  tlx_frustration INTEGER,
  tlx_composite   REAL,

  -- Page 6E — Mental model
  mental_model_text  TEXT,
  mental_model_text2 TEXT,

  -- Page 7 — Jian trust (1-7)
  jian1  INTEGER, jian2  INTEGER, jian3  INTEGER,
  jian4  INTEGER, jian5  INTEGER, jian6  INTEGER,
  jian7  INTEGER, jian8  INTEGER, jian9  INTEGER,
  jian10 INTEGER, jian11 INTEGER, jian12 INTEGER,
  jian_order      INTEGER[],
  jian_composite  REAL,

  -- Page 8
  ac2          TEXT,
  attn_fail_2  BOOLEAN,
  debrief_open TEXT,

  -- Derived exclusion flags
  exclude_final BOOLEAN,

  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Row Level Security: lock it down
-- All writes go through the Next.js API route using the service role key
ALTER TABLE responses ENABLE ROW LEVEL SECURITY;

-- No public access — service role key bypasses RLS
-- (The API route uses the service role key server-side)

-- Optional: auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER responses_updated_at
  BEFORE UPDATE ON responses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
