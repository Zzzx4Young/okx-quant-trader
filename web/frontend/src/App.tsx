import { useEffect, useState } from 'react'
import {
  AppShell,
  Burger,
  Group,
  NavLink,
  ScrollArea,
  Text,
  Title,
  Badge,
  Stack,
  Divider,
  Anchor,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { PortfolioPage } from './pages/Portfolio'
import { CronPage } from './pages/Cron'
import { QueryPage } from './pages/Query'
import { BacktestListPage } from './pages/BacktestList'
import { BacktestDetailPage } from './pages/BacktestDetail'
import { BacktestComparePage } from './pages/BacktestCompare'

type RunSummary = {
  id: string
  name: string
  timestamp: string | null
  git_commit: string | null
  strategy: string | null
  symbol: string | null
  bar: string | null
  leverage: number | null
  buy_hold_ret_pct: number | null
  slippage_bps_list: number[]  // Phase 2C: bar-axis heatmap 需要（与 BacktestCompare 对齐）
  fee_bps_list: number[]
  n_cells: number
  viable_count: number
  best_ret_pct: number | null
  best_sharpe: number | null
}

type PageId = 'portfolio' | 'cron' | 'query' | 'backtest-list' | 'backtest-detail' | 'backtest-compare'

const NAV_ITEMS: Array<{
  id: PageId
  label: string
  description: string
  badge?: string
}> = [
  {
    id: 'portfolio',
    label: 'Portfolio',
    description: '持仓 · 历史 · 累计 PnL',
  },
  {
    id: 'cron',
    label: 'Cron Health',
    description: 'Drift · Heartbeat · Syncs',
  },
  {
    id: 'query',
    label: 'Query (AI)',
    description: '自然语言查询 · Phase 2b',
    badge: 'stub',
  },
  {
    id: 'backtest-list',
    label: 'Backtest',
    description: 'fragility_scan 输出 · 网格热力图 · equity 叠加',
    badge: 'new',
  },
]

const PAGE_TITLES: Record<PageId, string> = {
  portfolio: 'Portfolio · OKX Web',
  cron: 'Cron · OKX Web',
  query: 'Query · OKX Web',
  'backtest-list': 'Backtest · OKX Web',
  'backtest-detail': 'Backtest Detail · OKX Web',
  'backtest-compare': 'Compare · OKX Web',
}

export default function App() {
  const [page, setPage] = useState<PageId>('portfolio')
  const [opened, { toggle }] = useDisclosure()

  // Backtest 跨页共享状态
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [compareRunIds, setCompareRunIds] = useState<string[]>([])
  const [allRuns, setAllRuns] = useState<RunSummary[]>([])

  // 在 backtest 页时拉取所有 run 列表（compare 页用）
  useEffect(() => {
    if (!page.startsWith('backtest')) return
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch('/api/backtest/runs')
        if (!r.ok) return
        const json = await r.json()
        if (!cancelled) setAllRuns(json.runs ?? [])
      } catch {
        // 静默失败 — list 页面也会自己 fetch
      }
    })()
    return () => {
      cancelled = true
    }
  }, [page])

  useEffect(() => {
    document.title = PAGE_TITLES[page] ?? 'OKX Web'
  }, [page])

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !opened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
            />
            <Title order={4}>OKX Web Dashboard</Title>
            <Badge variant="light" color="blue" size="sm">
              v1.4.0
            </Badge>
            <Badge variant="light" color="gray" size="sm">
              bind 127.0.0.1:18787
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {new Date().toLocaleDateString('zh-CN', {
              year: 'numeric',
              month: '2-digit',
              day: '2-digit',
            })}
          </Text>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <AppShell.Section>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb="xs">
            Pages
          </Text>
        </AppShell.Section>
        <AppShell.Section grow component={ScrollArea}>
          <Stack gap={4}>
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.id}
                active={page === item.id}
                label={item.label}
                description={item.description}
                rightSection={
                  item.badge ? (
                    <Badge size="xs" color="yellow" variant="light">
                      {item.badge}
                    </Badge>
                  ) : null
                }
                onClick={() => {
                  setPage(item.id)
                  if (opened) toggle()
                }}
              />
            ))}
          </Stack>
        </AppShell.Section>
        <Divider my="sm" />
        <AppShell.Section>
          <Text size="xs" c="dimmed">
            全只读 · 后端 uvicorn 单进程 serve <br />
            <Anchor
              size="xs"
              href="https://api.minimaxi.com"
              target="_blank"
              rel="noreferrer"
            >
              Phase 2b · api.minimaxi.com
            </Anchor>
          </Text>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        {page === 'portfolio' && <PortfolioPage />}
        {page === 'cron' && <CronPage />}
        {page === 'query' && <QueryPage />}
        {page === 'backtest-list' && (
          <BacktestListPage
            onSelect={(id) => {
              setSelectedRunId(id)
              setPage('backtest-detail')
            }}
          />
        )}
        {page === 'backtest-detail' && selectedRunId && (
          <BacktestDetailPage
            runId={selectedRunId}
            onBack={() => setPage('backtest-list')}
            onAddToCompare={(id) => {
              if (!compareRunIds.includes(id)) {
                setCompareRunIds([...compareRunIds, id])
              }
              setPage('backtest-compare')
            }}
          />
        )}
        {page === 'backtest-compare' && (
          <BacktestComparePage
            runIds={compareRunIds}
            setRunIds={setCompareRunIds}
            allRuns={allRuns}
            onSelect={(id) => {
              setSelectedRunId(id)
              setPage('backtest-detail')
            }}
          />
        )}
      </AppShell.Main>
    </AppShell>
  )
}