import { useMemo, useState } from 'react'
import { formatMinuteAsClock, formatMinuteRange, getScheduleEvents } from '../utils/timeline'

const EVENT_TYPE_LABELS = {
  kyorugi: 'Kyorugi',
  poomsae: 'Poomsae',
  pair_poomsae: 'Pair Poomsae',
  team_poomsae: 'Team Poomsae',
}

function uniq(values) {
  return [...new Set(values.filter(Boolean))].sort()
}

function eventKey(event) {
  return event.event_id || `${event.division_id}-${event.ring_id}-${event.start_minute}`
}

function buildChangedMap(changedEvents = []) {
  return Object.fromEntries(changedEvents.map((row) => [row.event_id, row]))
}

function buildCoordinatorLookups(coordinationBoard) {
  const matchNumByEvent = {}
  const focusMatchByEvent = {}
  const roundByEvent = {}
  for (const row of coordinationBoard?.rows || []) {
    if (!(row.event_id in matchNumByEvent)) {
      matchNumByEvent[row.event_id] = row.match_number
      focusMatchByEvent[row.event_id] = row.match_id
      roundByEvent[row.event_id] = row.round_name
    }
  }
  return { matchNumByEvent, focusMatchByEvent, roundByEvent }
}

export default function TimelineComparison({
  originalSchedule = [],
  currentSchedule = [],
  changedEvents = [],
  emergencySummary = null,
  refereeAdjustments = [],
  coordinationBoard = null,
  repairMetrics = null,
  currentMinute = 0,
  onSelectDivision,
}) {
  const [filters, setFilters] = useState({
    belt: 'all',
    age: 'all',
    weight: 'all',
    eventType: 'all',
    ring: 'all',
    rescheduledOnly: false,
  })

  const changedMap = useMemo(() => buildChangedMap(changedEvents), [changedEvents])
  const lookups = useMemo(() => buildCoordinatorLookups(coordinationBoard), [coordinationBoard])
  const allEvents = useMemo(
    () => [...getScheduleEvents(originalSchedule), ...getScheduleEvents(currentSchedule)],
    [originalSchedule, currentSchedule],
  )
  const options = useMemo(
    () => ({
      belts: uniq(allEvents.map((event) => event.belt_rank_group)),
      ages: uniq(allEvents.map((event) => event.age_group)),
      weights: uniq(allEvents.map((event) => event.weight_class)),
      eventTypes: uniq(allEvents.map((event) => event.event_type)),
      rings: uniq(allEvents.map((event) => event.ring_id)),
    }),
    [allEvents],
  )

  const minMinute = Math.min(0, ...allEvents.map((event) => event.start_minute ?? 0))
  const maxMinute = Math.max(60, ...allEvents.map((event) => event.end_minute ?? 0))
  const span = Math.max(1, maxMinute - minMinute)
  const pixelsPerMinute = span > 540 ? 3 : 4
  const timelineWidth = Math.max(960, span * pixelsPerMinute)
  const axisTicks = useMemo(() => buildAxisTicks(minMinute, maxMinute), [minMinute, maxMinute])
  const ringChanges = changedEvents.filter((event) => event.original_ring_id !== event.new_ring_id).length
  const delayRows = changedEvents.map((event) => Math.max(0, event.new_start_minute - event.original_start_minute))
  const avgDelay =
    typeof repairMetrics?.average_delay_minutes === 'number'
      ? repairMetrics.average_delay_minutes
      : delayRows.length
        ? Math.round((delayRows.reduce((total, value) => total + value, 0) / delayRows.length) * 10) / 10
        : 0
  const maxDelay =
    typeof repairMetrics?.max_delay_minutes === 'number' ? repairMetrics.max_delay_minutes : Math.max(0, ...delayRows)
  const changedCount = repairMetrics?.changed_match_count ?? changedEvents.length

  function updateFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }

  function matchesFilters(event) {
    const change = changedMap[event.event_id] || (event.is_rescheduled ? event : null)
    if (filters.rescheduledOnly && !change) return false
    if (filters.belt !== 'all' && event.belt_rank_group !== filters.belt) return false
    if (filters.age !== 'all' && event.age_group !== filters.age) return false
    if (filters.weight !== 'all' && event.weight_class !== filters.weight) return false
    if (filters.eventType !== 'all' && event.event_type !== filters.eventType) return false
    if (filters.ring !== 'all' && event.ring_id !== filters.ring) return false
    return true
  }

  function handleBarClick(event) {
    onSelectDivision?.({
      ...event,
      division_id: event.division_id,
      focus_match_id: lookups.focusMatchByEvent[event.event_id] || event.focus_match_id || undefined,
    })
  }

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Timeline Comparison</p>
          <h2 className="m-0 mt-1 text-2xl font-bold text-slate-950">Original vs Updated Schedule</h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Compare the published ring plan against the repaired schedule and inspect changed matches.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-5 xl:min-w-[680px]">
          <Summary label="Changed" value={changedCount} detail="matches/events" tone={changedCount ? 'amber' : 'slate'} />
          <Summary label="Avg delay" value={`${avgDelay} min`} detail="changed only" />
          <Summary label="Max delay" value={`${maxDelay} min`} detail="largest move" tone={maxDelay ? 'rose' : 'slate'} />
          <Summary label="Ring moves" value={ringChanges} detail="old -> new" />
          <Summary label="Referee changes" value={refereeAdjustments.length} detail={emergencySummary?.emergency_type || 'none'} />
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 lg:grid-cols-6">
        <SelectFilter label="Belt" value={filters.belt} values={options.belts} onChange={(value) => updateFilter('belt', value)} />
        <SelectFilter label="Age" value={filters.age} values={options.ages} onChange={(value) => updateFilter('age', value)} />
        <SelectFilter label="Weight" value={filters.weight} values={options.weights} onChange={(value) => updateFilter('weight', value)} />
        <SelectFilter
          label="Event"
          value={filters.eventType}
          values={options.eventTypes}
          labelFor={(value) => EVENT_TYPE_LABELS[value] || value}
          onChange={(value) => updateFilter('eventType', value)}
        />
        <SelectFilter label="Ring" value={filters.ring} values={options.rings} onChange={(value) => updateFilter('ring', value)} />
        <label className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">
          <input
            type="checkbox"
            checked={filters.rescheduledOnly}
            onChange={(event) => updateFilter('rescheduledOnly', event.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
          />
          Rescheduled only
        </label>
      </div>

      <div className="mt-5 space-y-6">
        <GanttChart
          title="Original Schedule Gantt"
          schedule={originalSchedule}
          changedMap={changedMap}
          lookups={lookups}
          minMinute={minMinute}
          span={span}
          timelineWidth={timelineWidth}
          axisTicks={axisTicks}
          currentMinute={currentMinute}
          matchesFilters={matchesFilters}
          onBarClick={handleBarClick}
          variant="original"
        />
        <GanttChart
          title="Updated/Repaired Schedule Gantt"
          schedule={currentSchedule}
          changedMap={changedMap}
          lookups={lookups}
          minMinute={minMinute}
          span={span}
          timelineWidth={timelineWidth}
          axisTicks={axisTicks}
          currentMinute={currentMinute}
          matchesFilters={matchesFilters}
          onBarClick={handleBarClick}
          variant="updated"
        />
      </div>
    </section>
  )
}

