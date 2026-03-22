'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

export default function AttentionDebriefPage() {
  const router = useRouter()
  const { register, handleSubmit } = useForm()

  async function onSubmit(data: any) {
    const payload = {
      debrief_open: data.debrief_open || '',
      end_time: new Date().toISOString(),
      completed: true,
    }
    setSurvey(payload)
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ...payload }),
    }).catch(console.error)
    router.push('/complete')
  }

  return (
    <PageWrapper title="Open Reflection" step={10} totalSteps={10}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <div>
          <label className="section-title block mb-1">
            Did any information shown during the video clip change how you felt about the vehicle's decisions?
          </label>
          <p className="text-xs text-gray-400 mb-2">Optional — please explain your reasoning.</p>
          <textarea
            {...register('debrief_open')}
            rows={5}
            placeholder="Optional response…"
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">Submit Survey →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
