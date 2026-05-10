import { useMemo, useState } from 'react'
import EventCard from './EventCard'
import { formatMinuteAsClock, formatTournamentMinute, isEventCompleted, isEventInProgress } from '../utils/timeline'
import { ringIsInsideLunch, ringLunchSpan } from '../utils/lunch'

function isAffectedRing(emergencySummary, ringId, ringName) {
  const affected = emergencySummary?.affectedResource
  if (!affected) {
    return false
  }
  return affected === ringId || affected === ringName
}

function changeBadgesFor(changeInfo) {
  if (!changeInfo) {
    return []
  }
  const badges = []
  const delay = Math.max(0, Number(changeInfo.new_start_minute) - Number(changeInfo.original_start_minute))
  if (delay > 0) {
    badges.push({ label: `Delayed +${delay} min`, tone: 'amber' })
  }
  if (changeInfo.original_ring_id && changeInfo.new_ring_id && changeInfo.original_ring_id !== changeInfo.new_ring_id) {
    badges.push({ label: `Moved ${changeInfo.original_ring_id} -> ${changeInfo.new_ring_id}`, tone: 'blue' })
  }
  if (
    changeInfo.original_referee_crew_id &&
    changeInfo.new_referee_crew_id &&
    (changeInfo.original_referee_crew_id !== changeInfo.new_referee_crew_id ||
      (changeInfo.changes || []).includes('referee_assignment_changed'))
  ) {
    badges.push({ label: 'Referee changed', tone: 'purple' })
  }
  if (badges.length === 0 || (changeInfo.changes || []).length > 0) {
    badges.push({ label: 'Rescheduled', tone: 'slate' })
  }
  return badges
}

function ChangeBadge({ badge }) {
  const className = {
    amber: 'border-amber-300 bg-amber-100 text-amber-950',
    blue: 'border-blue-300 bg-blue-100 text-blue-950',
    purple: 'border-purple-300 bg-purple-100 text-purple-950',
    slate: 'border-slate-300 bg-white text-slate-700',
  }[badge.tone]
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${className}`}>{badge.label}</span>
}

function MatchRowCard({ row, tournamentStartTime, onSelectDivision, changeInfo = null }) {
  const badges = changeBadgesFor(changeInfo)
  return (
    <button
      type="button"
      onClick={onSelectDivision}
      className={`w-full rounded-md border p-3 text-left text-xs hover:border-blue-300 hover:bg-blue-50 ${
        badges.length > 0 ? 'border-amber-300 bg-amber-50 shadow-sm shadow-amber-100' : 'border-slate-200 bg-slate-50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-semibold text-slate-900">
          Match {row.match_number} · {row.division_name}
        </div>
        {badges.map((badge) => (
          <ChangeBadge key={badge.label} badge={badge} />
        ))}
      </div>
      <div className="mt-0.5 text-slate-700">{row.round_name}</div>
      <div className="mt-1 text-slate-700">{(row.athlete_display || []).join(' · ') || 'Entries pending'}</div>
      <div className="mt-1 text-slate-600">Coaches {(row.coach_labels || []).join(', ') || 'n/a'}</div>
      <div className="mt-1 text-slate-600">
        {formatMinuteAsClock(Number(row.start_minute), tournamentStartTime)} · {String(row.status || 'waiting').replaceAll('_', ' ')}
      </div>
    </button>
  )
}

function MatchRowsModal({ ringName, rows, tournamentStartTime, onClose, onSelectDivision, changedEventMap = {} }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/40 p-4">
      <div className="max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div className="text-sm font-semibold text-slate-900">{ringName} · Remaining Matches</div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            Close
          </button>
        </div>
        <div className="max-h-[calc(85vh-3.5rem)] space-y-2 overflow-y-auto p-3">
          {rows.map((row) => (
            <MatchRowCard
              key={row.match_id}
              row={row}
              tournamentStartTime={tournamentStartTime}
              changeInfo={changedEventMap[row.event_id] || null}
              onSelectDivision={() =>
                onSelectDivision?.({
                  division_id: row.division_id,
                  division_name: row.division_name,
                  event_id: row.event_id,
                  focus_match_id: row.match_id,
                })
              }
            />
          ))}
        </div>
      </div>
    </div>
  )
}

