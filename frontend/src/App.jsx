import { useEffect, useState } from 'react'
import { getHealth, getMockTournamentSnapshot, getRescheduleDemo, getValidationSnapshot } from './api'
import TournamentSetup from './components/TournamentSetup'
import ScheduleDashboard from './components/ScheduleDashboard'
import EmergencyControls from './components/EmergencyControls'
import NotificationsPanel from './components/NotificationsPanel'

function App() {
  const [health, setHealth] = useState({ status: 'loading' })
  const [tournament, setTournament] = useState(null)
  const [originalSchedule, setOriginalSchedule] = useState([])
  const [currentSchedule, setCurrentSchedule] = useState([])
  const [changedEvents, setChangedEvents] = useState([])
  const [notifications, setNotifications] = useState([])
  const [validation, setValidation] = useState(null)
  const [emergencySummary, setEmergencySummary] = useState(null)
  const [loadingEmergency, setLoadingEmergency] = useState(false)
  const [error, setError] = useState(null)

  async function handleEmergencySimulation(formValues) {
    try {
      setLoadingEmergency(true)
      setError(null)
      const response = await getRescheduleDemo(formValues)
      setOriginalSchedule(response.original_schedule)
      setCurrentSchedule(response.rescheduled_schedule)
      setChangedEvents(response.changed_events)
      setNotifications(response.notifications)
      setValidation(response.validation)
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
      })
    } catch (simulationError) {
      setError(simulationError.message)
    } finally {
      setLoadingEmergency(false)
    }
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
        <ScheduleDashboard
          originalSchedule={originalSchedule}
          currentSchedule={currentSchedule}
          changedEvents={changedEvents}
          validation={validation}
          emergencySummary={emergencySummary}
        />
        <EmergencyControls
          tournament={tournament}
          onSimulate={handleEmergencySimulation}
          loading={loadingEmergency}
          error={error}
        />
        <NotificationsPanel notifications={notifications} />
      </div>
    </div>
  )
}

export default App
