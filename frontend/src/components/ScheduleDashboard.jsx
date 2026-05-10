import { useMemo } from 'react'
import RingColumn from './RingColumn'
import {
  formatDuration,
  formatMinuteAsClock,
  formatMinuteRange,
  formatTournamentMinute,
  getMakespan,
  getScheduleEvents,
  getStagingGroups,
  isEventInProgress,
} from '../utils/timeline'
import { formatLunchWindowLabel } from '../utils/lunch'

function isAffectedRing(emergencySummary, ring) {
  const affected = emergencySummary?.affectedResource
  if (!affected) {
    return false
  }
  return affected === ring.ring_id || affected === ring.ring_name
}

function computeRingDelayTotals(ringEvents, changedEventMap) {
  let rescheduled = 0
  let delayMinutes = 0

  ringEvents.forEach((eventItem) => {
    const delta = changedEventMap[eventItem.event_id]
    if (!delta || delta.new_start_minute <= delta.original_start_minute) {
      return
    }

    rescheduled += 1
    delayMinutes += Math.max(0, delta.new_start_minute - delta.original_start_minute)
  })

  return { rescheduled, delayMinutes }
}

const COORD_PHASE_RANK = {
  currently_competing: 0,
  report_staging: 1,
  report_holding: 2,
  warm_up_now: 3,
  completed: 4,
}

function coordinatorEventLookups(coordinationBoard) {
  const rows = [...(coordinationBoard?.rows || [])].sort(
    (a, b) => (COORD_PHASE_RANK[a.phase] ?? 9) - (COORD_PHASE_RANK[b.phase] ?? 9),
  )
  const matchNumByEvent = {}
  const focusMatchByEvent = {}
  for (const row of rows) {
    if (!(row.event_id in focusMatchByEvent)) {
      matchNumByEvent[row.event_id] = row.match_number
      focusMatchByEvent[row.event_id] = row.match_id
    }
  }
  return { matchNumByEvent, focusMatchByEvent }
}

function coordinatorRingRows(coordinationBoard) {
  const rows = coordinationBoard?.rows || []
  const grouped = {}
  for (const row of rows) {
    if (!grouped[row.ring_id]) grouped[row.ring_id] = []
    grouped[row.ring_id].push(row)
  }
  for (const ringId of Object.keys(grouped)) {
    const seen = new Set()
    grouped[ringId] = grouped[ringId]
      .filter((row) => {
        if (seen.has(row.match_id)) return false
        seen.add(row.match_id)
        return true
      })
      .sort((a, b) => (a.start_minute - b.start_minute) || (a.match_number - b.match_number))
  }
  return grouped
}

