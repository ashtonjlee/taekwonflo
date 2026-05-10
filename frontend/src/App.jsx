import { useEffect, useState } from 'react'
import {
  getDivisionDetail,
  getHealth,
  getMockTournamentSnapshot,
  getRepairDemo,
  getRescheduleDemo,
  getValidationSnapshot,
  postLiveOperations,
} from './api'
import TournamentSetup from './components/TournamentSetup'
import DemoModePanel from './components/DemoModePanel'
import ScheduleDashboard from './components/ScheduleDashboard'
import EmergencyControls from './components/EmergencyControls'
import NotificationsPanel from './components/NotificationsPanel'
import DivisionDetailPanel from './components/DivisionDetailPanel'
import LiveReportsSection from './components/LiveReportsSection'
import TimelineComparison from './components/TimelineComparison'

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
        current_minute: minuteHint ?? emergencySummary?.current_minute ?? 0,
        changed_events: changedEvents,
      })
      setCoordinationBoard(bucket.coordination_board || null)
      setRingOperationalHints(bucket.ring_hints || {})
    } catch {
      //
    }
  }

  function applyRescheduleResponse(response, formValues) {
    setOriginalSchedule(response.original_schedule)
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
      current_minute: formValues.current_minute,
      duration_minutes: formValues.delay_minutes,
    })
  }

  async function handleEmergencySimulation(formValues) {
    try {
      setLoadingEmergency(true)
      setError(null)
      const [response, snapshot] = await Promise.all([
        getRescheduleDemo(formValues),
        getMockTournamentSnapshot(),
      ])
      setTournament(snapshot.tournament)
      applyRescheduleResponse(response, formValues)
      setDemoResult(null)
      setDemoError(null)
    } catch (simulationError) {
      setError(simulationError.message)
    } finally {
      setLoadingEmergency(false)
    }
  }

  async function handleRunDemo(demoKey) {
    try {
      setLoadingDemo(demoKey)
      setDemoError(null)
      setDemoResult(null)
      setError(null)
      setDivisionResourceLocations([])

      if (demoKey === 'coach_delayed') {
        const coachDemoParams = {
          emergency_type: 'coach_conflict',
          current_minute: 0,
        }
        const [response, snapshot] = await Promise.all([
          getRepairDemo(coachDemoParams),
          getMockTournamentSnapshot(),
        ])
        setTournament(snapshot.tournament)
        setOriginalSchedule(response.original_schedule)
        setCurrentSchedule(response.repaired_schedule)
        setChangedEvents(response.changed_events || [])
        setNotifications(response.notifications)
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
        })
        setDivisionDetail(response.division_detail)
        setDivisionResourceLocations(response.resource_locations || [])
        setEmergencySummary({
          emergency_type: 'coach_conflict',
          affectedResource: response.resource_locations?.[0]?.resource_id || 'auto-selected coach',
          current_minute: response.current_minute ?? 0,
          duration_minutes: 20,
        })
        setDemoResult(buildRepairDemoExplanation(response))
        return
      }

      const formValues =
        demoKey === 'medical_pause'
          ? {
              emergency_type: 'medical_delay',
              current_minute: 60,
              delay_minutes: 20,
              ring_id: 'ring-1',
              pause_duration_minutes: 20,
            }
          : {
              emergency_type: 'referee_shortage',
              current_minute: 60,
              delay_minutes: 20,
              referee_crew_id: 'ref-crew-1',
              unavailable_duration_minutes: 20,
            }
      const [response, snapshot] = await Promise.all([
        getRescheduleDemo(formValues),
        getMockTournamentSnapshot(),
      ])
      setTournament(snapshot.tournament)
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
            : 'No future event needed to move for this deterministic demo window.',
        whyStrategy:
          changedCount > 0
            ? 'The existing emergency rescheduler froze completed and active work, then adjusted future events around the pause.'
            : 'The selected pause did not create a future conflict, so the schedule stayed intact.',
        emptyState: changedCount === 0 ? 'Empty state: no downstream event was affected, so there was nothing to repair.' : null,
      }
    }

    return {
      title: 'Referee shortage demo complete',
      strategyLabel: changedCount > 0 ? 'future-event reschedule' : 'no schedule movement needed',
      validationPassed,
      metrics: buildResponseMetrics(response),
      whatHappened: `${formValues.referee_crew_id} was marked short during the demo window.`,
      whatChanged:
        changedCount > 0
          ? `${changedCount} future event${changedCount === 1 ? '' : 's'} changed so the unavailable crew is not double-booked.`
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
      same_division_match_swap: 'same-division match swap',
      same_ring_match_swap: 'same-ring match swap',
      local_shift: 'local ring shift',
      global_reschedule: 'global reschedule fallback',
      infeasible: 'infeasible',
    }[strategy] || strategy
    const fallbackText =
      strategy === 'global_reschedule'
        ? 'No eligible same-division or same-ring match could run safely, so the system fell back to the existing global rescheduler.'
        : strategy === 'infeasible'
          ? 'No eligible match swap or fallback repair was possible for the selected coach delay.'
          : null

    return {
      title: 'Coach delayed demo complete',
      strategyLabel: strategyText,
      validationPassed,
      metrics: {
        changedMatchCount: response.changed_match_count ?? (changedMatches || changedEventsCount),
        averageDelayMinutes: response.average_delay_minutes ?? 0,
        maxDelayMinutes: response.max_delay_minutes ?? 0,
        queueRepairApplied: Boolean(response.queue_repair_applied),
      },
      whatHappened: 'An auto-selected coach was delayed, so the repair layer checked whether another match could run first.',
      whatChanged:
        changedMatches > 0
          ? `${changedMatches} match records changed. ${response.replacement_match?.match_id || 'A replacement match'} was inserted while the blocked match waits.`
          : `${changedEventsCount} scheduled event${changedEventsCount === 1 ? '' : 's'} changed after match-level repair was not available.`,
      whyStrategy:
        strategy === 'same_division_match_swap'
          ? 'The next eligible match in the same division had known bracket dependencies and available athletes, coaches, referees, and ring time.'
          : fallbackText || 'The system used the first valid fallback that preserved resource constraints.',
      emptyState: fallbackText,
    }
  }

  async function handleSelectDivision(event) {
    try {
      setDivisionDetailLoading(true)
      setDivisionDetailError(null)
      setDivisionDetail(null)
      setDivisionResourceLocations([])
      const detail = await getDivisionDetail(event.division_id, {
        current_minute: emergencySummary?.current_minute ?? 0,
        focus_match_id: event.focus_match_id || undefined,
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

    async function loadSnapshot() {
      try {
        const [snapshot, validationResult] = await Promise.all([
          getMockTournamentSnapshot(),
          getValidationSnapshot(),
        ])
        if (!isActive) {
          return
        }
        setTournament(snapshot.tournament)
        setOriginalSchedule(snapshot.schedule)
        setCurrentSchedule(snapshot.schedule)
        setChangedEvents([])
        setNotifications(snapshot.notifications)
        setValidation(validationResult)
        setEmergencySummary(null)
        setError(null)
        setScheduleChangeDetails([])
        setRefereeAdjustments([])
        setCoordinationBoard(null)
        setRingOperationalHints({})
        setRepairMetrics(null)
      } catch (loadError) {
        if (isActive) {
          setError(loadError.message)
        }
      }
    }

    void loadSnapshot()

    return () => {
      isActive = false
    }
  }, [])

  useEffect(() => {
    void hydrateLiveSignals(emergencySummary?.current_minute)
  }, [tournament, currentSchedule, originalSchedule, emergencySummary?.current_minute, changedEvents])

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

        <TournamentSetup snapshot={{ tournament }} />
        <DemoModePanel
          tournament={tournament}
          schedule={currentSchedule}
          onRunDemo={handleRunDemo}
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
              emergencySummary={emergencySummary}
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
            emergencySummary={emergencySummary}
            refereeAdjustments={refereeAdjustments}
            coordinationBoard={coordinationBoard}
            repairMetrics={repairMetrics}
            onSelectDivision={handleSelectDivision}
          />
        )}
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
