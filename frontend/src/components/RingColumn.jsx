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
  isExpanded = false,
  onExpandToggle = () => {},
  ringDelayTotals = { rescheduled: 0, delayMinutes: 0 },
  validationPassed = true,
  operationalHint = null,
  matchHintByEventId = {},
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
  const progEvent = sortedEvents.find((event) => isEventInProgress(event, currentMinute))
  const displayRemaining =
    operationalHint != null && typeof operationalHint.remaining_event_count === 'number'
      ? operationalHint.remaining_event_count
      : remainingEvents
  const opsRescheduled =
    operationalHint?.material_reschedule_count ?? operationalHint?.rescheduled_division_events ?? 0
  const opsDelayMinutes =
    typeof operationalHint?.total_delay_minutes === 'number' ? operationalHint.total_delay_minutes : null

  const progMatchHint = progEvent ? matchHintByEventId[progEvent.event_id] : null
  const resolvedNextEvt = nextEvent
  const primaryLine = progEvent
    ? `Current: ${progEvent.division_name || progEvent.division}${
        progMatchHint !== undefined ? ` · Match ${progMatchHint}` : ''
      }`
    : (() => {
        const nm =
          operationalHint?.next_division_name ||
          resolvedNextEvt?.division_name ||
          resolvedNextEvt?.division ||
          null
        const mh =
          operationalHint?.next_match_number ??
          (resolvedNextEvt ? matchHintByEventId[resolvedNextEvt.event_id] : undefined)
        if (nm) {
          const prefix = operationalHint?.idle ? 'Idle · Next:' : 'Next:'
          const clockBit =
            resolvedNextEvt != null
              ? ` at ${formatMinuteAsClock(resolvedNextEvt.start_minute, tournamentStartTime)}`
              : ''
          const matchBit =
            mh !== undefined && mh !== null ? ` · Match ${mh}` : ''
          return `${prefix} ${nm}${matchBit}${clockBit}`
        }
        if (operationalHint?.idle === true || sortedEvents.length === 0) {
          return 'Idle · No upcoming division on this ring'
        }
        return 'No future calls'
      })()

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

  const delayBits = []
  if (ringDelayTotals.rescheduled > 0) {
    delayBits.push(`${ringDelayTotals.rescheduled} moved`)
    if (ringDelayTotals.delayMinutes > 0) {
      delayBits.push(`+${ringDelayTotals.delayMinutes} min`)
    }
  }

  return (
    <div
      className={`min-h-fit rounded-xl border bg-white shadow-sm transition-all duration-300 ${
        hasChangedEvents ? 'border-amber-300 shadow-amber-100' : 'border-slate-200'
      } ${isExpanded ? 'p-3 hover:shadow-md' : ''}`}
    >
      <button
        type="button"
        onClick={onExpandToggle}
        aria-expanded={isExpanded}
        className={`flex w-full items-start gap-3 text-left ${
          isExpanded ? 'rounded-lg pb-3' : 'rounded-xl p-3 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-400'
        }`}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="m-0 text-sm font-semibold text-slate-900">{ringName}</h4>
            <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${ringStatusClass}`}>
              {ringStatus}
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              {isExpanded ? 'Collapse' : 'Expand'}
            </span>
          </div>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-600">{primaryLine}</p>
          {!isExpanded ? (
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-600">
              <span>
                <span className="font-semibold text-slate-900">{sortedEvents.length}</span> events
              </span>
              <span>
                <span className="font-semibold text-slate-900">{displayRemaining}</span> remaining events
              </span>
              {opsDelayMinutes !== null ? (
                <span>
                  Ops delay <span className="font-semibold text-slate-900">{opsDelayMinutes}m</span>
                </span>
              ) : delayBits.length > 0 ? (
                <span className={`font-semibold ${hasDelayed ? 'text-rose-700' : 'text-slate-900'}`}>
                  {delayBits.join(' • ')}
                </span>
              ) : (
                <span className="text-slate-500">No reschedule delta</span>
              )}
              <span className={`font-semibold ${opsRescheduled ? 'text-amber-700' : 'text-slate-500'}`}>
                {opsRescheduled} rescheduled shifts
              </span>
              <span className={`font-semibold ${validationPassed ? 'text-emerald-700' : 'text-rose-700'}`}>
                Audit {validationPassed ? 'passed' : 'failed'}
              </span>
            </div>
          ) : null}
        </div>
        {!isExpanded ? (
          <div className="shrink-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-center text-[11px] text-slate-600">
            <div className="font-semibold text-slate-950">{sortedEvents.length}</div>
            <div>slots</div>
          </div>
        ) : null}
      </button>

      {isExpanded ? (
        <div className="border-t border-slate-100 pt-3">
          <div className="mb-3 grid grid-cols-3 gap-2 rounded-md border border-slate-200 bg-slate-50 p-2 text-center text-[11px] text-slate-600">
            <div>
              <div className="font-semibold text-slate-950">{sortedEvents.length}</div>
              <div>events</div>
            </div>
            <div>
              <div className="font-semibold text-slate-950">{displayRemaining}</div>
              <div>left</div>
            </div>
            <div>
              <div className="font-semibold text-slate-950">
                {nextEvent ? formatTournamentMinute(nextEvent.start_minute) : '-'}
              </div>
              <div>next</div>
            </div>
          </div>
          <div className="flex flex-col gap-2">
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
                  coordinationMatchNumber={matchHintByEventId[event.event_id]}
                />
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