export default function ScheduleDashboard({
  originalSchedule = [],
  currentSchedule = [],
  changedEvents = [],
  scheduleChanges = [],
  validation = null,
  emergencySummary = null,
  onSelectDivision,
  expandedRingIds = new Set(),
  onToggleRing,
  ringOperationalHints = {},
  coordinationBoard = null,
  tournament = null,
}) {
  const tournamentStartTime = tournament?.tournament_day_start_time || '09:00'
  const ringNameById = useMemo(
    () => Object.fromEntries((tournament?.rings || []).map((r) => [r.id, r.name])),
    [tournament?.rings],
  )
  const { matchNumByEvent, focusMatchByEvent } = useMemo(
    () => coordinatorEventLookups(coordinationBoard),
    [coordinationBoard],
  )
  const ringMatchRowsByRing = useMemo(
    () => coordinatorRingRows(coordinationBoard),
    [coordinationBoard],
  )

  const divisionSelectWithFocus = onSelectDivision
    ? (eventLike) =>
        onSelectDivision({
          ...eventLike,
          division_id: eventLike.division_id,
          focus_match_id: focusMatchByEvent[eventLike.event_id] || eventLike.focus_match_id || undefined,
        })
    : onSelectDivision
  const changedEventMap = Object.fromEntries(changedEvents.map((event) => [event.event_id, event]))
  const beforeMakespan = getMakespan(originalSchedule)
  const afterMakespan = getMakespan(currentSchedule)
  const affected = emergencySummary?.affectedResource || 'N/A'
  const currentMinute = emergencySummary?.current_minute ?? 0
  const emergencyDuration = emergencySummary?.duration_minutes
  const allEvents = getScheduleEvents(currentSchedule)
  const activeEvents = allEvents.filter((event) => isEventInProgress(event, currentMinute))
  const delayedEvents = changedEvents.filter((event) => event.new_start_minute > event.original_start_minute)
  const activeRingCount = currentSchedule.filter((ring) =>
    (ring.events || []).some((event) => isEventInProgress(event, currentMinute)),
  ).length
  const pausedRingCount = ['medical_delay', 'ring_pause'].includes(emergencySummary?.emergency_type)
    ? currentSchedule.filter((ring) => isAffectedRing(emergencySummary, ring)).length
    : 0
  const delayedRingCount = currentSchedule.filter((ring) =>
    (ring.events || []).some((event) => {
      const changeInfo = changedEventMap[event.event_id]
      return changeInfo && changeInfo.new_start_minute > changeInfo.original_start_minute
    }),
  ).length
  const delayedOrPausedRings = new Set()
  currentSchedule.forEach((ring) => {
    const hasDelayedEvent = (ring.events || []).some((event) => {
      const changeInfo = changedEventMap[event.event_id]
      return changeInfo && changeInfo.new_start_minute > changeInfo.original_start_minute
    })
    if (hasDelayedEvent || (pausedRingCount > 0 && isAffectedRing(emergencySummary, ring))) {
      delayedOrPausedRings.add(ring.ring_id)
    }
  })
  const remainingEvents = allEvents.filter((event) => event.end_minute > currentMinute).length
  const completedEvents = allEvents.length - remainingEvents
  const stagingGroups = getStagingGroups(allEvents, currentMinute)
  const stagingCount = stagingGroups.reduce((total, group) => total + group.events.length, 0)
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
        <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3 xl:min-w-[720px] xl:grid-cols-6">
          <SummaryTile label="Current minute" value={formatTournamentMinute(currentMinute)} detail={formatMinuteAsClock(currentMinute, tournamentStartTime)} tone="blue" />
          <SummaryTile label="Completion time" value={formatMinuteAsClock(afterMakespan, tournamentStartTime)} detail={formatDuration(0, afterMakespan)} />
          <SummaryTile label="Active rings" value={activeRingCount} detail={`${activeEvents.length} events`} tone="emerald" />
          <SummaryTile
            label="Delayed/paused"
            value={delayedOrPausedRings.size}
            detail={`${delayedRingCount} delayed, ${pausedRingCount} paused`}
            tone={delayedOrPausedRings.size > 0 ? 'amber' : 'slate'}
          />
          <SummaryTile label="Remaining events" value={remainingEvents} detail={`${completedEvents} completed`} />
          <SummaryTile
            label="Validation"
            value={validationPassed ? 'Passed' : 'Failed'}
            tone={validationPassed ? 'emerald' : 'rose'}
          />
        </div>
      </div>

      {tournament ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-950 shadow-sm shadow-amber-100/70">
          <span className="font-semibold uppercase tracking-wide text-amber-900">Lunch corridor</span>
          <span className="ml-2 font-semibold">{formatLunchWindowLabel(tournament)}</span>
          <span className="mx-2 text-amber-800">•</span>
          <span>
            Grace T+
            {(tournament.lunch_start_minute ?? 180) + (tournament.lunch_grace_minutes ?? 20)} · rings observe staggered synthetic
            breaks once the division overlapping lunch finishes (UI highlights “Lunch break” per ring).
          </span>
        </div>
      ) : null}

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
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-5">
            <Metric
              label="Current minute"
              value={formatTournamentMinute(currentMinute)}
              detail={formatMinuteAsClock(currentMinute)}
              tone="blue"
            />
            <Metric
              label="Completion time"
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
              label="Remaining events"
              value={remainingEvents}
              detail={`${completedEvents} completed of ${allEvents.length}`}
            />
            <Metric
              label="Schedule changes"
              value={changedEvents.length}
              detail={`${delayedEvents.length} delayed events`}
              tone={changedEvents.length > 0 ? 'amber' : 'slate'}
            />
          </div>
          <div className="mt-4 rounded-md border border-slate-200 bg-white p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Emergency impact</div>
            <div className="mt-2 grid grid-cols-1 gap-2 text-slate-700 md:grid-cols-4">
              <div>
                Affected: <span className="font-medium text-slate-950">{affected}</span>
              </div>
              <div>
                Active rings: <span className="font-medium text-slate-950">{activeRingCount}</span>
              </div>
              <div>
                Delayed/paused rings: <span className="font-medium text-slate-950">{delayedOrPausedRings.size}</span>
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
              <div className="mt-1 text-xs text-blue-800">Live calls after {formatMinuteAsClock(currentMinute)}.</div>
            </div>
            <span className="rounded bg-white px-2 py-1 text-xs font-semibold text-blue-800">
              {stagingCount} queued
            </span>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3">
            {stagingCount === 0 ? (
              <p className="rounded border border-blue-100 bg-white p-3 text-sm text-blue-800">
                No upcoming events in the staging window.
              </p>
            ) : (
              stagingGroups.map((group) => (
                <StagingLane
                  key={group.id}
                  group={group}
                  currentMinute={currentMinute}
                  onSelectDivision={divisionSelectWithFocus}
                  matchHintByEventId={matchNumByEvent}
                />
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
            onSelectDivision={divisionSelectWithFocus}
            isExpanded={expandedRingIds.has(ring.ring_id)}
            onExpandToggle={() => onToggleRing(ring.ring_id)}
            ringDelayTotals={computeRingDelayTotals(ring.events || [], changedEventMap)}
            validationPassed={validationPassed}
            operationalHint={ringOperationalHints?.[ring.ring_id] ?? null}
            matchHintByEventId={matchNumByEvent}
            matchRows={ringMatchRowsByRing[ring.ring_id] || []}
            tournament={tournament}
            tournamentStartTime={tournamentStartTime}
            ringNameById={ringNameById}
          />
        ))}
      </div>
    </section>
  )
}

