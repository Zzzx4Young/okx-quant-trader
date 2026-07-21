import { useEffect, useState } from 'react'

type Position = {
  symbol: string | null
  direction: string | null
  entry_price: number | null
  size: number | null
  leverage: number | null
  margin: number | null
  sl_price: number | null
  tp_price: number | null
  strategy: string | null
  trigger_strategy: string | null
  opened_at: string | null
  mark_px_at_sync: number | null
  mgn_mode: string | null
}

type ClosedPosition = {
  symbol: string | null
  direction: string | null
  entry_price: number | null
  size: number | null
  leverage: number | null
  strategy: string | null
  closed_at: string | null
  realized_pnl: number | null
  close_source: string | null
}

type PortfolioFull = {
  updated_at: string | null
  version: string | null
  active_count: number
  closed_count: number
  daily_stats: {
    date?: string
    total_trades?: number
    loss_trades?: number
    consecutive_losses?: number
    total_pnl?: number
    total_fee?: number
    last_loss_at?: string | null
    emergency_stop_triggered?: boolean
  }
  summary: {
    total_margin_used: number
    daily_pnl: number | null
    daily_trades: number | null
    consecutive_losses: number | null
    emergency_stop: boolean
  }
  active: Position[]
  closed_recent: ClosedPosition[]
}

const POLL_MS = 10_000

export function PortfolioPage() {
  const [data, setData] = useState<PortfolioFull | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<string>('-')

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      try {
        const r = await fetch('/api/portfolio')
        if (!r.ok) throw new Error(`/api/portfolio ${r.status}`)
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
      <h2>
        Portfolio &mdash; {data ? `${data.active_count} active` : 'loading…'}
        {data?.updated_at && (
          <span className="muted"> · sync at {data.updated_at}</span>
        )}
      </h2>

      {error && (
        <div className="error">
          <h3>Error</h3>
          <pre>{error}</pre>
        </div>
      )}

      {data && (
        <>
          <div className="card-grid">
            <Card
              label="Active"
              value={String(data.active_count)}
            />
            <Card
              label="Daily PnL"
              value={fmtNum(data.summary.daily_pnl, 'USDT')}
              tone={
                data.summary.daily_pnl != null && data.summary.daily_pnl < 0
                  ? 'red'
                  : 'green'
              }
            />
            <Card
              label="Daily Trades"
              value={String(data.summary.daily_trades ?? '-')}
            />
            <Card
              label="Margin Used"
              value={fmtNum(data.summary.total_margin_used, 'USDT')}
            />
            <Card
              label="Consec Losses"
              value={String(data.summary.consecutive_losses ?? '-')}
              tone={(data.summary.consecutive_losses ?? 0) >= 3 ? 'red' : ''}
            />
            <Card
              label="Emergency"
              value={data.summary.emergency_stop ? 'TRIGGERED' : 'no'}
              tone={data.summary.emergency_stop ? 'red' : 'green'}
            />
          </div>

          <h3>Active Positions</h3>
          {data.active.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>symbol</th>
                  <th>dir</th>
                  <th>size</th>
                  <th>lev</th>
                  <th>entry</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>strategy</th>
                  <th>opened_at</th>
                </tr>
              </thead>
              <tbody>
                {data.active.map((p, i) => (
                  <tr
                    key={i}
                    className={
                      p.strategy === 'EXTERNAL_WEB_SYNC' ? 'external' : ''
                    }
                  >
                    <td>{p.symbol}</td>
                    <td>{p.direction}</td>
                    <td>{p.size}</td>
                    <td>{p.leverage}x</td>
                    <td>{p.entry_price?.toFixed(2)}</td>
                    <td>{p.sl_price?.toFixed(2)}</td>
                    <td>{p.tp_price?.toFixed(2)}</td>
                    <td>{p.strategy}</td>
                    <td className="muted">{p.opened_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No active positions.</p>
          )}

          <h3>
            Closed Positions &mdash; recent {data.closed_recent.length}{' '}
            <span className="muted">(total: {data.closed_count})</span>
          </h3>
          {data.closed_recent.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>symbol</th>
                  <th>dir</th>
                  <th>size</th>
                  <th>lev</th>
                  <th>entry</th>
                  <th>strategy</th>
                  <th>closed_at</th>
                  <th>realized_pnl</th>
                  <th>close_source</th>
                </tr>
              </thead>
              <tbody>
                {data.closed_recent
                  .slice()
                  .reverse()
                  .map((p, i) => (
                    <tr key={i}>
                      <td>{p.symbol}</td>
                      <td>{p.direction}</td>
                      <td>{p.size}</td>
                      <td>{p.leverage}x</td>
                      <td>{p.entry_price?.toFixed(2)}</td>
                      <td>{p.strategy}</td>
                      <td className="muted">{p.closed_at}</td>
                      <td
                        className={
                          p.realized_pnl != null && p.realized_pnl < 0
                            ? 'red'
                            : 'green'
                        }
                      >
                        {p.realized_pnl?.toFixed(4)}
                      </td>
                      <td className="muted">{p.close_source}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No closed positions.</p>
          )}

          {data.daily_stats.date && (
            <p className="muted">
              daily_stats · date={data.daily_stats.date} · loss_trades=
              {data.daily_stats.loss_trades} · total_fee=
              {data.daily_stats.total_fee?.toFixed(4)}
            </p>
          )}
        </>
      )}

      <p className="last-fetch">last fetch: {lastFetch}</p>
    </div>
  )
}

function Card({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'green' | 'red' | ''
}) {
  return (
    <div className={`card ${tone ? `card-${tone}` : ''}`}>
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
    </div>
  )
}

function fmtNum(v: number | null | undefined, suffix: string = ''): string {
  if (v == null) return '-'
  return `${v.toFixed(4)}${suffix ? ' ' + suffix : ''}`
}
