'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'
import LikertMatrix from '@/components/survey/LikertMatrix'

const PT_ITEMS = [
  'I usually trust machines until there is a reason not to.',
  'My tendency to trust machines is high.',
  'It is easy for me to trust machines to do their job.',
  'I generally give machines the benefit of the doubt.',
  'I am comfortable relying on machines for important tasks.',
  'Trusting machines comes naturally to me.',
]

const AV_ITEMS = [
  'Autonomous vehicles can make driving safer overall.',
  'I feel comfortable with the idea of riding in a self-driving car.',
  'The benefits of autonomous vehicles outweigh the risks.',
]

export default function BaselineTrustPage() {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()

  async function onSubmit(data: any) {
    // Parse all values as numbers
    const payload: Record<string, number> = {}
    for (const [k, v] of Object.entries(data)) {
      payload[k] = parseInt(v as string, 10)
    }
    setSurvey(payload)
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ...payload }),
    }).catch(console.error)
    router.push('/instructions')
  }

  return (
    <PageWrapper title="General Attitudes" step={2} totalSteps={10}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">

        {/* Section A — Propensity to Trust */}
        <div>
          <p className="section-title">Section A: Trust in Machines</p>
          <p className="section-note">
            Rate how much you agree with each statement.&nbsp;
            <strong>1 = Strongly Disagree &nbsp;·&nbsp; 5 = Strongly Agree</strong>
          </p>
          <LikertMatrix
            items={PT_ITEMS}
            scale={5}
            namePrefix="pt"
            register={register}
            errors={errors}
          />
        </div>

        {/* Section B — AV Attitudes */}
        <div>
          <p className="section-title">Section B: Autonomous Vehicle Attitudes</p>
          <p className="section-note">
            Rate your agreement before watching any clips.&nbsp;
            <strong>1 = Strongly Disagree &nbsp;·&nbsp; 7 = Strongly Agree</strong>
          </p>
          <LikertMatrix
            items={AV_ITEMS}
            scale={7}
            namePrefix="av"
            register={register}
            errors={errors}
          />
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
