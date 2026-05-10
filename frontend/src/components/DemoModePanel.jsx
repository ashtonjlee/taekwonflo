const DEMO_LABELS = {
  medical_pause: 'Medical pause demo',
  referee_shortage: 'Referee shortage demo',
  coach_delayed: 'Coach delayed demo',
}

export default function DemoModePanel({
  tournament = null,
  schedule = [],
  onRunDemo,
  loadingDemo = null,
  result = null,
  error = null,
}) {
  const metrics = buildDemoMetrics(tournament, schedule)

  return (
    <section className="rounded-xl bg-white p-5 shadow">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Demo Mode</p>
          <h2 className="m-0 mt-1 text-xl font-semibold text-slate-950">Scripted Operations Demos</h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Large tournament simulation using 5 rings and roughly 61 divisions. Run a repeatable scenario and get a
            plain-English summary of the repair or reschedule decision.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <DemoButton demoKey="medical_pause" loadingDemo={loadingDemo} onRunDemo={onRunDemo} />
          <DemoButton demoKey="referee_shortage" loadingDemo={loadingDemo} onRunDemo={onRunDemo} />
          <DemoButton demoKey="coach_delayed" loadingDemo={loadingDemo} onRunDemo={onRunDemo} />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm md:grid-cols-5">
        <DemoMetric label="Estimated length" value={metrics.lengthLabel} />
        <DemoMetric label="Divisions" value={metrics.divisionCount} />
        <DemoMetric label="Matches" value={metrics.matchCount} />
        <DemoMetric label="Athletes" value={metrics.athleteCount} />
        <DemoMetric label="Teams" value={metrics.teamCount} />
      </div>

      {error ? (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          {error}
        </div>
      ) : null}

      {result ? <DemoExplanation result={result} /> : null}
    </section>
  )
}

function buildDemoMetrics(tournament, schedule) {
  const allEvents = schedule.flatMap((ring) => ring.events || [])
  const makespan = allEvents.length ? Math.max(...allEvents.map((event) => event.end_minute || 0)) : 0
  const hours = Math.floor(makespan / 60)
  const minutes = makespan % 60
  const matchCount = (tournament?.divisions || []).reduce((total, division) => {
    if (division.event_type === 'kyorugi') {
      return total + Math.max(1, (division.bracket_size || division.competitor_count || 2) - 1)
    }
    return total + Math.max(1, division.competitor_count || division.athlete_ids?.length || 1)
  }, 0)

  return {
    lengthLabel: makespan ? `${hours}h ${minutes}m` : 'loading',
    divisionCount: tournament?.divisions?.length || 0,
    matchCount,
    athleteCount: tournament?.athletes?.length || 0,
    teamCount: tournament?.teams?.length || 0,
  }
}

function DemoMetric({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-bold text-slate-950">{value}</div>
    </div>
  )
}

function DemoButton({ demoKey, loadingDemo, onRunDemo }) {
  const isLoading = loadingDemo === demoKey

  return (
    <button
      type="button"
      onClick={() => onRunDemo(demoKey)}
      disabled={Boolean(loadingDemo)}
      className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-950 transition hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {isLoading ? 'Running...' : DEMO_LABELS[demoKey]}
    </button>
  )
}

function DemoExplanation({ result }) {
  const validationText = result.validationPassed
    ? 'Validation still passes because the resulting schedule keeps ring, referee, athlete, and coach conflicts out of overlapping time windows.'
    : 'Validation did not pass; review the validation errors before using this result.'

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-950">{result.title}</div>
          <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Strategy: {result.strategyLabel}
          </div>
        </div>
        <span
          className={`w-fit rounded px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${
            result.validationPassed ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
          }`}
        >
          {result.validationPassed ? 'validation passed' : 'validation failed'}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
        <ExplanationCard label="What happened" text={result.whatHappened} />
        <ExplanationCard label="What changed" text={result.whatChanged} />
        <ExplanationCard label="Why this strategy" text={result.whyStrategy} />
        <ExplanationCard label="Why validation passes" text={validationText} />
      </div>

      {result.metrics ? (
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <DemoMetric label="Changed matches" value={result.metrics.changedMatchCount} />
          <DemoMetric label="Average delay" value={`${result.metrics.averageDelayMinutes} min`} />
          <DemoMetric label="Max delay" value={`${result.metrics.maxDelayMinutes} min`} />
          <DemoMetric label="Queue repair" value={result.metrics.queueRepairApplied ? 'yes' : 'no'} />
        </div>
      ) : null}

      {result.emptyState ? (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          {result.emptyState}
        </div>
      ) : null}
    </div>
  )
}

function ExplanationCard({ label, text }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-slate-800">{text}</div>
    </div>
  )
}
