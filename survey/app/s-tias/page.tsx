'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'
import LikertMatrix from '@/components/survey/LikertMatrix'

const STIAS_ITEMS = [
  'I am confident in the system.',
  'The system is reliable.',
  'I can trust the system.',
]

export default function STIASPage() {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()

  async function onSubmit(data: any) {
    const stias1 = parseInt(data.stias1, 10)
    const stias2 = parseInt(data.stias2, 10)
    const stias3 = parseInt(data.stias3, 10)
    const stias_mean = parseFloat(((stias1 + stias2 + stias3) / 3).toFixed(3))

    const payload = { stias1, stias2, stias3, stias_mean }
    setSurvey(payload)
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ...payload }),
    }).catch(console.error)
    router.push('/nasa-tlx')
  }

  return (
    <PageWrapper title="Trust Rating" step={6} totalSteps={10}>
      <p className="section-note">
        Rate how you feel about the vehicle's decision-making in the clip you just watched.
        <br />
        <strong>1 = Not at all &nbsp;·&nbsp; 7 = Extremely</strong>
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <LikertMatrix
          items={STIAS_ITEMS}
          scale={7}
          namePrefix="stias"
          register={register}
          errors={errors}
        />

        {Object.keys(errors).length > 0 && (
          <p className="text-red-600 text-sm">Please answer all items before continuing.</p>
        )}

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
