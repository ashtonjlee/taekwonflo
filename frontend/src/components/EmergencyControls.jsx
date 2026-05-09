import { useMemo, useState } from 'react'

const EMERGENCY_TYPES = [
  { value: 'medical_delay', label: 'medical_delay' },
  { value: 'ring_pause', label: 'ring_pause' },
  { value: 'referee_shortage', label: 'referee_shortage' },
  { value: 'coach_conflict', label: 'coach_conflict' },
]

export default function EmergencyControls({ tournament, onSimulate, loading = false, error = null }) {
  const [emergencyType, setEmergencyType] = useState('ring_pause')
  const [currentMinute, setCurrentMinute] = useState(60)
  const [delayMinutes, setDelayMinutes] = useState(20)
  const [ringId, setRingId] = useState('')
  const [refereeCrewId, setRefereeCrewId] = useState('')
  const [coachId, setCoachId] = useState('')

  const ringOptions = tournament?.rings || []
  const refereeOptions = tournament?.referee_crews || []
  const coachOptions = tournament?.coaches || []

  const affectedField = useMemo(() => {
    if (emergencyType === 'medical_delay' || emergencyType === 'ring_pause') {
      return 'ring'
    }
    if (emergencyType === 'referee_shortage') {
      return 'referee'
    }
    if (emergencyType === 'coach_conflict') {
      return 'coach'
    }
    return null
  }, [emergencyType])

  function handleSubmit(event) {
    event.preventDefault()
    const payload = {
      emergency_type: emergencyType,
      current_minute: Number(currentMinute),
      delay_minutes: Number(delayMinutes),
      pause_duration_minutes: Number(delayMinutes),
      unavailable_duration_minutes: Number(delayMinutes),
    }

    if (emergencyType === 'medical_delay' || emergencyType === 'ring_pause') {
      payload.ring_id = ringId || undefined
    }
    if (emergencyType === 'referee_shortage') {
      payload.referee_crew_id = refereeCrewId || undefined
    }
    if (emergencyType === 'coach_conflict') {
      payload.coach_id = coachId || undefined
    }
    onSimulate(payload)
  }

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <h2 className="m-0 text-xl font-semibold">Emergency Controls</h2>
      <p className="mt-2 text-sm text-slate-600">
        Simulate disruption and re-optimize only future events.
      </p>
      <form className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2" onSubmit={handleSubmit}>
        <label className="text-sm">
          Emergency Type
          <select
            className="mt-1 w-full rounded border border-slate-300 p-2"
            value={emergencyType}
            onChange={(event) => setEmergencyType(event.target.value)}
          >
            {EMERGENCY_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm">
          Current Minute
          <input
            className="mt-1 w-full rounded border border-slate-300 p-2"
            type="number"
            value={currentMinute}
            onChange={(event) => setCurrentMinute(event.target.value)}
            min={0}
          />
        </label>

        <label className="text-sm">
          Delay / Unavailable Duration (minutes)
          <input
            className="mt-1 w-full rounded border border-slate-300 p-2"
            type="number"
            value={delayMinutes}
            onChange={(event) => setDelayMinutes(event.target.value)}
            min={1}
          />
        </label>

        {affectedField === 'ring' ? (
          <label className="text-sm">
            Ring
            <select
              className="mt-1 w-full rounded border border-slate-300 p-2"
              value={ringId}
              onChange={(event) => setRingId(event.target.value)}
            >
              <option value="">Auto-select first ring</option>
              {ringOptions.map((ring) => (
                <option key={ring.id} value={ring.id}>
                  {ring.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {affectedField === 'referee' ? (
          <label className="text-sm">
            Referee Crew
            <select
              className="mt-1 w-full rounded border border-slate-300 p-2"
              value={refereeCrewId}
              onChange={(event) => setRefereeCrewId(event.target.value)}
            >
              <option value="">Auto-select first crew</option>
              {refereeOptions.map((crew) => (
                <option key={crew.id} value={crew.id}>
                  {crew.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {affectedField === 'coach' ? (
          <label className="text-sm">
            Coach
            <select
              className="mt-1 w-full rounded border border-slate-300 p-2"
              value={coachId}
              onChange={(event) => setCoachId(event.target.value)}
            >
              <option value="">Auto-select first coach</option>
              {coachOptions.map((coach) => (
                <option key={coach.id} value={coach.id}>
                  {coach.name} ({coach.id})
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <div className="md:col-span-2">
          <button
            type="submit"
            className="rounded-md bg-amber-100 px-4 py-2 text-sm font-medium text-amber-900 disabled:opacity-50"
            disabled={loading}
          >
            {loading ? 'Running simulation...' : 'Simulate Emergency & Re-optimize'}
          </button>
        </div>
      </form>
      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
    </section>
  )
}
