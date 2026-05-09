import RingColumn from './RingColumn'
import { formatDuration, formatMinuteAsClock, formatMinuteRange } from '../utils/timeline'

function getMakespan(schedule = []) {
  const allEvents = schedule.flatMap((ring) => ring.events || [])
  if (allEvents.length === 0) {
    return 0
  }
  return Math.max(...allEvents.map((event) => event.end_minute ?? 0))
}

function getAllEvents(schedule = []) {
  return schedule
    .flatMap((ring) =>
      (ring.events || []).map((event) => ({
        ...event,
        ring_id: event.ring_id || ring.ring_id,
        ring_name: event.ring_name || ring.ring_name,
      })),
    )
    .sort((first, second) => (first.start_minute ?? 0) - (second.start_minute ?? 0))
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
  const currentMinute = emergencySummary?.current_minute ?? 60
  const emergencyDuration = emergencySummary?.duration_minutes
  const allEvents = getAllEvents(currentSchedule)
  const activeEvents = allEvents.filter(
    (event) => event.start_minute <= currentMinute && currentMinute < event.end_minute,
  )
  const stagingQueue = allEvents
    .filter((event) => event.start_minute >= currentMinute)
    .slice(0, 6)
  const delayedEvents = changedEvents.filter((event) => event.new_start_minute > event.original_start_minute)
  const makespanDelta = afterMakespan - beforeMakespan
  const validationPassed = validation?.valid !== false
  const emergencyLabel = emergencySummary?.emergency_type || 'none'

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Live operations</p>
          <h2 className="m-0 mt-1 text-2xl font-bold text-slate-950">Schedule Dashboard</h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Monitor ring status, staging calls, and the impact of emergency re-optimization.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4 lg:min-w-[520px]">
          <SummaryTile label="Now" value={formatMinuteAsClock(currentMinute)} tone="blue" />
          <SummaryTile label="Active" value={activeEvents.length} tone="emerald" />
          <SummaryTile
            label="Changed"
            value={changedEvents.length}
            tone={changedEvents.length > 0 ? 'amber' : 'slate'}
          />
          <SummaryTile
            label="Validation"
            value={validationPassed ? 'Passed' : 'Failed'}
            tone={validationPassed ? 'emerald' : 'rose'}
          />
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="font-semibold text-slate-900">Operations Summary</div>
              <div className="mt-1 text-xs text-slate-500">Original schedule compared with current ring plan.</div>
            </div>
            <span
              className={`w-fit rounded px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${
                emergencySummary ? 'bg-amber-100 text-amber-900' : 'bg-slate-200 text-slate-700'
              }`}
            >
              {emergencyLabel}
            </span>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
            <Metric
              label="Finish time"
              value={formatMinuteAsClock(afterMakespan)}
              detail={`${formatDuration(0, afterMakespan)} total`}
            />
            <Metric
              label="Makespan delta"
              value={`${makespanDelta > 0 ? '+' : ''}${makespanDelta} min`}
              detail={`${beforeMakespan} -> ${afterMakespan} tournament minutes`}
              tone={makespanDelta > 0 ? 'rose' : 'emerald'}
            />
            <Metric
              label="Delayed events"
              value={delayedEvents.length}
              detail={`${changedEvents.length} total changes`}
              tone={delayedEvents.length > 0 ? 'amber' : 'slate'}
            />
          </div>
          <div className="mt-4 rounded-md border border-slate-200 bg-white p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Emergency impact</div>
            <div className="mt-2 grid grid-cols-1 gap-2 text-slate-700 md:grid-cols-4">
              <div>
                Affected: <span className="font-medium text-slate-950">{affected}</span>
              </div>
              <div>
                Current minute: <span className="font-medium text-slate-950">T+{currentMinute}</span>
              </div>
              <div>
                Active events frozen: <span className="font-medium text-slate-950">{activeEvents.length}</span>
              </div>
              <div>
                Duration:{' '}
                <span className="font-medium text-slate-950">
                  {emergencyDuration ? `${emergencyDuration} min` : 'N/A'}
                </span>
              </div>
            </div>
          </div>
          {emergencySummary && changedEvents.length === 0 ? (
            <p className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-amber-900">
              No schedule changes were needed because the selected disruption did not affect any future events.
            </p>
          ) : null}
        </div>

        <div className="rounded-lg border border-blue-100 bg-blue-50 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-blue-950">Staging Queue</div>
              <div className="mt-1 text-xs text-blue-800">Next calls after {formatMinuteAsClock(currentMinute)}.</div>
            </div>
            <span className="rounded bg-white px-2 py-1 text-xs font-semibold text-blue-800">
              {stagingQueue.length} ready
            </span>
          </div>
          <div className="mt-3 space-y-2">
            {stagingQueue.length === 0 ? (
              <p className="rounded border border-blue-100 bg-white p-3 text-sm text-blue-800">
                No upcoming events in the staging window.
              </p>
            ) : (
              stagingQueue.map((event, index) => (
                <div
                  key={`${event.event_id || event.id}-${index}`}
                  className="grid grid-cols-[3rem_1fr] gap-3 rounded-md border border-blue-100 bg-white p-3 text-sm"
                >
                  <div className="text-xs font-semibold uppercase text-blue-700">#{index + 1}</div>
                  <div>
                    <div className="font-semibold text-slate-900">
                      {event.division_name || event.division || 'Unknown division'}
                    </div>
                    <div className="mt-1 text-xs text-slate-600">
                      {formatMinuteRange(event.start_minute, event.end_minute)} - {event.ring_name || event.ring_id}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {currentSchedule.map((ring) => (
          <RingColumn
            key={ring.ring_id}
            ringId={ring.ring_id}
            ringName={ring.ring_name}
            events={ring.events}
            changedEventMap={changedEventMap}
            currentMinute={currentMinute}
            emergencySummary={emergencySummary}
          />
        ))}
      </div>
    </section>
  )
}

function SummaryTile({ label, value, tone = 'slate' }) {
  const toneClass = {
    amber: 'border-amber-200 bg-amber-50 text-amber-950',
    blue: 'border-blue-200 bg-blue-50 text-blue-950',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-950',
    rose: 'border-rose-200 bg-rose-50 text-rose-950',
    slate: 'border-slate-200 bg-slate-50 text-slate-950',
  }[tone]

  return (
    <div className={`rounded-lg border p-3 ${toneClass}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-lg font-bold">{value}</div>
    </div>
  )
}

function Metric({ label, value, detail, tone = 'slate' }) {
  const valueClass = {
    amber: 'text-amber-800',
    emerald: 'text-emerald-800',
    rose: 'text-rose-800',
    slate: 'text-slate-950',
  }[tone]

  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-bold ${valueClass}`}>{value}</div>
      <div className="mt-1 text-xs text-slate-500">{detail}</div>
    </div>
  )
}