function GanttChart({
  title,
  schedule,
  changedMap,
  lookups,
  minMinute,
  span,
  timelineWidth,
  axisTicks,
  currentMinute,
  matchesFilters,
  onBarClick,
  variant,
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="m-0 text-sm font-semibold text-slate-950">{title}</h3>
        <span className="text-xs font-semibold text-slate-500">Rings as rows · horizontal scroll preserves clock scale</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <div className="min-w-full p-3" style={{ width: `${timelineWidth + 90}px` }}>
          <div className="grid grid-cols-[5rem_1fr] gap-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Ring</div>
            <TimeAxis minMinute={minMinute} span={span} ticks={axisTicks} />
          </div>
          <div className="mt-2 space-y-3">
            {schedule.map((ring) => {
              const visibleEvents = (ring.events || []).filter(matchesFilters)
              return (
                <div key={`${variant}-${ring.ring_id}`} className="grid grid-cols-[5rem_1fr] gap-3">
                  <div className="pt-3 text-xs font-semibold text-slate-700">{ring.ring_name || ring.ring_id}</div>
                  <div className="relative min-h-[3.75rem] rounded-md border border-slate-200 bg-white">
                    <GridLines minMinute={minMinute} span={span} ticks={axisTicks} />
                    <CurrentTimeMarker minMinute={minMinute} span={span} currentMinute={currentMinute} />
                    {visibleEvents.length === 0 ? (
                      <div className="relative z-10 px-3 py-4 text-xs text-slate-400">No events match filters</div>
                    ) : (
                      visibleEvents.map((event) => (
                        <GanttBar
                          key={`${variant}-${eventKey(event)}`}
                          event={event}
                          change={changedMap[event.event_id] || null}
                          matchNumber={event.match_number || lookups.matchNumByEvent[event.event_id]}
                          roundName={event.round_name || lookups.roundByEvent[event.event_id] || 'division block'}
                          minMinute={minMinute}
                          span={span}
                          variant={variant}
                          onClick={() => onBarClick(event)}
                        />
                      ))
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

function buildAxisTicks(minMinute, maxMinute) {
  const start = Math.floor(minMinute / 15) * 15
  const end = Math.ceil(maxMinute / 15) * 15
  const ticks = []
  for (let minute = start; minute <= end; minute += 15) {
    ticks.push({
      minute,
      major: minute % 60 === 0,
      half: minute % 30 === 0,
    })
  }
  return ticks
}

function TimeAxis({ minMinute, span, ticks }) {
  return (
    <div className="relative h-9 border-b border-slate-300">
      {ticks.map((tick) => {
        const left = ((tick.minute - minMinute) / span) * 100
        return (
          <div
            key={`axis-${tick.minute}`}
            className="absolute bottom-0 flex translate-x-[-1px] flex-col items-start"
            style={{ left: `${left}%` }}
          >
            <span className={`${tick.major ? 'h-3 border-l border-slate-600' : tick.half ? 'h-2 border-l border-slate-400' : 'h-1.5 border-l border-slate-300'}`} />
            {tick.major ? (
              <span className="mt-1 whitespace-nowrap text-[11px] font-semibold text-slate-700">
                {formatMinuteAsClock(tick.minute)}
              </span>
            ) : tick.half ? (
              <span className="mt-1 whitespace-nowrap text-[10px] text-slate-500">{formatMinuteAsClock(tick.minute)}</span>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function GridLines({ minMinute, span, ticks }) {
  return (
    <div className="pointer-events-none absolute inset-0">
      {ticks.map((tick) => {
        const left = ((tick.minute - minMinute) / span) * 100
        return (
          <div
            key={`grid-${tick.minute}`}
            className={`absolute top-0 h-full border-l ${
              tick.major ? 'border-slate-300' : tick.half ? 'border-slate-200' : 'border-slate-100'
            }`}
            style={{ left: `${left}%` }}
          />
        )
      })}
    </div>
  )
}

function CurrentTimeMarker({ minMinute, span, currentMinute }) {
  const left = ((currentMinute - minMinute) / span) * 100
  if (left < 0 || left > 100) return null
  return (
    <div className="pointer-events-none absolute top-0 z-20 h-full border-l-2 border-rose-500" style={{ left: `${left}%` }}>
      <span className="absolute -top-5 -translate-x-1/2 rounded bg-rose-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
        now
      </span>
    </div>
  )
}

function GanttBar({ event, change, matchNumber, roundName, minMinute, span, variant, onClick }) {
  const isChanged = Boolean(change || event.is_rescheduled)
  const left = Math.max(0, ((event.start_minute - minMinute) / span) * 100)
  const width = Math.max(3, ((event.end_minute - event.start_minute) / span) * 100)
  const movedRing = change && change.original_ring_id !== change.new_ring_id
  const delayed = change && change.new_start_minute > change.original_start_minute
  const title = [
    `Match ${matchNumber || event.match_number || '-'}`,
    event.division_name,
    roundName,
    event.ring_name || event.ring_id,
    formatMinuteRange(event.start_minute, event.end_minute),
    EVENT_TYPE_LABELS[event.event_type] || event.event_type,
    movedRing ? `${change.original_ring_id} -> ${change.new_ring_id}` : null,
    delayed ? `${formatMinuteAsClock(change.original_start_minute)} -> ${formatMinuteAsClock(change.new_start_minute)}` : null,
  ]
    .filter(Boolean)
    .join(' | ')

  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`absolute top-2 z-10 h-10 overflow-hidden rounded-md border px-2 text-left text-[11px] leading-tight shadow-sm transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${
        isChanged
          ? variant === 'updated'
            ? 'border-amber-400 bg-amber-100 text-amber-950'
            : 'border-blue-300 bg-blue-50 text-blue-950'
          : 'border-slate-200 bg-slate-100 text-slate-700 hover:bg-slate-200'
      }`}
      style={{ left: `${left}%`, width: `${width}%` }}
    >
      <span className="block truncate font-bold">M{matchNumber || '-'} · {event.division_name}</span>
      <span className="block truncate">
        {roundName} · {formatMinuteRange(event.start_minute, event.end_minute)}
      </span>
      {isChanged ? (
        <span className="block truncate font-semibold">
          {movedRing ? `${change.original_ring_id} -> ${change.new_ring_id}` : ''}
          {movedRing && delayed ? ' · ' : ''}
          {delayed ? `+${change.new_start_minute - change.original_start_minute} min` : event.delay_minutes ? `+${event.delay_minutes} min` : 'changed'}
        </span>
      ) : null}
    </button>
  )
}

function SelectFilter({ label, value, values, onChange, labelFor = (item) => item }) {
  return (
    <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 block w-full rounded-md border border-slate-200 bg-white px-2 py-2 text-sm normal-case tracking-normal text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
      >
        <option value="all">All</option>
        {values.map((item) => (
          <option key={item} value={item}>
            {labelFor(item)}
          </option>
        ))}
      </select>
    </label>
  )
}

function Summary({ label, value, detail, tone = 'slate' }) {
  const toneClass = {
    amber: 'border-amber-200 bg-amber-50 text-amber-950',
    rose: 'border-rose-200 bg-rose-50 text-rose-950',
    slate: 'border-slate-200 bg-slate-50 text-slate-950',
  }[tone]
  return (
    <div className={`rounded-lg border p-3 ${toneClass}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-lg font-bold">{value}</div>
      <div className="mt-0.5 text-[11px] font-medium opacity-75">{detail}</div>
    </div>
  )
}
