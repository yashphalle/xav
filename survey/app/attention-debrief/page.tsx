'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

const AC2_OPTIONS = ['Not at all', 'Slightly', 'Moderately', 'Very', 'Extremely']
const AC2_CORRECT = 'Extremely'

export default function AttentionDebriefPage() {
  const router = useRouter()
  const { register, handleSubmit } = useForm()

  async function onSubmit(data: any) {
    const ac2 = data.ac2 ?? ''
    const attn_fail_2 = ac2 !== AC2_CORRECT
    const payload = {
      ac2,
      attn_fail_2,
      debrief_open: data.debrief_open || '',
    }
    setSurvey(payload)
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ...payload }),
    }).catch(console.error)
    router.push('/overall-trust')
  }

  return (
    <PageWrapper title="Final Questions" step={9} totalSteps={10}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">

        {/* Attention Check 2 — trap question */}
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-5">
          <p className="text-sm font-medium text-amber-900 mb-1">Attention Check</p>
          <p className="text-sm text-amber-800 mb-4">
            To confirm you are still reading carefully, please select{' '}
            <strong>"Extremely"</strong> for the item below.
          </p>
          <p className="text-sm font-medium text-gray-800 mb-3">
            "I have been paying careful attention throughout this study."
          </p>
          <div className="space-y-2">
            {AC2_OPTIONS.map((opt) => (
              <label key={opt} className="radio-row">
                <input type="radio" value={opt} {...register('ac2')} className="w-4 h-4 text-blue-600" />
                <span className="text-sm text-gray-700">{opt}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Open-ended debrief */}
        <div>
          <label className="section-title block mb-1">
            Did any information shown during the video clips change how you felt about the vehicle's decisions?
          </label>
          <p className="text-xs text-gray-400 mb-2">Optional. Please explain your reasoning.</p>
          <textarea
            {...register('debrief_open')}
            rows={5}
            placeholder="Optional response…"
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
