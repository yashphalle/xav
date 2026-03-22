'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

interface FormData {
  mental_model_text: string
  mental_model_text2: string
}

export default function MentalModelPage() {
  const router = useRouter()
  const { register, handleSubmit, watch, formState: { errors } } = useForm<FormData>()
  const charCount = watch('mental_model_text', '').length

  async function onSubmit(data: FormData) {
    setSurvey({ mental_model_text: data.mental_model_text, mental_model_text2: data.mental_model_text2 })
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        participant_id: getSurvey().participant_id,
        mental_model_text: data.mental_model_text,
        mental_model_text2: data.mental_model_text2,
      }),
    }).catch(console.error)
    router.push('/jian-trust')
  }

  return (
    <PageWrapper title="Your Understanding" step={8} totalSteps={10}>
      <p className="text-gray-500 text-sm mb-6">
        There are no right or wrong answers — we want your genuine understanding.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {/* Primary question */}
        <div>
          <label className="section-title block mb-2">
            In your own words, explain why you think the vehicle acted the way it did in this clip.
          </label>
          <textarea
            {...register('mental_model_text', {
              })}
            rows={5}
            placeholder="Describe what you think the vehicle was 'thinking'…"
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
          <div className="flex justify-between mt-1">
            {errors.mental_model_text ? (
              <p className="field-error">{String(errors.mental_model_text.message)}</p>
            ) : (
              <span />
            )}
            <span className="text-xs text-gray-400">{charCount} chars</span>
          </div>
        </div>

        {/* Optional secondary question */}
        <div>
          <label className="section-title block mb-1">
            What information do you think the vehicle used to make this decision?
          </label>
          <p className="text-xs text-gray-400 mb-2">Optional</p>
          <textarea
            {...register('mental_model_text2')}
            rows={3}
            placeholder="Optional — sensor data, camera feeds, etc."
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
