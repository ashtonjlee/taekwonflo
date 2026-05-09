import EventCard from './EventCard'
import { formatMinuteAsClock, formatTournamentMinute, isEventInProgress } from '../utils/timeline'

function isAffectedRing(emergencySummary, ringId, ringName) {
  const affected = emergencySummary?.affectedResource
  if (!affected) {
    return false
  }
  return affected === ringId || affected === ringName
}

export default function RingColumn({
  ringId,
  ringName,
  events = [],
  changedEventMap = {},
  currentMinute = 60,
  emergencySummary = null,
  onSelectDivision,
  tournamentStartTime = '09:00',
}) {
  const sortedEvents = [...events].sort((first, second) => (first.start_minute ?? 0) - (second.start_minute ?? 0))
  const hasInProgress = sortedEvents.some((event) => isEventInProgress(event, currentMinute))
  const hasDelayed = events.some((event) => {
    const changeInfo = changedEventMap[event.event_id]
    return changeInfo && changeInfo.new_start_minute > changeInfo.original_start_minute
  })
  const isRingEmergency = ['medical_delay', 'ring_pause'].includes(emergencySummary?.emergency_type)
  const isPaused = isRingEmergency && isAffectedRing(emergencySummary, ringId, ringName)
  const hasChangedEvents = sortedEvents.some((event) => changedEventMap[event.event_id])
  const nextEvent = sortedEvents.find((event) => event.start_minute >= currentMinute)
  const remainingEvents = sortedEvents.filter((event) => event.end_minute > currentMinute).length

  let ringStatus = 'idle'
  let ringStatusClass = 'bg-slate-100 text-slate-700 ring-1 ring-slate-200'
  if (isPaused) {
    ringStatus = 'paused'
    ringStatusClass = 'bg-purple-100 text-purple-800 ring-1 ring-purple-200'
  } else if (hasDelayed) {
    ringStatus = 'delayed'
    ringStatusClass = 'bg-rose-100 text-rose-800 ring-1 ring-rose-200'
  } else if (hasInProgress) {
    ringStatus = 'in progress'
    ringStatusClass = 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200'
  }

  return (
    <div
      className={`min-h-64 rounded-xl border bg-white p-3 shadow-sm transition-all duration-300 hover:shadow-md ${
        hasChangedEvents ? 'border-amber-300 shadow-amber-100' : 'border-slate-200'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h4 className="m-0 text-sm font-semibold text-slate-900">{ringName}</h4>
          <p className="mt-0.5 text-xs text-slate-500">
            {nextEvent
              ? `Next: ${nextEvent.division_name || nextEvent.division || 'event'} at ${formatMinuteAsClock(
                  nextEvent.start_minute,
                  tournamentStartTime,
                )}`
              : 'No future calls'}
          </p>
        </div>
        <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${ringStatusClass}`}>
          {ringStatus}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 rounded-md border border-slate-200 bg-slate-50 p-2 text-center text-[11px] text-slate-600">
        <div>
          <div className="font-semibold text-slate-950">{sortedEvents.length}</div>
          <div>events</div>
        </div>
        <div>
          <div className="font-semibold text-slate-950">{remainingEvents}</div>
          <div>left</div>
        </div>
        <div>
          <div className="font-semibold text-slate-950">
            {nextEvent ? formatTournamentMinute(nextEvent.start_minute) : '-'}
          </div>
          <div>next</div>
        </div>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        {sortedEvents.length === 0 ? (
          <p className="text-xs text-slate-500">No events assigned yet.</p>
        ) : (
          sortedEvents.map((event) => (
            <EventCard
              key={event.event_id || event.id}
              event={event}
              changeInfo={changedEventMap[event.event_id]}
              currentMinute={currentMinute}
              isPaused={isPaused && event.end_minute > currentMinute}
              onSelectDivision={onSelectDivision}
              tournamentStartTime={tournamentStartTime}
            />
          ))
        )}
      </div>
    </div>
  )
}