export default function RingColumn({
  ringId,
  ringName,
  events = [],
  changedEventMap = {},
  currentMinute = 0,
  emergencySummary = null,
  onSelectDivision,
  tournamentStartTime = '09:00',
  isExpanded = false,
  onExpandToggle = () => {},
  ringDelayTotals = { rescheduled: 0, delayMinutes: 0 },
  validationPassed = true,
  operationalHint = null,
  matchHintByEventId = {},
  matchRows = [],
  tournament = null,
}) {
  const [showAllMatches, setShowAllMatches] = useState(false)
  const m = Number(currentMinute ?? 0)
  const sortedEvents = [...events].sort((first, second) => (first.start_minute ?? 0) - (second.start_minute ?? 0))
  const sortedMatchRows = useMemo(
    () =>
      [...(matchRows || [])].sort(
        (first, second) => (first.start_minute - second.start_minute) || (first.match_number - second.match_number),
      ),
    [matchRows],
  )
  const hasMatchRows = sortedMatchRows.length > 0
  const remainingMatchRows = hasMatchRows ? sortedMatchRows.filter((row) => row.end_minute > m) : []
  const nextTwentyMatchRows = remainingMatchRows.slice(0, 20)

  const progEvent = sortedEvents.find((event) => isEventInProgress(event, m))
  const nextStrict = sortedEvents.find((event) => Number(event.start_minute) > m)
  const currentMatchRow = hasMatchRows
    ? sortedMatchRows.find((row) => row.status === 'in_progress' || (row.start_minute <= m && m < row.end_minute))
    : null
  const nextMatchRow = hasMatchRows ? sortedMatchRows.find((row) => row.start_minute > m) : null
  const lunchSpan = tournament ? ringLunchSpan(sortedEvents, tournament) : null
  const inSyntheticLunch = ringIsInsideLunch(m, lunchSpan)

  const ringFinished = hasMatchRows
    ? sortedMatchRows.length > 0 && sortedMatchRows.every((row) => Number(row.end_minute) <= m)
    : sortedEvents.length > 0 && sortedEvents.every((event) => isEventCompleted(event, m))

  const hasInProgress = hasMatchRows ? Boolean(currentMatchRow) : Boolean(progEvent)
  const hasDelayed = events.some((event) => {
    const changeInfo = changedEventMap[event.event_id]
    return changeInfo && changeInfo.new_start_minute > changeInfo.original_start_minute
  })
  const isRingEmergency = ['medical_delay', 'ring_pause'].includes(emergencySummary?.emergency_type)
  const isPaused = isRingEmergency && isAffectedRing(emergencySummary, ringId, ringName)
  const hasChangedEvents = sortedEvents.some((event) => changedEventMap[event.event_id])
  const remainingEvents = sortedEvents.filter((event) => event.end_minute > m).length
  const displayRemaining = hasMatchRows
    ? remainingMatchRows.length
    : operationalHint != null && typeof operationalHint.remaining_event_count === 'number'
      ? operationalHint.remaining_event_count
      : remainingEvents

  const opsRescheduled = operationalHint?.material_reschedule_count ?? operationalHint?.rescheduled_division_events ?? 0
  const opsDelayMinutes = typeof operationalHint?.total_delay_minutes === 'number' ? operationalHint.total_delay_minutes : null

  const progMatchHint = hasMatchRows ? currentMatchRow?.match_number : progEvent ? matchHintByEventId[progEvent.event_id] : undefined
  const nextMatchHint = hasMatchRows ? nextMatchRow?.match_number : nextStrict ? matchHintByEventId[nextStrict.event_id] : undefined

  const afterLunchTag =
    lunchSpan &&
    nextStrict &&
    typeof nextStrict.start_minute === 'number' &&
    nextStrict.start_minute >= lunchSpan.segEnd
      ? ' · after lunch corridor'
      : ''

  let ringStatus = 'idle'
  let ringStatusClass = 'bg-slate-100 text-slate-700 ring-1 ring-slate-200'
  if (isPaused) {
    ringStatus = 'paused'
    ringStatusClass = 'bg-purple-100 text-purple-800 ring-1 ring-purple-200'
  } else if (hasDelayed) {
    ringStatus = 'delayed'
    ringStatusClass = 'bg-rose-100 text-rose-800 ring-1 ring-rose-200'
  } else if (inSyntheticLunch && !hasInProgress && !ringFinished) {
    ringStatus = 'lunch break'
    ringStatusClass = 'bg-amber-100 text-amber-900 ring-1 ring-amber-300'
  } else if (hasInProgress) {
    ringStatus = 'in progress'
    ringStatusClass = 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200'
  }

  let linePrimary = 'Idle'
  let lineSecondary = ''
  if (ringFinished) {
    linePrimary = 'Ring complete'
  } else if (hasMatchRows && currentMatchRow) {
    linePrimary = `Current: Match ${currentMatchRow.match_number} · ${currentMatchRow.division_name}`
    lineSecondary = nextMatchRow
      ? `Next: Match ${nextMatchRow.match_number} · ${nextMatchRow.division_name} · ${formatMinuteAsClock(Number(nextMatchRow.start_minute), tournamentStartTime)}`
      : ''
  } else if (progEvent) {
    linePrimary = `Current: ${progEvent.division_name || progEvent.division}${progMatchHint !== undefined ? ` · Match ${progMatchHint}` : ''}`
    lineSecondary = nextStrict
      ? `Next: ${nextStrict.division_name || nextStrict.division}${nextMatchHint !== undefined ? ` · Match ${nextMatchHint}` : ''} · ${formatMinuteAsClock(Number(nextStrict.start_minute), tournamentStartTime)}${afterLunchTag}`
      : ''
  } else if (inSyntheticLunch) {
    linePrimary = 'Lunch break'
    lineSecondary = nextStrict
      ? `Resumes ${nextStrict.division_name || 'next division'} at ${formatMinuteAsClock(Number(nextStrict.start_minute), tournamentStartTime)}${nextMatchHint !== undefined ? ` · Match ${nextMatchHint}` : ''}${afterLunchTag}`
      : lunchSpan != null && tournament != null
        ? `Synthetic break clears near ${formatMinuteAsClock(Number(lunchSpan.segEnd), tournamentStartTime)}`
        : ''
  } else if (hasMatchRows && nextMatchRow) {
    linePrimary = 'Idle · no active match'
    lineSecondary = `Next: Match ${nextMatchRow.match_number} · ${nextMatchRow.division_name} · ${formatMinuteAsClock(Number(nextMatchRow.start_minute), tournamentStartTime)}`
  } else if (sortedEvents.length === 0) {
    linePrimary = 'Idle · No assignments'
  } else if (nextStrict) {
    lineSecondary = `Next: ${nextStrict.division_name || nextStrict.division}${nextMatchHint !== undefined ? ` · Match ${nextMatchHint}` : ''} · ${formatMinuteAsClock(Number(nextStrict.start_minute), tournamentStartTime)}${afterLunchTag}`
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
            <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${ringStatusClass}`}>{ringStatus}</span>
            <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{isExpanded ? 'Collapse' : 'Expand'}</span>
          </div>
          <div className="mt-0.5 space-y-1 text-xs leading-relaxed text-slate-700">
            <p className="m-0">{linePrimary}</p>
            {lineSecondary ? <p className="m-0 text-[11px] text-slate-600">{lineSecondary}</p> : null}
          </div>
          {!isExpanded ? (
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-600">
              <span>
                <span className="font-semibold text-slate-900">{hasMatchRows ? sortedMatchRows.length : sortedEvents.length}</span>{' '}
                {hasMatchRows ? 'matches' : 'events'}
              </span>
              <span>
                <span className="font-semibold text-slate-900">{displayRemaining}</span> remaining {hasMatchRows ? 'matches' : 'events'}
              </span>
              {opsDelayMinutes !== null ? (
                <span>
                  Ops delay <span className="font-semibold text-slate-900">{opsDelayMinutes}m</span>
                </span>
              ) : delayBits.length > 0 ? (
                <span className={`font-semibold ${hasDelayed ? 'text-rose-700' : 'text-slate-900'}`}>{delayBits.join(' • ')}</span>
              ) : (
                <span className="text-slate-500">No reschedule delta</span>
              )}
              <span className={`font-semibold ${opsRescheduled ? 'text-amber-700' : 'text-slate-500'}`}>{opsRescheduled} rescheduled shifts</span>
              <span className={`font-semibold ${validationPassed ? 'text-emerald-700' : 'text-rose-700'}`}>Audit {validationPassed ? 'passed' : 'failed'}</span>
            </div>
          ) : null}
        </div>
        {!isExpanded ? (
          <div className="shrink-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-center text-[11px] text-slate-600">
            <div className="font-semibold text-slate-950">{hasMatchRows ? sortedMatchRows.length : sortedEvents.length}</div>
            <div>{hasMatchRows ? 'matches' : 'slots'}</div>
          </div>
        ) : null}
      </button>

      {isExpanded ? (
        <div className="border-t border-slate-100 pt-3">
          <div className="mb-3 grid grid-cols-3 gap-2 rounded-md border border-slate-200 bg-slate-50 p-2 text-center text-[11px] text-slate-600">
            <div>
              <div className="font-semibold text-slate-950">{hasMatchRows ? sortedMatchRows.length : sortedEvents.length}</div>
              <div>{hasMatchRows ? 'matches' : 'events'}</div>
            </div>
            <div>
              <div className="font-semibold text-slate-950">{displayRemaining}</div>
              <div>left</div>
            </div>
            <div>
              <div className="font-semibold text-slate-950">
                {hasMatchRows ? (nextMatchRow ? formatTournamentMinute(Number(nextMatchRow.start_minute)) : '-') : nextStrict ? formatTournamentMinute(Number(nextStrict.start_minute)) : '-'}
              </div>
              <div>next</div>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {hasMatchRows ? (
              <>
                {nextTwentyMatchRows.length === 0 ? (
                  <p className="text-xs text-slate-500">No remaining matches on this ring.</p>
                ) : (
                  nextTwentyMatchRows.map((row) => (
                    <MatchRowCard
                      key={row.match_id}
                      row={row}
                      tournamentStartTime={tournamentStartTime}
                      changeInfo={changedEventMap[row.event_id] || null}
                      onSelectDivision={() =>
                        onSelectDivision?.({
                          division_id: row.division_id,
                          division_name: row.division_name,
                          event_id: row.event_id,
                          focus_match_id: row.match_id,
                        })
                      }
                    />
                  ))
                )}
                {remainingMatchRows.length > 20 ? (
                  <button
                    type="button"
                    onClick={() => setShowAllMatches(true)}
                    className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-900 hover:bg-blue-100"
                  >
                    Show all matches ({remainingMatchRows.length})
                  </button>
                ) : null}
              </>
            ) : sortedEvents.length === 0 ? (
              <p className="text-xs text-slate-500">No events assigned yet.</p>
            ) : (
              sortedEvents.map((event) => (
                <EventCard
                  key={event.event_id || event.id}
                  event={event}
                  changeInfo={changedEventMap[event.event_id]}
                  currentMinute={m}
                  isPaused={isPaused && event.end_minute > m}
                  onSelectDivision={onSelectDivision}
                  tournamentStartTime={tournamentStartTime}
                  coordinationMatchNumber={matchHintByEventId[event.event_id]}
                />
              ))
            )}
          </div>
        </div>
      ) : null}

      {showAllMatches ? (
        <MatchRowsModal
          ringName={ringName}
          rows={remainingMatchRows}
          tournamentStartTime={tournamentStartTime}
          onClose={() => setShowAllMatches(false)}
          onSelectDivision={onSelectDivision}
          changedEventMap={changedEventMap}
        />
      ) : null}
    </div>
  )
}
