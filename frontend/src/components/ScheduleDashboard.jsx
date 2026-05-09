import RingColumn from './RingColumn'

function getMakespan(schedule = []) {
  const allEvents = schedule.flatMap((ring) => ring.events || [])
  if (allEvents.length === 0) {
    return 0
  }
  return Math.max(...allEvents.map((event) => event.end_minute ?? 0))
}

export default function ScheduleDashboard({
  originalSchedule = [],
  currentSchedule = [],
  changedEvents = [],
  validation = null,
  emergencySummary = null,
}) {
  const changedEventMap = Object.fromEntries(changedEvents.map((event) => [event.event_id, event]))
  const beforeMakespan = getMakespan(originalSchedule)
  const afterMakespan = getMakespan(currentSchedule)
  const affected = emergencySummary?.affectedResource || 'N/A'

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <h2 className="m-0 text-xl font-semibold">Schedule Dashboard</h2>
      <p className="mt-2 text-sm text-slate-600">
        Compare the original schedule to the current re-optimized schedule.
      </p>

      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm">
        <div className="font-semibold text-slate-800">Comparison Summary</div>
        <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
          <div>Changed events: {changedEvents.length}</div>
          <div>Validation: {validation?.valid ? 'Passed' : 'Failed'}</div>
          <div>
            Makespan: {beforeMakespan} → {afterMakespan}
          </div>
          <div>
            Emergency: {emergencySummary?.emergency_type || 'none'} ({affected})
          </div>
        </div>
        {emergencySummary && changedEvents.length === 0 ? (
          <p className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-amber-900">
            No schedule changes were needed because the selected disruption did not affect any future events.
          </p>
        ) : null}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {currentSchedule.map((ring) => (
          <RingColumn
            key={ring.ring_id}
            ringName={ring.ring_name}
            events={ring.events}
            changedEventMap={changedEventMap}
          />
        ))}
      </div>
    </section>
  )
}
