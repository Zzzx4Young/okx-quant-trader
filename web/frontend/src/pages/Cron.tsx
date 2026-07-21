import { useEffect, useState } from 'react'

type Drift = {
  threshold_seconds: number
  drift_seconds: number | null
  fallback_used: boolean
  boundary: string | null
  last_run_at: string | null
}

type Heartbeat = {
  last_run_at: string | null
  timeframe: string | null
  warmup_ms: number | null
  signal_triggered: boolean | null
  errors_count: number | null
}

type LastWorkflow = {
  success: boolean | null
  open_tick: boolean | null
  signal_triggered: boolean | null
  reconcile: Record<string, unknown> | null
  errors: unknown[] | null
  timestamp: string | null
}

type RecentSync = {
  at: string
  reason: string
  drift_detected: boolean
  ghost_closed_count: number
  new_synced_count: number
  actions: string[]
}

type CronData = {
  now: string
  drift: Drift
  heartbeat: Heartbeat
  last_workflow: LastWorkflow
  recent_syncs: RecentSync[]
  health_probe: {
    files: string[]
    probe_log_text: string | null
  }
}

const POLL_MS = 10_000

export function CronPage() {
  const [data, setData] = useState<CronData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<string>('-')

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      try {
        const r = await fetch('/api/cron')
        if (!r.ok) throw new Error(`/api/cron ${r.status}`)
        const json = await r.json()
        if (cancelled) return
        setData(json)
        setError(null)
        setLastFetch(new Date().toLocaleTimeString())
      } catch (e: unknown) {
        if (cancelled) return
        setError(String(e))
      }
    }
    fetchData()
    const id = setInterval(fetchData, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return (
    <div>
      <h2>Cron &mdash; Signal Runner Health</h2>

      {error && (
        <div className="error">
          <h3>Error</h3>
          <pre>{error}</pre>
        </div>
      )}

      {data && (
        <>
          <div
            className={`drift-card ${
              data.drift.fallback_used ? 'drift-card-red' : 'drift-card-green'
            }`}
          >
            <div className="card-label">Cold-start Drift</div>
            <div className="drift-value">
              {data.drift.drift_seconds != null
                ? `${data.drift.drift_seconds}s`
                : '-'}
            </div>
            <div className="drift-sub">
              {data.drift.fallback_used
                ? `⚠️ > ${data.drift.threshold_seconds}s threshold → fallback ran (no spinlock to boundary)`
                : `✓ within ${data.drift.threshold_seconds}s threshold`}
            </div>
            <div className="card-meta">
              <div>
                boundary: <code>{data.drift.boundary ?? '-'}</code>
              </div>
              <div>
                last_run_at: <code>{data.drift.last_run_at ?? '-'}</code>
              </div>
            </div>
          </div>

          <h3>Latest Heartbeat</h3>
          <table>
            <tbody>
              <tr>
                <td>last_run_at</td>
                <td>
                  <code>{data.heartbeat.last_run_at ?? '-'}</code>
                </td>
              </tr>
              <tr>
                <td>timeframe</td>
                <td>{data.heartbeat.timeframe ?? '-'}</td>
              </tr>
              <tr>
                <td>warmup_ms</td>
                <td>{data.heartbeat.warmup_ms ?? '-'}</td>
              </tr>
              <tr>
                <td>signal_triggered</td>
                <td>
                  <span
                    className={
                      data.heartbeat.signal_triggered
                        ? 'tag tag-yellow'
                        : 'tag tag-green'
                    }
                  >
                    {String(data.heartbeat.signal_triggered ?? '-')}
                  </span>
                </td>
              </tr>
              <tr>
                <td>errors_count</td>
                <td>
                  <span
                    className={
                      data.heartbeat.errors_count
                        ? 'tag tag-red'
                        : 'tag tag-green'
                    }
                  >
                    {data.heartbeat.errors_count ?? 0}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>

          <h3>Last Workflow Result</h3>
          <table>
            <tbody>
              <tr>
                <td>success</td>
                <td>{String(data.last_workflow.success ?? '-')}</td>
              </tr>
              <tr>
                <td>timestamp</td>
                <td>
                  <code>{data.last_workflow.timestamp ?? '-'}</code>
                </td>
              </tr>
              <tr>
                <td>tick</td>
                <td>{String(data.last_workflow.open_tick ?? '-')}</td>
              </tr>
              <tr>
                <td>signal_triggered</td>
                <td>
                  {String(data.last_workflow.signal_triggered ?? '-')}
                </td>
              </tr>
              <tr>
                <td>reconcile</td>
                <td>
                  <pre>
                    {JSON.stringify(
                      data.last_workflow.reconcile ?? null,
                      null,
                      2,
                    )}
                  </pre>
                </td>
              </tr>
              {data.last_workflow.errors &&
                data.last_workflow.errors.length > 0 && (
                  <tr>
                    <td>errors</td>
                    <td>
                      <pre>
                        {JSON.stringify(data.last_workflow.errors, null, 2)}
                      </pre>
                    </td>
                  </tr>
                )}
            </tbody>
          </table>

          <h3>Recent Syncs (last 10)</h3>
          {data.recent_syncs.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>at</th>
                  <th>reason</th>
                  <th>drift</th>
                  <th>ghost/new</th>
                  <th>actions</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_syncs
                  .slice()
                  .reverse()
                  .map((s, i) => (
                    <tr key={i}>
                      <td className="muted">{s.at}</td>
                      <td>{s.reason}</td>
                      <td>{String(s.drift_detected)}</td>
                      <td>
                        {s.ghost_closed_count}/{s.new_synced_count}
                      </td>
                      <td>
                        <ul className="actions-list">
                          {s.actions.map((a, j) => (
                            <li key={j}>
                              <code>{a}</code>
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No sync history yet.</p>
          )}

          <h3>Health Probe</h3>
          {data.health_probe.files.length > 0 ? (
            <>
              <p className="muted">
                Files: {data.health_probe.files.join(', ')}
              </p>
              {data.health_probe.probe_log_text && (
                <pre className="probe-log">
                  {data.health_probe.probe_log_text}
                </pre>
              )}
            </>
          ) : (
            <p className="muted">No probe files found.</p>
          )}
        </>
      )}

      <p className="last-fetch">last fetch: {lastFetch}</p>
    </div>
  )
}