function SummaryTile({ label, value, detail = null, tone = 'slate' }) {
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
      {detail ? <div className="mt-0.5 text-[11px] font-medium opacity-75">{detail}</div> : null}
    </div>
  )
}

function Metric({ label, value, detail, tone = 'slate' }) {
  const valueClass = {
    amber: 'text-amber-800',
    blue: 'text-blue-800',
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

function StagingLane({ group, currentMinute, onSelectDivision, matchHintByEventId = {} }) {
  return (
    <div className="rounded-md border border-blue-100 bg-white p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-800">{group.label}</div>
        <div className="text-xs font-semibold text-slate-500">{group.events.length}</div>
      </div>
      <div className="mt-2 space-y-2">
        {group.events.length === 0 ? (
          <div className="rounded border border-slate-100 bg-slate-50 p-2 text-xs text-slate-500">No calls</div>
        ) : (
          group.events.map((event, index) => {
            const minutesUntilStart = event.start_minute - currentMinute
            const mh = matchHintByEventId[event.event_id]
            return (
              <button
                type="button"
                key={`${group.id}-${event.event_id || event.id}-${index}`}
                onClick={() =>
                  onSelectDivision?.({
                    ...event,
                    division_id: event.division_id,
                  })
                }
                className="grid w-full grid-cols-[4.25rem_1fr] gap-3 rounded border border-slate-100 bg-slate-50 p-2 text-left text-sm transition-colors hover:border-blue-200 hover:bg-blue-50/60 focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                <div className="text-xs font-semibold text-blue-700">
                  {minutesUntilStart === 0 ? 'now' : `${minutesUntilStart} min`}
                </div>
                <div className="min-w-0">
                  <div className="truncate font-semibold text-slate-900">
                    {event.division_name || event.division || 'Unknown division'}
                  </div>
                  {mh !== undefined ? <div className="mt-0.5 text-[11px] font-semibold text-slate-700">Match {mh}</div> : null}
                  <div className="mt-0.5 text-xs text-slate-600">
                    {formatMinuteRange(event.start_minute, event.end_minute)} — {event.ring_name || event.ring_id}
                  </div>
                  <div className="sr-only">Open division detail</div>
                </div>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
