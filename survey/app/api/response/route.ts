import { NextRequest, NextResponse } from 'next/server'
import { supabase } from '@/lib/supabase'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { participant_id, ...data } = body

    if (!participant_id) {
      return NextResponse.json({ error: 'Missing participant_id' }, { status: 400 })
    }

    const { error } = await supabase
      .from('responses')
      .upsert(
        { participant_id, ...data, updated_at: new Date().toISOString() },
        { onConflict: 'participant_id' }
      )

    if (error) {
      console.error('[Supabase error]', error)
      return NextResponse.json({ error: error.message }, { status: 500 })
    }

    return NextResponse.json({ success: true })
  } catch (err) {
    console.error('[API error]', err)
    return NextResponse.json({ error: 'Internal error' }, { status: 500 })
  }
}
