import { useEffect, useState } from 'react'
import {
  generateDemoTournament,
  getDivisionDetail,
  getHealth,
  importCsvTournament,
  postDivisionDetail,
  postLiveOperations,
  postRepairDemo,
  postRescheduleDemo,
} from './api'
import TournamentSetup from './components/TournamentSetup'
import DemoModePanel from './components/DemoModePanel'
import ScheduleDashboard from './components/ScheduleDashboard'
import EmergencyControls from './components/EmergencyControls'
import NotificationsPanel from './components/NotificationsPanel'
import DivisionDetailPanel from './components/DivisionDetailPanel'
import LiveReportsSection from './components/LiveReportsSection'
import TimelineComparison from './components/TimelineComparison'
import CsvUploadPanel from './components/CsvUploadPanel'
import LiveDemoControls, { shouldTriggerRandomDelay } from './components/LiveDemoControls'

function App() {
  const [health, setHealth] = useState({ status: 'loading' })
  const [tournament, setTournament] = useState(null)
  const [originalSchedule, setOriginalSchedule] = useState([])
  const [currentSchedule, setCurrentSchedule] = useState([])
  const [changedEvents, setChangedEvents] = useState([])
  const [notifications, setNotifications] = useState([])
  const [validation, setValidation] = useState(null)
  const [emergencySummary, setEmergencySummary] = useState(null)
  const [divisionDetail, setDivisionDetail] = useState(null)
  const [divisionDetailLoading, setDivisionDetailLoading] = useState(false)
  const [divisionDetailError, setDivisionDetailError] = useState(null)
  const [divisionResourceLocations, setDivisionResourceLocations] = useState([])
  const [demoResult, setDemoResult] = useState(null)
  const [repairMetrics, setRepairMetrics] = useState(null)
  const [activeView, setActiveView] = useState('dashboard')
  const [demoError, setDemoError] = useState(null)
  const [loadingDemo, setLoadingDemo] = useState(null)
  const [loadingEmergency, setLoadingEmergency] = useState(false)
  const [error, setError] = useState(null)
  /** Ring columns start collapsed; only ring IDs in this set show the full schedule list */
  const [expandedRingIds, setExpandedRingIds] = useState(() => new Set())

  const [coordinationBoard, setCoordinationBoard] = useState(null)
  const [scheduleChangeDetails, setScheduleChangeDetails] = useState([])
  const [refereeAdjustments, setRefereeAdjustments] = useState([])
  const [ringOperationalHints, setRingOperationalHints] = useState({})
  const [liveMinute, setLiveMinute] = useState(0)
  const [eventLog, setEventLog] = useState([])

  function toggleRingExpanded(ringId) {
    setExpandedRingIds((prev) => {
      const next = new Set(prev)
      if (next.has(ringId)) {
        next.delete(ringId)
      } else {
        next.add(ringId)
      }
      return next
    })
  }

  async function hydrateLiveSignals(minuteHint) {
    if (!tournament || !currentSchedule.length) {
      return
    }
    try {
      const bucket = await postLiveOperations({
        tournament,
        schedule: currentSchedule,
        original_schedule: originalSchedule,
        current_minute: minuteHint ?? liveMinute,
        changed_events: changedEvents,
      })
      setCoordinationBoard(bucket.coordination_board || null)
      setRingOperationalHints(bucket.ring_hints || {})
    } catch {
      //
    }
  }

  function applyRescheduleResponse(response, formValues) {
    // Original schedule is the published baseline. Once we have one, keep it; do not
    // overwrite it on every demo run so the UI can always diff against the same
    // baseline. (See docs/SCHEDULER_ARCHITECTURE_NOTES.md §9.)
    setOriginalSchedule((prev) => (prev && prev.length ? prev : response.original_schedule))
    setCurrentSchedule(response.rescheduled_schedule)
    setChangedEvents(response.changed_events)
    setNotifications(response.notifications)
    setValidation(response.validation)
    setScheduleChangeDetails(response.schedule_changes || [])
    setRefereeAdjustments(response.referee_adjustments || [])
    setCoordinationBoard(response.coordination_board || null)
    setRepairMetrics({
      changed_match_count: response.changed_match_count ?? response.changed_events?.length ?? 0,
      average_delay_minutes: response.average_delay_minutes ?? 0,
      max_delay_minutes: response.max_delay_minutes ?? 0,
      repair_strategy_used: response.repair_strategy_used || 'global_reschedule',
      queue_repair_applied: Boolean(response.queue_repair_applied),
    })
    const changedEvent = response.changed_events[0]
    setEmergencySummary({
      emergency_type: formValues.emergency_type,
      affectedResource:
        formValues.ring_id ||
        formValues.referee_crew_id ||
        formValues.coach_id ||
        changedEvent?.new_ring_id ||
        changedEvent?.new_referee_crew_id ||
        'auto-selected impactful event',
      current_minute: formValues.current_minute ?? liveMinute,
      duration_minutes: formValues.delay_minutes,
    })
    setLiveMinute(formValues.current_minute ?? liveMinute)
  }

  async function handleEmergencySimulation(formValues) {
    try {
      setLoadingEmergency(true)
      setError(null)
      if (!tournament || !originalSchedule.length) {
        setError('Generate or upload a tournament first.')
        return
      }
      const response =
        formValues.emergency_type === 'coach_conflict'
          ? await postRepairDemo({
              tournament,
              original_schedule: originalSchedule,
              ...formValues,
            })
          : await postRescheduleDemo({
              tournament,
              original_schedule: originalSchedule,
              ...formValues,
            })
      if (formValues.emergency_type === 'coach_conflict') {
        applyRepairResponse(response, formValues)
      } else {
        applyRescheduleResponse(response, formValues)
      }
      setDemoResult(null)
      setDemoError(null)
    } catch (simulationError) {
      setError(simulationError.message)
    } finally {
      setLoadingEmergency(false)
    }
  }

  async function handleImportCsv(file) {
    const response = await importCsvTournament(file)
    setTournament(response.tournament)
    setOriginalSchedule(response.schedule)
    setCurrentSchedule(response.schedule)
    setChangedEvents([])
    setNotifications(response.notifications || [])
    setValidation(null)
    setEmergencySummary(null)
    setLiveMinute(0)
    setEventLog([{ id: `csv-${Date.now()}`, text: `CSV imported: ${response.preview?.athlete_count || 0} athletes, ${response.preview?.division_count || 0} divisions.` }])
    return response
  }

  async function handleGenerateDemoTournament() {
    try {
      setLoadingDemo('generate_tournament')
      setDemoError(null)
      setError(null)
      setDemoResult(null)
      const response = await generateDemoTournament()
      setTournament(response.tournament)
      setOriginalSchedule(response.schedule)
      setCurrentSchedule(response.schedule)
      setChangedEvents([])
      setNotifications(response.notifications || [])
      setValidation(null)
      setEmergencySummary(null)
      setLiveMinute(0)
      setScheduleChangeDetails([])
      setRefereeAdjustments([])
      setCoordinationBoard(null)
      setRingOperationalHints({})
      setRepairMetrics(null)
      setDivisionDetail(null)
      setDivisionDetailError(null)
      setDivisionResourceLocations([])
      setEventLog([
        {
          id: `demo-${Date.now()}`,
          text: `Demo tournament generated: ${response.preview?.athlete_count || 0} athletes, ${response.preview?.division_count || 0} divisions.`,
        },
      ])
    } catch (generateError) {
      setDemoError(generateError.message)
    } finally {
      setLoadingDemo(null)
    }
  }

  function applyRepairResponse(response, formValues) {
    setOriginalSchedule((prev) => (prev && prev.length ? prev : response.original_schedule))
    setCurrentSchedule(response.repaired_schedule)
    setChangedEvents(response.changed_events || [])
    setNotifications(response.notifications || [])
    setValidation(response.validation)
    setScheduleChangeDetails(response.schedule_changes || [])
    setRefereeAdjustments(response.referee_adjustments || [])
    setCoordinationBoard(response.coordination_board || null)
    setRepairMetrics({
      changed_match_count: response.changed_match_count ?? response.changed_events?.length ?? 0,
      average_delay_minutes: response.average_delay_minutes ?? 0,
      max_delay_minutes: response.max_delay_minutes ?? 0,
      repair_strategy_used: response.repair_strategy_used,
      queue_repair_applied: Boolean(response.queue_repair_applied),
      local_swap_used: Boolean(response.local_swap_used),
      global_reschedule_used: Boolean(response.global_reschedule_used),
      explanation: response.explanation || '',
    })
    setDivisionDetail(response.division_detail || null)
    setDivisionResourceLocations(response.resource_locations || [])
    setEmergencySummary({
      emergency_type: formValues.emergency_type || 'coach_conflict',
      affectedResource: response.resource_locations?.[0]?.resource_id || formValues.coach_id || 'auto-selected coach',
      current_minute: response.current_minute ?? formValues.current_minute ?? liveMinute,
      duration_minutes: formValues.delay_minutes,
    })
    setLiveMinute(response.current_minute ?? formValues.current_minute ?? liveMinute)
  }

  async function injectLiveDelay(type, minute, random = false) {
    if (!tournament || !originalSchedule.length) {
      setDemoError('Generate or upload a tournament first.')
      return
    }
    // Random delays must only happen at the current live tick — never inject in the past.
    const safeMinute = Math.max(minute, liveMinute)
    const params = {
      emergency_type: type,
      current_minute: safeMinute,
      delay_minutes: type === 'medical_delay' ? 5 : type === 'coach_conflict' ? 5 : 20,
      pause_duration_minutes: type === 'medical_delay' ? 5 : undefined,
    }
    if (type === 'medical_delay') {
      params.ring_id = currentSchedule.find((ring) => (ring.events || []).some((event) => event.start_minute <= safeMinute && safeMinute < event.end_minute))?.ring_id || currentSchedule[0]?.ring_id
    }
    const response =
      type === 'coach_conflict'
        ? await postRepairDemo({
            tournament,
            original_schedule: originalSchedule,
            emergency_type: 'coach_conflict',
            current_minute: safeMinute,
            delay_minutes: 5,
          })
        : await postRescheduleDemo({
            tournament,
            original_schedule: originalSchedule,
            ...params,
          })
    if (type === 'coach_conflict') {
      applyRepairResponse(response, {
        emergency_type: 'coach_conflict',
        current_minute: safeMinute,
        delay_minutes: 5,
      })
    } else {
      applyRescheduleResponse(response, params)
    }
    setValidation(response.validation)
    setScheduleChangeDetails(response.schedule_changes || [])
    setRefereeAdjustments(response.referee_adjustments || [])
    setCoordinationBoard(response.coordination_board || null)
    const explanationSuffix = response.explanation ? ` — ${response.explanation}` : ''
    setEventLog((prev) => [
      {
        id: `delay-${Date.now()}`,
        text: `${random ? 'Random' : 'Manual'} ${type.replaceAll('_', ' ')} at T+${safeMinute}: ${(response.changed_events || []).length} schedule change(s), ${(response.referee_adjustments || []).length} referee adjustment(s).${explanationSuffix}`,
      },
      ...prev,
    ])
  }

  function handleLiveReset() {
    setLiveMinute(0)
    setCurrentSchedule(originalSchedule)
    setChangedEvents([])
    setScheduleChangeDetails([])
    setRefereeAdjustments([])
    setEmergencySummary(null)
    setRepairMetrics(null)
    setCoordinationBoard(null)
    setRingOperationalHints({})
    setEventLog([])
    setDivisionDetail(null)
    setDivisionDetailError(null)
    setDivisionResourceLocations([])
  }

  function handleAdvanceLiveTime(stepMinutes, randomDelayEnabled = false) {
    const nextMinute = Math.min(480, liveMinute + stepMinutes)
    setLiveMinute(nextMinute)
    if (randomDelayEnabled && nextMinute > liveMinute) {
      const delayType = shouldTriggerRandomDelay(nextMinute, liveMinute)
      if (delayType) {
        // Random delays must only fire at the current advance window, never in the past.
        void injectLiveDelay(delayType, nextMinute, true)
      }
    }
    return nextMinute
  }

  async function handleRunDemo(demoKey) {
    try {
      setLoadingDemo(demoKey)
      setDemoError(null)
      setDemoResult(null)
      setError(null)
      setDivisionResourceLocations([])

      if (!tournament || !originalSchedule.length) {
        setDemoError('Generate or upload a tournament first.')
        return
      }

      if (demoKey === 'coach_delayed') {
        const coachDemoParams = {
          emergency_type: 'coach_conflict',
          current_minute: 0,
          delay_minutes: 5,
        }
        const response = await postRepairDemo({
          tournament,
          original_schedule: originalSchedule,
          ...coachDemoParams,
        })
        applyRepairResponse(response, coachDemoParams)
        setDemoResult(buildRepairDemoExplanation(response))
        return
      }

      const formValues =
        demoKey === 'medical_pause'
          ? {
              emergency_type: 'medical_delay',
              current_minute: 60,
              delay_minutes: 5,
              ring_id: 'ring-1',
              pause_duration_minutes: 5,
            }
          : {
              emergency_type: 'referee_shortage',
              current_minute: 60,
              delay_minutes: 20,
              unavailable_duration_minutes: 20,
            }
      const response = await postRescheduleDemo({
        tournament,
        original_schedule: originalSchedule,
        ...formValues,
      })
      applyRescheduleResponse(response, formValues)
      setDemoResult(buildRescheduleDemoExplanation(demoKey, response, formValues))
    } catch (demoRunError) {
      setDemoError(demoRunError.message)
    } finally {
      setLoadingDemo(null)
    }
  }

  function buildRescheduleDemoExplanation(demoKey, response, formValues) {
    const changedCount = response.changed_events?.length || 0
    const delayedCount = (response.changed_events || []).filter(
      (event) => event.new_start_minute > event.original_start_minute,
    ).length
    const validationPassed = response.validation?.valid !== false

    if (demoKey === 'medical_pause') {
      return {
        title: 'Medical pause demo complete',
        strategyLabel: changedCount > 0 ? 'future-event reschedule' : 'no schedule movement needed',
        validationPassed,
        metrics: buildResponseMetrics(response),
        whatHappened: `A medical pause was applied to ${formValues.ring_id} at T+${formValues.current_minute}.`,
        whatChanged:
          changedCount > 0
            ? `${changedCount} future event${changedCount === 1 ? '' : 's'} changed, including ${delayedCount} delayed event${delayedCount === 1 ? '' : 's'}.`
            : `${formValues.ring_id} paused for ${formValues.pause_duration_minutes || formValues.delay_minutes} minutes; current work resumed and no ring reassignment was needed.`,
        whyStrategy:
          changedCount > 0
            ? 'The existing emergency rescheduler froze completed and active work, then adjusted future events around the pause.'
            : 'The selected pause did not create a future conflict, so the schedule stayed intact.',
        emptyState: changedCount === 0 ? 'Empty state: no downstream event was affected, so there was nothing to repair.' : null,
      }
    }

    return {
      title: 'Referee shortage demo complete',
      strategyLabel:
        changedCount > 0
          ? 'future-event reschedule'
          : response.referee_adjustments?.length
            ? 'referee borrowing adjustment'
            : 'no schedule movement needed',
      validationPassed,
      metrics: buildResponseMetrics(response),
      whatHappened: response.demo_scenario_reason || 'One assigned referee was marked unavailable during the demo window.',
      whatChanged:
        changedCount > 0
          ? `${changedCount} future event${changedCount === 1 ? '' : 's'} changed so the unavailable crew is not double-booked.`
          : response.referee_adjustments?.length
            ? `${response.referee_adjustments.length} referee assignment${response.referee_adjustments.length === 1 ? '' : 's'} changed to keep the ring staffed.`
            : 'No future event needed to move for this deterministic demo window.',
      whyStrategy:
        changedCount > 0
          ? 'The existing rescheduler preferred valid future assignments while preserving completed and active events.'
          : 'No match swap or event move was necessary because the shortage did not block a future assignment in this window.',
      emptyState: changedCount === 0 ? 'Empty state: the shortage window did not force a visible schedule change.' : null,
    }
  }

  function buildResponseMetrics(response) {
    const changed = response.changed_events || []
    const delays = changed.map((event) => Math.max(0, event.new_start_minute - event.original_start_minute))
    return {
      changedMatchCount: response.changed_match_count ?? changed.length,
      averageDelayMinutes:
        response.average_delay_minutes ?? (delays.length ? Math.round((delays.reduce((sum, value) => sum + value, 0) / delays.length) * 10) / 10 : 0),
      maxDelayMinutes: response.max_delay_minutes ?? Math.max(0, ...delays),
      queueRepairApplied: Boolean(response.queue_repair_applied),
    }
  }

  function buildRepairDemoExplanation(response) {
    const strategy = response.repair_strategy_used
    const changedMatches = response.changed_matches?.length || 0
    const changedEventsCount = response.changed_events?.length || 0
    const validationPassed = response.validation?.valid !== false
    const strategyText = {
      same_division_adjacent_swap: 'same-division adjacent swap',
      same_division_next_ready_swap: 'same-division next-ready swap',
      same_division_match_swap: 'same-division match swap',
      same_ring_match_swap: 'same-ring match swap',
      small_local_wait: 'small local wait',
      local_shift: 'local ring shift',
      global_reschedule: 'global reschedule fallback',
      infeasible: 'infeasible',
    }[strategy] || strategy
    const fallbackText =
      strategy === 'global_reschedule'
        ? 'No eligible local swap or small wait was possible, so the system fell back to the global rescheduler.'
        : strategy === 'infeasible'
          ? 'No eligible match swap or fallback repair was possible for the selected coach delay.'
          : null

    const whyStrategy = response.explanation || (
      strategy === 'same_division_adjacent_swap'
        ? 'The very next match in the same division round was ready, so the two were swapped with no other changes.'
        : strategy === 'same_division_next_ready_swap'
          ? 'The next ready match within a small same-division window was promoted while the blocked match waits.'
          : strategy === 'small_local_wait'
            ? 'Coach delay was small, so the affected match waited locally instead of triggering a global reschedule.'
            : strategy === 'same_division_match_swap'
              ? 'The next eligible match in the same division had known bracket dependencies and available resources.'
              : fallbackText || 'The system used the first valid fallback that preserved resource constraints.'
    )

    return {
      title: 'Coach delayed demo complete',
      strategyLabel: strategyText,
      validationPassed,
      metrics: {
        changedMatchCount: response.changed_match_count ?? (changedMatches || changedEventsCount),
        averageDelayMinutes: response.average_delay_minutes ?? 0,
        maxDelayMinutes: response.max_delay_minutes ?? 0,
        queueRepairApplied: Boolean(response.queue_repair_applied),
        localSwapUsed: Boolean(response.local_swap_used),
        globalRescheduleUsed: Boolean(response.global_reschedule_used),
      },
      whatHappened:
        response.explanation ||
        'An auto-selected coach was delayed, so the repair layer checked whether another match could run first.',
      whatChanged:
        changedMatches > 0
          ? `${changedMatches} match record${changedMatches === 1 ? '' : 's'} changed. ${
              response.replacement_match
                ? `Match ${response.replacement_match.match_number} runs while Match ${response.affected_match_number ?? 'the blocked match'} waits.`
                : 'A replacement match was inserted while the blocked match waits.'
            }`
          : `${changedEventsCount} scheduled event${changedEventsCount === 1 ? '' : 's'} changed.`,
      whyStrategy,
      emptyState: fallbackText,
    }
  }

  async function handleSelectDivision(event) {
    try {
      setDivisionDetailLoading(true)
      setDivisionDetailError(null)
      setDivisionDetail(null)
      setDivisionResourceLocations([])
      const detail =
        tournament && currentSchedule.length
          ? await postDivisionDetail(event.division_id, {
              tournament,
              schedule: currentSchedule,
              current_minute: liveMinute,
              focus_match_id: event.focus_match_id || event.match_id || undefined,
            })
          : await getDivisionDetail(event.division_id, {
              current_minute: liveMinute,
              focus_match_id: event.focus_match_id || event.match_id || undefined,
            })
      setDivisionDetail(detail)
    } catch (detailError) {
      setDivisionDetailError(detailError.message)
    } finally {
      setDivisionDetailLoading(false)
    }
  }

  function handleCloseDivisionDetail() {
    setDivisionDetail(null)
    setDivisionDetailError(null)
    setDivisionDetailLoading(false)
    setDivisionResourceLocations([])
  }

  useEffect(() => {
    let isActive = true

    getHealth().then((result) => {
      if (isActive) {
        setHealth(result)
      }
    })

    return () => {
      isActive = false
    }
  }, [])

  useEffect(() => {
    void hydrateLiveSignals(liveMinute)
  }, [tournament, currentSchedule, originalSchedule, liveMinute, changedEvents])

  const liveEmergencySummary = {
    ...(emergencySummary || {}),
    current_minute: liveMinute,
  }

  const longOpStage =
    loadingEmergency
      ? 'optimizing schedule'
      : loadingDemo === 'generate_tournament'
        ? 'optimizing schedule'
      : loadingDemo === 'coach_delayed'
        ? 'optimizing schedule'
        : loadingDemo
          ? 'optimizing schedule'
          : null
  const longOpLabel =
    loadingEmergency
      ? 'Reschedule demo running'
      : loadingDemo === 'generate_tournament'
        ? 'Generate demo tournament running'
      : loadingDemo === 'coach_delayed'
        ? 'Coach delay repair running'
        : loadingDemo === 'medical_pause'
          ? 'Medical pause demo running'
          : loadingDemo === 'referee_shortage'
            ? 'Referee shortage demo running'
            : null

  return (
    <div className="min-h-screen p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="rounded-xl bg-white p-5 shadow">
          <h1 className="m-0 text-3xl font-bold">TaekwonFlo MVP</h1>
          <p className="mt-2 text-sm text-slate-600">
            Placeholder interface for scheduling and emergency rescheduling.
          </p>
          <div className="mt-3 text-sm">
            Backend status:{' '}
            <span className="font-semibold text-blue-700">{health.status}</span>
          </div>
        </header>
        {longOpLabel ? <LongOpProgress label={longOpLabel} stage={longOpStage} /> : null}

        <TournamentSetup snapshot={{ tournament }} />
        <CsvUploadPanel onImportCsv={handleImportCsv} />
        <DemoModePanel
          tournament={tournament}
          schedule={currentSchedule}
          onRunDemo={handleRunDemo}
          onGenerateDemo={handleGenerateDemoTournament}
          loadingDemo={loadingDemo}
          result={demoResult}
          error={demoError}
        />
        <div className="flex flex-wrap gap-2 rounded-xl bg-white p-2 shadow">
          <ViewTab id="dashboard" label="Schedule Dashboard" activeView={activeView} onSelect={setActiveView} />
          <ViewTab id="timeline" label="Timeline Comparison" activeView={activeView} onSelect={setActiveView} />
        </div>
        {activeView === 'dashboard' ? (
          <>
            <ScheduleDashboard
              originalSchedule={originalSchedule}
              currentSchedule={currentSchedule}
              changedEvents={changedEvents}
              validation={validation}
              emergencySummary={liveEmergencySummary}
              onSelectDivision={handleSelectDivision}
              expandedRingIds={expandedRingIds}
              onToggleRing={toggleRingExpanded}
              ringOperationalHints={ringOperationalHints}
              coordinationBoard={coordinationBoard}
              tournament={tournament}
            />
            <LiveReportsSection
              coordinationBoard={coordinationBoard}
              scheduleChanges={scheduleChangeDetails}
              refereeAdjustments={refereeAdjustments}
              onCoordinatorSelect={handleSelectDivision}
            />
          </>
        ) : (
          <TimelineComparison
            originalSchedule={originalSchedule}
            currentSchedule={currentSchedule}
            changedEvents={changedEvents}
            emergencySummary={liveEmergencySummary}
            refereeAdjustments={refereeAdjustments}
            coordinationBoard={coordinationBoard}
            repairMetrics={repairMetrics}
            currentMinute={liveMinute}
            onSelectDivision={handleSelectDivision}
          />
        )}
        <LiveDemoControls
          currentMinute={liveMinute}
          onSetMinute={setLiveMinute}
          onAdvanceTime={handleAdvanceLiveTime}
          onReset={handleLiveReset}
          onInjectDelay={injectLiveDelay}
          eventLog={eventLog}
        />
        <EmergencyControls
          tournament={tournament}
          onSimulate={handleEmergencySimulation}
          loading={loadingEmergency}
          error={error}
        />
        <NotificationsPanel notifications={notifications} />
      </div>
      <DivisionDetailPanel
        detail={divisionDetail}
        loading={divisionDetailLoading}
        error={divisionDetailError}
        resourceLocations={divisionResourceLocations}
        onClose={handleCloseDivisionDetail}
      />
    </div>
  )
}

function LongOpProgress({ label, stage }) {
  const stages = ['parsing data', 'building divisions', 'optimizing schedule', 'validating']
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => Math.min(value + 1, stages.length - 1)), 1500)
    return () => window.clearInterval(timer)
  }, [])
  const idx = Math.max(stages.indexOf(stage), tick, 0)
  const pct = Math.round(((idx + 1) / stages.length) * 100)
  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900 shadow">
      <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide">
        <span>{label}</span>
        <span>{pct}%</span>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-blue-100">
        <div className="h-full rounded-full bg-blue-500 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {stages.map((entry, position) => (
          <span
            key={entry}
            className={`rounded-full px-2 py-0.5 ${
              position <= idx ? 'bg-blue-200 text-blue-900' : 'bg-white text-slate-500 border border-slate-200'
            }`}
          >
            {entry}
          </span>
        ))}
      </div>
    </div>
  )
}

function ViewTab({ id, label, activeView, onSelect }) {
  const active = activeView === id
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className={`rounded-md px-4 py-2 text-sm font-semibold transition-colors ${
        active ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
      }`}
    >
      {label}
    </button>
  )
}

export default App
