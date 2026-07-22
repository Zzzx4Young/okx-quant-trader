import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Card,
  Center,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { LineChart } from '@mantine/charts'
import dayjs from 'dayjs'

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
  unrealized_pnl_usd?: number | null
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
    margin_source?: string
    unrealized_pnl?: number | null
    daily_pnl: number | null
    daily_trades: number | null
    consecutive_losses: number | null
    emergency_stop: boolean
  }
  risk_metrics?: {
    source: 'okx_live' | 'cache_fresh' | 'cache_stale' | 'unavailable'
    equity_usd?: number
    gross_notional_usd?: number
    net_notional_usd?: number
    gross_leverage?: number
    net_leverage?: number
    margin_used_usd?: number
    account_used_margin_usd?: number
    unrealized_pnl_usd?: number | null
    unrealized_pnl_per_position?: Record<string, number>
    inst_concentration?: number
    inst_concentration_symbol?: string | null
    strategy_concentration?: number
    strategy_concentration_name?: string | null
    min_liq_distance_pct?: number | null
    min_liq_distance_symbol?: string | null
    error?: string
  }
  active: Position[]
  closed_recent: ClosedPosition[]
}

const POLL_MS = 10_000

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '-'
  return n.toFixed(digits)
}

function pnlTone(n: number | null | undefined): 'red' | 'green' | undefined {
  if (n == null) return undefined
  if (n < 0) return 'red'
  if (n > 0) return 'green'
  return undefined
}

