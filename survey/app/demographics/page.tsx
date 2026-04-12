'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

const AGE_OPTIONS = ['18–24', '25–34', '35–44', '45–54', '55+']
const GENDER_OPTIONS = ['Man', 'Woman', 'Non-binary / third gender', 'Prefer not to say']
const EDUCATION_OPTIONS = [
  'High school diploma or equivalent',
  'Some college, no degree',
  "Bachelor's degree",
  'Graduate degree (Master\'s, PhD, etc.)',
]
const LICENSE_OPTIONS = ['Yes', 'No']
const DRIVE_YEARS_OPTIONS = ['0 (do not drive)', '1–5 years', '6–15 years', '16+ years']
const DRIVE_FREQ_OPTIONS = ['Daily', 'A few times a week', 'Rarely', 'Never']
const AV_EXP_OPTIONS = [
  'Yes, fully autonomous (e.g., Waymo)',
  'Yes, semi-autonomous (e.g., Tesla Autopilot)',
  'No',
]

interface FormData {
  age: string
  gender: string
  education: string
  license: string
  drive_years: string
  drive_freq: string
  av_exp: string
  av_familiarity: string
}

function RadioGroup({
  label,
  name,
  options,
  register,
  error,
}: {
  label: string
  name: keyof FormData
  options: string[]
  register: any
  error?: any
}) {
  return (
    <div>
      <p className="section-title">{label}</p>
      <div className="mt-2 space-y-2">
        {options.map((opt) => (
          <label key={opt} className="radio-row">
            <input
              type="radio"
              value={opt}
              {...register(name)}
              className="w-4 h-4 text-blue-600"
            />
            <span className="text-sm text-gray-700">{opt}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

export default function DemographicsPage() {
  const router = useRouter()
  const { register, handleSubmit, watch, formState: { errors } } = useForm<FormData>()
  const avFamiliarity = watch('av_familiarity', '4')

  async function onSubmit(data: FormData) {
    const payload = { ...data, av_familiarity: parseInt(data.av_familiarity, 10) }
    setSurvey(payload)
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ...payload }),
    }).catch(console.error)
    router.push('/baseline-trust')
  }

  return (
    <PageWrapper title="About You" step={1} totalSteps={10}>
      <p className="text-gray-500 text-sm mb-6">All questions are required.</p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <RadioGroup label="Q1. What is your age?" name="age" options={AGE_OPTIONS} register={register} error={errors.age} />
        <RadioGroup label="Q2. What is your gender?" name="gender" options={GENDER_OPTIONS} register={register} error={errors.gender} />
        <RadioGroup label="Q3. What is your highest level of education?" name="education" options={EDUCATION_OPTIONS} register={register} error={errors.education} />
        <RadioGroup label="Q4. Do you hold a valid driver's license?" name="license" options={LICENSE_OPTIONS} register={register} error={errors.license} />
        <RadioGroup label="Q5. How many years have you been driving?" name="drive_years" options={DRIVE_YEARS_OPTIONS} register={register} error={errors.drive_years} />
        <RadioGroup label="Q6. How often do you currently drive?" name="drive_freq" options={DRIVE_FREQ_OPTIONS} register={register} error={errors.drive_freq} />
        <RadioGroup label="Q7. Have you ever ridden in an autonomous or semi-autonomous vehicle?" name="av_exp" options={AV_EXP_OPTIONS} register={register} error={errors.av_exp} />

        {/* Q8 — Slider */}
        <div>
          <p className="section-title">Q8. How familiar are you with autonomous vehicle technology?</p>
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-4">
              <span className="text-xs text-gray-500 w-28 text-right shrink-0">Not at all familiar</span>
              <input
                type="range"
                min={1}
                max={7}
                step={1}
                defaultValue={4}
                {...register('av_familiarity')}
                className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
              />
              <span className="text-xs text-gray-500 w-28 shrink-0">Very familiar</span>
            </div>
            <p className="text-center text-sm font-semibold text-blue-700">
              {avFamiliarity ?? 4} / 7
            </p>
          </div>
        </div>

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
