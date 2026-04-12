/**
 * DB migration checker.
 * 1. Tests whether scenario_responses table exists.
 * 2. If yes — inserts a test entry and leaves it for verification.
 * 3. If no  — prints the SQL to run in Supabase SQL editor.
 */
import { createClient } from '@supabase/supabase-js'
import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dir = dirname(fileURLToPath(import.meta.url))
const envPath = resolve(__dir, '../.env')
const env = Object.fromEntries(
  readFileSync(envPath, 'utf8').split('\n').filter(l => l.includes('=')).map(l => {
    const idx = l.indexOf('=')
    return [l.slice(0, idx).trim(), l.slice(idx + 1).trim().replace(/^["']|["']$/g, '')]
  })
)

const supabase = createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_KEY)

const TEST_PARTICIPANT_ID = '00000000-0000-0000-0000-000000000099'

async function run() {
  console.log('=== DB Migration Check ===\n')

  // 1. Check if scenario_responses exists
  const { error: tableCheckErr } = await supabase
    .from('scenario_responses')
    .select('id')
    .limit(1)

  if (tableCheckErr) {
    console.log('✗ scenario_responses table NOT found:', tableCheckErr.message)
    console.log('\n─────────────────────────────────────────────────────')
    console.log('ACTION REQUIRED: Run supabase/schema.sql in your Supabase SQL editor.')
    console.log('Go to: https://supabase.com/dashboard → Your project → SQL Editor')
    console.log('Paste the contents of: survey/supabase/schema.sql')
    console.log('─────────────────────────────────────────────────────\n')
    process.exit(1)
  }

  console.log('✓ scenario_responses table exists\n')

  // 2. Ensure test participant row exists in responses (FK constraint)
  const { error: parentErr } = await supabase.from('responses').upsert(
    { participant_id: TEST_PARTICIPANT_ID, condition: 'vlm_descriptive', scenario_order: [0,1,2,3,4] },
    { onConflict: 'participant_id' }
  )
  if (parentErr) {
    console.error('✗ Could not insert test row into responses:', parentErr.message)
    console.error('  Hint: Run the ALTER TABLE statements at the top of schema.sql in Supabase SQL Editor.')
    process.exit(1)
  }
  console.log('✓ Test participant row ready in responses')

  // 3. Insert test scenario_responses entry (leave it for user to verify)
  const testEntry = {
    participant_id:  TEST_PARTICIPANT_ID,
    scenario_index:  0,
    scenario_id:     'S1_JaywalkingAdult',
    condition:       'vlm_descriptive',
    criticality:     'HIGH',
    video_watched:   true,
    comp1:           'A pedestrian crossing mid-block outside the crosswalk',
    comp2:           'It applied sudden brakes',
    comp3:           'It reacted preemptively as the pedestrian entered the road',
    comp1_correct:   true,
    comp2_correct:   true,
    comp3_correct:   true,
    comp_score:      3,
    comp_fail:       false,
    stias1: 6, stias2: 5, stias3: 6, stias_mean: 5.667,
    tlx_mental: 35, tlx_physical: 10, tlx_temporal: 20,
    tlx_performance: 75, tlx_effort: 30, tlx_frustration: 15,
    tlx_composite: 35.833,
    mental_model_text:  'The vehicle detected a pedestrian in the road and braked to avoid a collision.',
    mental_model_text2: 'Likely used camera and lidar sensor fusion.',
    jian1: 2, jian2: 2, jian3: 3, jian4: 2, jian5: 2,
    jian6: 6, jian7: 5, jian8: 6, jian9: 5, jian10: 6, jian11: 6, jian12: 4,
    jian_order: [5,0,3,8,11,2,6,10,1,7,4,9],
    jian_composite: 5.083,
    expl_clear: 6, expl_helpful: 6, expl_informed: 5, expl_mean: 5.667,
    anthropomorphism: 4,
  }

  const { error: insertErr } = await supabase
    .from('scenario_responses')
    .upsert(testEntry, { onConflict: 'participant_id,scenario_index' })

  if (insertErr) {
    console.error('✗ Insert failed:', insertErr.message)
    process.exit(1)
  }

  // 4. Verify by fetching back
  const { data, error: fetchErr } = await supabase
    .from('scenario_responses')
    .select('participant_id, scenario_id, condition, criticality, comp_score, jian_composite, expl_mean, anthropomorphism')
    .eq('participant_id', TEST_PARTICIPANT_ID)
    .single()

  if (fetchErr) {
    console.error('✗ Fetch failed:', fetchErr.message)
    process.exit(1)
  }

  console.log('✓ Test entry inserted and verified:')
  console.log(JSON.stringify(data, null, 2))
  console.log('\n─────────────────────────────────────────────────────')
  console.log('Check your Supabase dashboard → Table Editor → scenario_responses')
  console.log(`participant_id: ${TEST_PARTICIPANT_ID}`)
  console.log('The test entry is LEFT IN the table for you to verify.')
  console.log('To clean up later, delete the row with that participant_id.')
  console.log('─────────────────────────────────────────────────────')
}

run()
