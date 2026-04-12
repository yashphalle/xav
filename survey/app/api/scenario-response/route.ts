import { NextRequest, NextResponse } from 'next/server'
import { supabase } from '@/lib/supabase'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { participant_id, scenario_index, ...data } = body

    if (!participant_id) {
      return NextResponse.json({ error: 'Missing participant_id' }, { status: 400 })
    }
    if (scenario_index === undefined || scenario_index === null) {
      return NextResponse.json({ error: 'Missing scenario_index' }, { status: 400 })
    }

    const { error } = await supabase
      .from('scenario_responses')
      .upsert(
        {
          participant_id,
          scenario_index,
          ...data,
          updated_at: new Date().toISOString(),
        },
        { onConflict: 'participant_id,scenario_index' }
      )

    if (error) {
      console.error('[scenario-response error]', error)
      return NextResponse.json({ error: error.message }, { status: 500 })
    }

    return NextResponse.json({ success: true })
  } catch (err) {
    console.error('[scenario-response API error]', err)
    return NextResponse.json({ error: 'Internal error' }, { status: 500 })
  }
}
