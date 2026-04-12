export type Condition = 'none' | 'template' | 'vlm_descriptive' | 'vlm_teleological'
export type Criticality = 'HIGH' | 'MEDIUM' | 'LOW'

export interface ComprehensionQuestion {
  name: 'comp1' | 'comp2' | 'comp3'
  question: string
  options: [string, string, string, string]
  correct: string
}

export interface ScenarioConfig {
  id: string
  label: string
  criticality: Criticality
  /** One YouTube video ID per condition. Use 'PLACEHOLDER' until uploaded. */
  video_ids: Record<Condition, string>
  comprehension: ComprehensionQuestion[]
}

export const CONDITIONS: Condition[] = [
  'none',
  'template',
  'vlm_descriptive',
  'vlm_teleological',
]

export const SCENARIOS: ScenarioConfig[] = [
  // ── 0 ──────────────────────────────────────────────────────────────────────
  {
    id: 'S1_JaywalkingAdult',
    label: 'Urban Intersection',
    criticality: 'HIGH',
    video_ids: {
      none:             'PLACEHOLDER_S1_NONE',
      template:         'PLACEHOLDER_S1_TEMPLATE',
      vlm_descriptive:  't9xGuX40Ks8',   // existing recording
      vlm_teleological: 'PLACEHOLDER_S1_TELEOLOGICAL',
    },
    comprehension: [
      {
        name: 'comp1',
        question: 'Q1. What hazard did the vehicle detect in this clip?',
        options: [
          'A cyclist running a red light',
          'A pedestrian crossing mid-block outside the crosswalk',
          'A delivery truck blocking the lane',
          'A traffic signal malfunction',
        ],
        correct: 'A pedestrian crossing mid-block outside the crosswalk',
      },
      {
        name: 'comp2',
        question: 'Q2. How did the vehicle respond?',
        options: [
          'It accelerated to pass before the pedestrian',
          'It applied sudden brakes',
          'It changed lanes to avoid the pedestrian',
          'It honked and continued at reduced speed',
        ],
        correct: 'It applied sudden brakes',
      },
      {
        name: 'comp3',
        question: 'Q3. How would you describe the vehicle\'s reaction timing?',
        options: [
          'It did not react at all',
          'It reacted only after the pedestrian was directly in front',
          'It reacted preemptively as the pedestrian entered the road',
          'It reacted but only after a significant delay',
        ],
        correct: 'It reacted preemptively as the pedestrian entered the road',
      },
    ],
  },

  // ── 1 ──────────────────────────────────────────────────────────────────────
  {
    id: 'S2_SuddenStopEvasion',
    label: 'Highway Sudden Stop',
    criticality: 'HIGH',
    video_ids: {
      none:             'PLACEHOLDER_S2_NONE',
      template:         'PLACEHOLDER_S2_TEMPLATE',
      vlm_descriptive:  'PLACEHOLDER_S2_DESCRIPTIVE',
      vlm_teleological: 'PLACEHOLDER_S2_TELEOLOGICAL',
    },
    comprehension: [
      {
        name: 'comp1',
        question: 'Q1. What event prompted the vehicle\'s action?',
        options: [
          'A traffic light turned red suddenly',
          'The vehicle ahead braked without warning',
          'A cyclist swerved into the lane',
          'There was a pothole in the road',
        ],
        correct: 'The vehicle ahead braked without warning',
      },
      {
        name: 'comp2',
        question: 'Q2. What did the autonomous vehicle do in response?',
        options: [
          'It swerved into the oncoming lane',
          'It applied emergency braking',
          'It maintained speed and used the horn',
          'It gradually decelerated and merged right',
        ],
        correct: 'It applied emergency braking',
      },
      {
        name: 'comp3',
        question: 'Q3. Which best describes the gap between vehicles before and after the event?',
        options: [
          'The gap stayed roughly the same',
          'The gap increased as the AV pulled ahead',
          'The gap shrank dangerously before the AV braked',
          'There was no leading vehicle visible',
        ],
        correct: 'The gap shrank dangerously before the AV braked',
      },
    ],
  },

  // ── 2 ──────────────────────────────────────────────────────────────────────
  {
    id: 'S4_EmergencyVehiclePullOver',
    label: 'Emergency Vehicle Yield',
    criticality: 'MEDIUM',
    video_ids: {
      none:             'PLACEHOLDER_S4_NONE',
      template:         'PLACEHOLDER_S4_TEMPLATE',
      vlm_descriptive:  'PLACEHOLDER_S4_DESCRIPTIVE',
      vlm_teleological: 'PLACEHOLDER_S4_TELEOLOGICAL',
    },
    comprehension: [
      {
        name: 'comp1',
        question: 'Q1. What type of vehicle triggered the AV\'s action?',
        options: [
          'A police car on a routine patrol',
          'An ambulance or fire truck with sirens active',
          'A construction vehicle',
          'A school bus with flashing lights',
        ],
        correct: 'An ambulance or fire truck with sirens active',
      },
      {
        name: 'comp2',
        question: 'Q2. What did the autonomous vehicle do?',
        options: [
          'It stopped immediately in the middle of the lane',
          'It accelerated to clear the road faster',
          'It moved toward the curb and slowed to yield',
          'It changed to the left lane to give way',
        ],
        correct: 'It moved toward the curb and slowed to yield',
      },
      {
        name: 'comp3',
        question: 'Q3. What happened after the emergency vehicle passed?',
        options: [
          'It turned on hazard lights and waited',
          'It resumed normal speed',
          'It parked and powered down',
          'It was still pulled over at the end of the clip',
        ],
        correct: 'It resumed normal speed',
      },
    ],
  },

  // ── 3 ──────────────────────────────────────────────────────────────────────
  {
    id: 'S5v2_HiddenCyclist',
    label: 'Hidden Cyclist',
    criticality: 'HIGH',
    video_ids: {
      none:             'PLACEHOLDER_S5V2_NONE',
      template:         'PLACEHOLDER_S5V2_TEMPLATE',
      vlm_descriptive:  'PLACEHOLDER_S5V2_DESCRIPTIVE',
      vlm_teleological: 'PLACEHOLDER_S5V2_TELEOLOGICAL',
    },
    comprehension: [
      {
        name: 'comp1',
        question: 'Q1. What made this scenario particularly challenging for the vehicle?',
        options: [
          'The road was icy and slippery',
          'The cyclist emerged from an occluded area between parked cars',
          'The cyclist was travelling at high speed on the main road',
          'Sun glare obscured the sensors',
        ],
        correct: 'The cyclist emerged from an occluded area between parked cars',
      },
      {
        name: 'comp2',
        question: 'Q2. What did the vehicle do when the cyclist appeared?',
        options: [
          'It swerved fully into the opposite lane',
          'It continued at speed, relying on the cyclist to avoid it',
          'It braked sharply and steered slightly away',
          'It stopped completely and waited',
        ],
        correct: 'It braked sharply and steered slightly away',
      },
      {
        name: 'comp3',
        question: 'Q3. Which word best describes the nature of this hazard?',
        options: [
          'Predictable — the cyclist followed traffic rules',
          'Ambiguous — the cyclist\'s path was unclear',
          'Occluded — the cyclist was hidden until the last moment',
          'Deliberate — the cyclist was testing the vehicle',
        ],
        correct: 'Occluded — the cyclist was hidden until the last moment',
      },
    ],
  },

  // ── 4 ──────────────────────────────────────────────────────────────────────
  {
    id: 'L3_NarrowStreetNav',
    label: 'Narrow Street Navigation',
    criticality: 'LOW',
    video_ids: {
      none:             'PLACEHOLDER_L3_NONE',
      template:         'PLACEHOLDER_L3_TEMPLATE',
      vlm_descriptive:  'PLACEHOLDER_L3_DESCRIPTIVE',
      vlm_teleological: 'PLACEHOLDER_L3_TELEOLOGICAL',
    },
    comprehension: [
      {
        name: 'comp1',
        question: 'Q1. What driving challenge did the vehicle face in this clip?',
        options: [
          'A flooded road section',
          'Navigating a narrow street with parked cars on both sides',
          'A sudden detour due to road works',
          'A sharp blind corner at speed',
        ],
        correct: 'Navigating a narrow street with parked cars on both sides',
      },
      {
        name: 'comp2',
        question: 'Q2. How did the autonomous vehicle handle the narrow passage?',
        options: [
          'It stopped and waited for assistance',
          'It accelerated through the gap quickly',
          'It slowed down and carefully navigated through',
          'It reversed and found a different route',
        ],
        correct: 'It slowed down and carefully navigated through',
      },
      {
        name: 'comp3',
        question: 'Q3. Which best describes the vehicle\'s overall behavior in this clip?',
        options: [
          'Erratic — it made multiple unnecessary maneuvers',
          'Cautious and deliberate — it prioritized safety over speed',
          'Aggressive — it forced a path through',
          'Indecisive — it started and stopped multiple times',
        ],
        correct: 'Cautious and deliberate — it prioritized safety over speed',
      },
    ],
  },
]

/** Return the scenario config for a given display index using the stored order */
export function getScenarioForIndex(
  scenarioOrder: number[],
  displayIndex: number
): ScenarioConfig {
  return SCENARIOS[scenarioOrder[displayIndex]]
}

/** Shuffle array indices 0..n-1 */
export function shuffleIndices(n: number): number[] {
  const arr = Array.from({ length: n }, (_, i) => i)
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}
