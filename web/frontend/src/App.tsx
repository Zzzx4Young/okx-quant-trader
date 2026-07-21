import { useState, useEffect } from 'react'
import { PortfolioPage } from './pages/Portfolio'
import { CronPage } from './pages/Cron'
import { QueryPage } from './pages/Query'
import './index.css'

type PageId = 'portfolio' | 'cron' | 'query'

const NAV_ITEMS: Array<{
  id: PageId
  label: string
  subtitle: string
}> = [
  { id: 'portfolio', label: 'Portfolio', subtitle: '持仓 + 历史' },
  { id: 'cron', label: 'Cron', subtitle: '运行时 + drift' },
  { id: 'query', label: 'Query', subtitle: '自然语言 (Phase 2b)' },
]

const PAGE_TITLES: Record<PageId, string> = {
  portfolio: 'Portfolio · OKX Web',
  cron: 'Cron · OKX Web',
  query: 'Query · OKX Web',
}

export default function App() {
  const [page, setPage] = useState<PageId>('portfolio')

  // Title regression fix: sync document.title with current page.
  useEffect(() => {
    document.title = PAGE_TITLES[page] ?? 'OKX Web'
  }, [page])

  return (
    <main>
      <header>
        <h1>OKX Web Dashboard</h1>
        <p className="subtitle">
          Phase 2 · v1.2.0 · 全只读 · bind 127.0.0.1:18787
        </p>
      </header>

      <nav className="tab-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`tab ${page === item.id ? 'tab-active' : ''}`}
            onClick={() => setPage(item.id)}
          >
            <span className="tab-label">{item.label}</span>
            <span className="tab-subtitle">{item.subtitle}</span>
          </button>
        ))}
      </nav>

      <section className="page-content">
        {page === 'portfolio' && <PortfolioPage />}
        {page === 'cron' && <CronPage />}
        {page === 'query' && <QueryPage />}
      </section>

      <footer>
        <p>
          See <code>okx/docs/WEB_DASHBOARD_DESIGN.md</code> · v1 LOCKED 2026-07-21.
        </p>
      </footer>
    </main>
  )
}
