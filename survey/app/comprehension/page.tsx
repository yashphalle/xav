'use client'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { getSurvey, setSurvey } from '@/lib/survey-store'
import PageWrapper from '@/components/survey/PageWrapper'

const QUESTIONS = [
  {
    name: 'comp1',
    question: 'Q1. What did the vehicle do in this clip?',
    options: [
      'Accelerated to pass through the intersection',
      'Applied sudden brakes',
      'Changed lanes to avoid the pedestrian',
      'Slowed down gradually and continued',
    ],
    correct: 'Applied sudden brakes',
  },
  {
    name: 'comp2',
    question: 'Q2. Why did the vehicle react the way it did?',
    options: [
      'A traffic light turned red',
      'Another vehicle cut in front',
      'A pedestrian was in the vehicle\'s path',
      'There was a stop sign ahead',
    ],
    correct: "A pedestrian was in the vehicle's path",
  },
  {
    name: 'comp3',
    question: 'Q3. How would you describe the vehicle\'s response?',
    options: [
      'It did not react and continued at speed',
      'It honked and slowed slightly',
      'It swerved into the adjacent lane',
      'It braked quickly to avoid the pedestrian',
    ],
    correct: 'It braked quickly to avoid the pedestrian',
  },
]

export default function ComprehensionPage() {
  const router = useRouter()
  const { register, handleSubmit, formState: { errors } } = useForm()

  async function onSubmit(data: any) {
    const comp1_correct = data.comp1 === QUESTIONS[0].correct
    const comp2_correct = data.comp2 === QUESTIONS[1].correct
    const comp3_correct = data.comp3 === QUESTIONS[2].correct
    const comp_score = [comp1_correct, comp2_correct, comp3_correct].filter(Boolean).length
    const comp_fail = comp_score < 1

    const payload = {
      comp1: data.comp1, comp2: data.comp2, comp3: data.comp3,
      comp1_correct, comp2_correct, comp3_correct,
      comp_score, comp_fail,
    }
    setSurvey(payload)
    await fetch('/api/response', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: getSurvey().participant_id, ...payload }),
    }).catch(console.error)
    router.push('/s-tias')
  }

  return (
    <PageWrapper title="Comprehension Check" step={5} totalSteps={10}>
      <p className="text-gray-500 text-sm mb-6">
        Based on the clip you just watched, answer the following questions.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-7">
        {QUESTIONS.map(({ name, question, options }) => (
          <div key={name}>
            <p className="section-title">{question}</p>
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
            {errors[name] && <p className="field-error">{String((errors[name] as any).message)}</p>}
          </div>
        ))}

        <div className="pt-2">
          <button type="submit" className="btn-primary">Continue →</button>
        </div>
      </form>
    </PageWrapper>
  )
}
