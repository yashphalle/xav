'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

interface FormData {
  desktop: string
  audio_ok: string
}

export default function TechCheckPage() {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm<FormData>()

  function onSubmit(data: FormData) {
    if (data.desktop === 'no' && data.desktop !== undefined) {
      setSurvey({ exclude_mobile: true })
      router.push('/screen-out')
      return
    }
    setSurvey({ audio_ok: data.audio_ok === 'yes', exclude_mobile: false })
    fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        participant_id: getSurvey().participant_id,
        audio_ok: data.audio_ok === 'yes',
        exclude_mobile: false,
      }),
    }).catch(console.error)
    router.push('/demographics')
  }

  return (
    <PageWrapper title="Before We Begin">
      <p className="text-gray-600 mb-6">Please confirm the following before we start.</p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {/* Q1 */}
        <div>
          <p className="section-title">
            Q1. I am completing this study on a desktop or laptop computer.
          </p>
          <div className="mt-2 space-y-2">
            {[
              { value: 'yes', label: 'Yes' },
              { value: 'no', label: 'No' },
            ].map(({ value, label }) => (
              <label key={value} className="radio-row">
                <input
                  type="radio"
                  value={value}
                  {...register('desktop')}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="text-sm text-gray-700">{label}</span>
              </label>
            ))}
          </div>
          {errors.desktop && <p className="field-error">{errors.desktop.message}</p>}
        </div>

        {/* Q2 */}
        <div>
          <p className="section-title">
            Q2. I am able to hear audio through speakers or headphones.
          </p>
          <div className="mt-2 space-y-2">
            {[
              { value: 'yes', label: 'Yes' },
              { value: 'no', label: 'No' },
            ].map(({ value, label }) => (
              <label key={value} className="radio-row">
                <input
                  type="radio"
                  value={value}
                  {...register('audio_ok')}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="text-sm text-gray-700">{label}</span>
              </label>
            ))}
          </div>
          {errors.audio_ok && <p className="field-error">{errors.audio_ok.message}</p>}
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">
            Continue →
          </button>
        </div>
      </form>
    </PageWrapper>
  )
}
