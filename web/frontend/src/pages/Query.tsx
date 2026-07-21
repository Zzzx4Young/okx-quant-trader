import { useState } from 'react'

type QueryResponse = {
  ok: boolean
  intent: string
  query: string
  answer: string
  extras: Record<string, unknown>
  version: string
}

const SAMPLE_QUERIES = [
  'BTC 仓位怎么样?',
  'ETH 仓位?',
  '今日 PnL?',
  '策略分布?',
  '所有持仓?',
]

export function QueryPage() {
  const [query, setQuery] = useState('')
  const [response, setResponse] = useState<QueryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (q: string) => {
    if (!q.trim()) return
    setLoading(true)
    setError(null)
    setQuery(q)
    try {
      const r = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      })
      if (!r.ok) throw new Error(`/api/query ${r.status}`)
      const json = await r.json()
      setResponse(json)
    } catch (e: unknown) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2>Query &mdash; 自然语言查询持仓</h2>
      <p className="muted">
        Phase 2a: keyword-routed stub (BTC / ETH / PnL / 策略 / 持仓).{' '}
        Phase 2b: LLM integration via api.minimaxi.com — once creds + model
        wired.
      </p>

      <div className="query-form">
        <input
          type="text"
          className="query-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入 query,例如 'BTC 仓位'"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !loading) submit(query)
          }}
        />
        <button
          className="query-button"
          onClick={() => submit(query)}
          disabled={loading || !query.trim()}
        >
          {loading ? '...' : '提交'}
        </button>
      </div>

      <div className="sample-queries">
        <span className="muted">样例:</span>
        {SAMPLE_QUERIES.map((q, i) => (
          <button
            key={i}
            className="sample-chip"
            onClick={() => submit(q)}
            disabled={loading}
          >
            {q}
          </button>
        ))}
      </div>

      {error && (
        <div className="error">
          <h3>Error</h3>
          <pre>{error}</pre>
        </div>
      )}

      {response && (
        <div className="query-response">
          <h3>Response</h3>
          <dl>
            <dt>intent</dt>
            <dd>
              <span className="tag tag-blue">{response.intent}</span>
            </dd>
            <dt>query</dt>
            <dd>
              <code>{response.query}</code>
            </dd>
            <dt>answer</dt>
            <dd>{response.answer}</dd>
            <dt>version</dt>
            <dd className="muted">{response.version}</dd>
            {Object.keys(response.extras).length > 0 && (
              <>
                <dt>extras</dt>
                <dd>
                  <pre>{JSON.stringify(response.extras, null, 2)}</pre>
                </dd>
              </>
            )}
          </dl>
        </div>
      )}
    </div>
  )
}
