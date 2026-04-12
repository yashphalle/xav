// Quick DB connectivity test — inserts a dummy row then fetches + deletes it
import { createClient } from '@supabase/supabase-js'
import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

// Load .env manually
const __dir = dirname(fileURLToPath(import.meta.url))
const envPath = resolve(__dir, '../.env')
const env = Object.fromEntries(
  readFileSync(envPath, 'utf8')
    .split('\n')
    .filter(l => l.includes('='))
    .map(l => {
      const idx = l.indexOf('=')
      const val = l.slice(idx + 1).trim().replace(/^["']|["']$/g, '')
      return [l.slice(0, idx).trim(), val]
    })
)

const supabase = createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_KEY)

const TEST_ID = '00000000-0000-0000-0000-000000000001'

async function run() {
  console.log('--- DB TEST ---')
  console.log('URL:', env.SUPABASE_URL)

  // 1. INSERT
  console.log('\n[1] Inserting dummy row...')
  const { error: insertErr } = await supabase
    .from('responses')
    .upsert({
      participant_id: TEST_ID,
      condition: 'none',
      start_time: new Date().toISOString(),
      age: 'test',
      completed: false,
    }, { onConflict: 'participant_id' })

  if (insertErr) {
    console.error('INSERT failed:', insertErr.message)
    process.exit(1)
  }
  console.log('Insert OK')

  // 2. FETCH
  console.log('\n[2] Fetching row...')
  const { data, error: fetchErr } = await supabase
    .from('responses')
    .select('participant_id, condition, age, start_time')
    .eq('participant_id', TEST_ID)
    .single()

  if (fetchErr) {
    console.error('FETCH failed:', fetchErr.message)
    process.exit(1)
  }
  console.log('Fetched row:', data)

  // 3. DELETE
  console.log('\n[3] Cleaning up...')
  const { error: deleteErr } = await supabase
    .from('responses')
    .delete()
    .eq('participant_id', TEST_ID)

  if (deleteErr) {
    console.error('DELETE failed:', deleteErr.message)
  } else {
    console.log('Cleanup OK')
  }

  console.log('\n✓ DB connection working correctly')
}

run()