function shortSymbol(s: string | null): string {
  if (!s) return '-'
  return s.replace('USDTSWAP', '').replace('-SWAP', '')
}

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
        setLastFetch(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
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

  // OKX v5 quirk: closed_recent is newest → oldest. Reverse + cumulative sum.
  const pnlSeries = useMemo(() => {
    if (!data) return []
    const sorted = [...data.closed_recent].sort((a, b) => {
      const ta = new Date(a.closed_at ?? 0).getTime()
      const tb = new Date(b.closed_at ?? 0).getTime()
      return ta - tb
    })
    let cum = 0
    return sorted.map((p) => {
      cum += p.realized_pnl ?? 0
      return {
        date: dayjs(p.closed_at).format('MM-DD HH:mm'),
        pnl: parseFloat((p.realized_pnl ?? 0).toFixed(4)),
        cumulative: parseFloat(cum.toFixed(4)),
      }
    })
  }, [data])

  const totalRealized = useMemo(() => {
    if (!data) return null
    return data.closed_recent.reduce(
      (acc, p) => acc + (p.realized_pnl ?? 0),
      0,
    )
  }, [data])

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>
            Portfolio · {data ? `${data.active_count} active` : 'loading…'}
          </Title>
          <Text size="xs" c="dimmed">
            sync at {data?.updated_at ?? '-'}
          </Text>
        </div>
        <Text size="xs" c="dimmed">
          last fetch: {lastFetch}
        </Text>
      </Group>

      {error && (
        <Alert color="red" title="Fetch error">
          <pre style={{ margin: 0 }}>{error}</pre>
        </Alert>
      )}

      {!data && !error && (
        <Center>
          <Loader />
        </Center>
      )}

      {data && (
        <>
          <SimpleGrid cols={{ base: 2, sm: 3, md: 4, lg: 8 }} spacing="sm">
            <StatCard
              label="Active"
              value={String(data.active_count)}
            />
            <StatCard
              label="Today's Total P&L"
              value={fmt(
                (data.summary.daily_pnl ?? 0) + (data.summary.unrealized_pnl ?? 0),
                4,
              )}
              suffix="USDT"
              sublabel="realized + unrealized"
              tone={pnlTone(
                (data.summary.daily_pnl ?? 0) + (data.summary.unrealized_pnl ?? 0),
              )}
            />
            <StatCard
              label="Daily Realized PnL"
              value={fmt(data.summary.daily_pnl, 4)}
              suffix="USDT"
              sublabel="closed trades only"
              tone={pnlTone(data.summary.daily_pnl)}
            />
            <StatCard
              label="Unrealized PnL"
              value={fmt(data.summary.unrealized_pnl ?? null, 4)}
              suffix="USDT"
              sublabel="open positions mark-to-market"
              tone={pnlTone(data.summary.unrealized_pnl ?? null)}
            />
            <StatCard
              label="Daily Trades"
              value={String(data.summary.daily_trades ?? '-')}
            />
            <StatCard
              label="Margin Used"
              value={fmt(data.summary.total_margin_used, 2)}
              suffix="USDT"
              sublabel={
                data.summary.margin_source
                  ? `source: ${data.summary.margin_source}`
                  : undefined
              }
            />
            <StatCard
              label="Consec Losses"
              value={String(data.summary.consecutive_losses ?? '-')}
              tone={
                (data.summary.consecutive_losses ?? 0) >= 3 ? 'red' : undefined
              }
            />
            <StatCard
              label="Emergency"
              value={data.summary.emergency_stop ? 'TRIGGERED' : 'no'}
              tone={data.summary.emergency_stop ? 'red' : 'green'}
            />
          </SimpleGrid>

          {data.risk_metrics && (
            <Card withBorder shadow="sm" padding="md">
              <Group justify="space-between" mb="xs">
                <Title order={4}>
                  Risk Metrics{' '}
                  <Text component="span" size="sm" c="dimmed">
                    OKX V5 · {data.risk_metrics.source.replace('_', ' ')}
                  </Text>
                </Title>
                {data.risk_metrics.source === 'unavailable' && (
                  <Badge color="yellow" variant="light">
                    {data.risk_metrics.error ?? 'unavailable'}
                  </Badge>
                )}
              </Group>
              <SimpleGrid cols={{ base: 2, sm: 3, md: 4, lg: 7 }} spacing="sm">
                <StatCard
                  label="Equity"
                  value={fmt(data.risk_metrics.equity_usd, 2)}
                  suffix="USDT"
                />
                <StatCard
                  label="Gross Notional"
                  value={fmt(data.risk_metrics.gross_notional_usd, 2)}
                  suffix="USDT"
                />
                <StatCard
                  label="Gross Leverage"
                  value={fmt(data.risk_metrics.gross_leverage, 4)}
                  suffix="x"
                />
                <StatCard
                  label="Unrealized PnL %"
                  value={
                    data.risk_metrics.equity_usd && data.risk_metrics.unrealized_pnl_usd != null
                      ? `${((data.risk_metrics.unrealized_pnl_usd / data.risk_metrics.equity_usd) * 100).toFixed(3)}%`
                      : '-'
                  }
                  sublabel="open positions vs equity"
                  tone={
                    data.risk_metrics.unrealized_pnl_usd == null
                      ? undefined
                      : data.risk_metrics.unrealized_pnl_usd >= 0
                        ? 'green'
                        : 'red'
                  }
                />
                <StatCard
                  label="Inst Concentration"
                  value={
                    data.risk_metrics.inst_concentration != null
                      ? `${(data.risk_metrics.inst_concentration * 100).toFixed(1)}%`
                      : '-'
                  }
                  sublabel={
                    data.risk_metrics.inst_concentration_symbol ?? '-'
                  }
                  tone={
                    (data.risk_metrics.inst_concentration ?? 0) > 0.5
                      ? 'yellow'
                      : undefined
                  }
                />
                <StatCard
                  label="Strategy Concentration"
                  value={
                    data.risk_metrics.strategy_concentration != null
                      ? `${(data.risk_metrics.strategy_concentration * 100).toFixed(1)}%`
                      : '-'
                  }
                  sublabel={
                    data.risk_metrics.strategy_concentration_name ?? '-'
                  }
                  tone={
                    (data.risk_metrics.strategy_concentration ?? 0) >= 1
                      ? 'yellow'
                      : undefined
                  }
                />
                <StatCard
                  label="Min Liq Distance"
                  value={
                    data.risk_metrics.min_liq_distance_pct != null
                      ? `${(data.risk_metrics.min_liq_distance_pct * 100).toFixed(2)}%`
                      : '-'
                  }
                  sublabel={
                    data.risk_metrics.min_liq_distance_symbol ?? '-'
                  }
                  tone={
                    (data.risk_metrics.min_liq_distance_pct ?? 1) < 0.1
                      ? 'red'
                      : (data.risk_metrics.min_liq_distance_pct ?? 1) < 0.25
                        ? 'yellow'
                        : 'green'
                  }
                />
              </SimpleGrid>
            </Card>
          )}

          {pnlSeries.length > 0 && (
            <Card withBorder shadow="sm" padding="md">
              <Group justify="space-between" mb="xs">
                <Title order={4}>
                  Cumulative PnL ·{' '}
                  <Text component="span" c="dimmed" size="md">
                    {data.closed_recent.length} closed trades
                  </Text>
                </Title>
                <Text size="sm" c={pnlTone(totalRealized)} fw={600}>
                  Total realized: {fmt(totalRealized, 4)} USDT
                </Text>
              </Group>
              <LineChart
                h={220}
                data={pnlSeries}
                dataKey="date"
                series={[
                  {
                    name: 'cumulative',
                    color: 'blue.6',
                    label: 'Cumulative PnL',
                  },
                ]}
                curveType="monotone"
                withDots={false}
                withLegend={false}
                valueFormatter={(v) => `${v.toFixed(2)} USDT`}
                yAxisProps={{ width: 70 }}
              />
            </Card>
          )}

          <Card withBorder shadow="sm" padding="md">
            <Title order={4} mb="xs">
              Active Positions
            </Title>
            {data.active.length === 0 ? (
              <Text c="dimmed">No active positions.</Text>
            ) : (
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Symbol</Table.Th>
                    <Table.Th>Dir</Table.Th>
                    <Table.Th>Size</Table.Th>
                    <Table.Th>Lev</Table.Th>
                    <Table.Th>Entry</Table.Th>
                    <Table.Th>SL</Table.Th>
                    <Table.Th>TP</Table.Th>
                    <Table.Th>uPnL</Table.Th>
                    <Table.Th>Strategy</Table.Th>
                    <Table.Th>Opened</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {data.active.map((p, i) => (
                    <Table.Tr key={i}>
                      <Table.Td fw={600}>{shortSymbol(p.symbol)}</Table.Td>
                      <Table.Td>
                        <Badge
                          color={p.direction === 'long' ? 'green' : 'red'}
                          variant="light"
                          size="sm"
                        >
                          {p.direction}
                        </Badge>
                      </Table.Td>
                      <Table.Td>{p.size}</Table.Td>
                      <Table.Td>{p.leverage}x</Table.Td>
                      <Table.Td>{fmt(p.entry_price)}</Table.Td>
                      <Table.Td>{fmt(p.sl_price)}</Table.Td>
                      <Table.Td>{fmt(p.tp_price)}</Table.Td>
                      <Table.Td>
                        <Text c={pnlTone(p.unrealized_pnl_usd)} fw={600}>
                          {fmt(p.unrealized_pnl_usd, 4)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge variant="default" size="sm">
                          {p.strategy}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {p.opened_at}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </Card>

          <Card withBorder shadow="sm" padding="md">
            <Group justify="space-between" mb="xs">
              <Title order={4}>Closed Positions · recent</Title>
              <Text size="sm" c="dimmed">
                showing {data.closed_recent.length} of {data.closed_count} total
              </Text>
            </Group>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Symbol</Table.Th>
                  <Table.Th>Dir</Table.Th>
                  <Table.Th>Size</Table.Th>
                  <Table.Th>Lev</Table.Th>
                  <Table.Th>Strategy</Table.Th>
                  <Table.Th>Closed</Table.Th>
                  <Table.Th>PnL</Table.Th>
                  <Table.Th>Source</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.closed_recent.map((p, i) => (
                  <Table.Tr key={i}>
                    <Table.Td fw={600}>{shortSymbol(p.symbol)}</Table.Td>
                    <Table.Td>
                      <Badge
                        color={p.direction === 'long' ? 'green' : 'red'}
                        variant="light"
                        size="sm"
                      >
                        {p.direction}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{p.size}</Table.Td>
                    <Table.Td>{p.leverage}x</Table.Td>
                    <Table.Td>
                      <Badge variant="default" size="sm">
                        {p.strategy}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {p.closed_at}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text c={pnlTone(p.realized_pnl)} fw={600}>
                        {fmt(p.realized_pnl, 4)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {p.close_source ?? '-'}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </>
      )}
    </Stack>
  )
}

function StatCard({
  label,
  value,
  suffix,
  sublabel,
  tone,
}: {
  label: string
  value: string
  suffix?: string
  sublabel?: string
  tone?: 'red' | 'green' | 'yellow'
}) {
  return (
    <Card withBorder padding="sm">
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      <Group gap={4} mt={4} align="baseline">
        <Text size="lg" fw={700} c={tone}>
          {value}
        </Text>
        {suffix && (
          <Text size="xs" c="dimmed">
            {suffix}
          </Text>
        )}
      </Group>
      {sublabel && (
        <Text size="xs" c="dimmed" mt={2} truncate>
          {sublabel}
        </Text>
      )}
    </Card>
  )
}