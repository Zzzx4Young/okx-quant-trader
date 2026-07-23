import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Modal,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { LineChart } from '@mantine/charts'
import dayjs from 'dayjs'

type CellSummary = {
  label: string
  slippage_bps: number
  fee_bps: number
  ret_pct: number | null
  sharpe: number | null
  maxDD_pct: number | null
  trades: number | null
  win_rate_pct: number | null
  slip_cost: number | null
  fee_paid: number | null
  viable: boolean | null
  has_equity: boolean
  has_trades: boolean
}

type RunMeta = {
  id: string
  scan_name?: string
  timestamp: string | null
  strategy: string | null
  symbol: string | null
  bar: string | null
  leverage: number | null
  initial_capital: number | null
  buy_hold_ret_pct: number | null
  slippage_bps_list: number[]
  fee_bps_list: number[]
  git_commit: string | null
  grid?: Array<{
    ret_pct?: number
    sharpe?: number
    maxDD_pct?: number
    trades?: number
    win_rate_pct?: number
  }>
}

type EquityPoint = {
  timestamp: number
  equity: number
}

type Props = {
  runId: string
  onBack: () => void
  onAddToCompare: (runId: string) => void
}

function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '-'
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`
}

function tone(n: number | null | undefined): 'red' | 'green' | undefined {
  if (n == null) return undefined
  if (n < 0) return 'red'
  if (n > 0) return 'green'
  return undefined
}

// Map ret_pct to Mantine color shade (3 levels per side).
// Returns CSS var name like "var(--mantine-color-red-6)" or null.
function heatColor(ret: number | null | undefined): string | null {
  if (ret == null) return null
  const mag = Math.abs(ret)
  if (ret > 0) {
    if (mag >= 5) return 'var(--mantine-color-green-8)'
    if (mag >= 2) return 'var(--mantine-color-green-6)'
    return 'var(--mantine-color-green-4)'
  } else if (ret < 0) {
    if (mag >= 5) return 'var(--mantine-color-red-8)'
    if (mag >= 2) return 'var(--mantine-color-red-6)'
    return 'var(--mantine-color-red-4)'
  }
  return 'var(--mantine-color-gray-5)'
}

export function BacktestDetailPage({ runId, onBack, onAddToCompare }: Props) {
  const [meta, setMeta] = useState<RunMeta | null>(null)
  const [cells, setCells] = useState<CellSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Modal state for cell drill-down
  const [selectedCell, setSelectedCell] = useState<CellSummary | null>(null)
  const [equity, setEquity] = useState<EquityPoint[]>([])
  const [equityLoading, setEquityLoading] = useState(false)

  // Fetch meta + cells
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setMeta(null)
    setCells([])
    setError(null)
    ;(async () => {
      try {
        const [metaR, cellsR] = await Promise.all([
          fetch(`/api/backtest/runs/${runId}`),
          fetch(`/api/backtest/runs/${runId}/cells`),
        ])
        if (!metaR.ok) throw new Error(`/api/backtest/runs/${runId} ${metaR.status}`)
        if (!cellsR.ok)
          throw new Error(`/api/backtest/runs/${runId}/cells ${cellsR.status}`)
        const [metaJson, cellsJson] = await Promise.all([
          metaR.json(),
          cellsR.json(),
        ])
        if (cancelled) return
        setMeta(metaJson)
        setCells(cellsJson.cells ?? [])
      } catch (e: unknown) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runId])

  // Fetch equity when cell selected
  useEffect(() => {
    if (!selectedCell) {
      setEquity([])
      return
    }
    let cancelled = false
    setEquityLoading(true)
    ;(async () => {
      try {
        const r = await fetch(
          `/api/backtest/runs/${runId}/cells/${selectedCell.label}/equity`,
        )
        if (!r.ok) throw new Error(`equity fetch ${r.status}`)
        const json = await r.json()
        if (cancelled) return
        // Build chart-friendly data
        const pts: EquityPoint[] = (json.timestamp ?? []).map(
          (ts: number, i: number) => ({
            timestamp: ts,
            equity: json.equity[i],
          }),
        )
        setEquity(pts)
      } catch (e: unknown) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setEquityLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedCell, runId])

  // ── Downsample equity for chart (every Nth point) ──
  const equityChartData = useMemo(() => {
    if (equity.length === 0) return []
    // Target ~500 points max for fast rendering
    const TARGET = 500
    const step = Math.max(1, Math.floor(equity.length / TARGET))
    const out = []
    for (let i = 0; i < equity.length; i += step) {
      out.push({
        time: dayjs(equity[i].timestamp).format('YYYY-MM-DD HH:mm'),
        equity: parseFloat(equity[i].equity.toFixed(4)),
      })
    }
    // Always include last point
    if (out[out.length - 1].time !== dayjs(equity[equity.length - 1].timestamp).format('YYYY-MM-DD HH:mm')) {
      const last = equity[equity.length - 1]
      out.push({
        time: dayjs(last.timestamp).format('YYYY-MM-DD HH:mm'),
        equity: parseFloat(last.equity.toFixed(4)),
      })
    }
    return out
  }, [equity])

  const cellByLabel = useMemo(() => {
    const m = new Map<string, CellSummary>()
    for (const c of cells) m.set(c.label, c)
    return m
  }, [cells])

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Group gap="xs">
            <Button variant="subtle" size="xs" onClick={onBack}>
              ← Back
            </Button>
            <Title order={2}>
              {meta?.scan_name ?? runId}
            </Title>
          </Group>
          <Text size="xs" c="dimmed">
            {meta?.strategy} · {meta?.symbol} ({meta?.bar}) · {meta?.leverage}x ·{' '}
            {meta?.timestamp ? dayjs(meta.timestamp).format('YYYY-MM-DD HH:mm:ss') : '-'}
            {meta?.git_commit && (
              <Text component="span" ff="monospace" ml="sm">
                {meta.git_commit.slice(0, 7)}
              </Text>
            )}
          </Text>
        </div>
        <Button
          variant="light"
          onClick={() => onAddToCompare(runId)}
          disabled={!meta}
        >
          Add to compare →
        </Button>
      </Group>

      {error && (
        <Alert color="red" title="Fetch error">
          <pre style={{ margin: 0 }}>{error}</pre>
        </Alert>
      )}

      {loading && (
        <Center>
          <Loader />
        </Center>
      )}

      {!loading && meta && (
        <>
          {/* ── Meta stats ── */}
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
            <StatCard
              label="Buy & Hold Ref"
              value={
                meta.buy_hold_ret_pct != null
                  ? `${meta.buy_hold_ret_pct.toFixed(2)}%`
                  : '-'
              }
            />
            <StatCard
              label="Cells"
              value={`${cells.filter((c) => c.viable).length}/${cells.length} viable`}
            />
            <StatCard
              label="Initial Capital"
              value={
                meta.initial_capital != null
                  ? `$${meta.initial_capital.toFixed(0)}`
                  : '-'
              }
            />
            <StatCard
              label="Slip × Fee"
              value={`${meta.slippage_bps_list.length}×${meta.fee_bps_list.length}`}
            />
          </SimpleGrid>

          {/* ── Heatmap (slip × fee grid) ── */}
          <Card withBorder shadow="sm" padding="md">
            <Title order={4} mb="xs">
              Grid Heatmap ·{' '}
              <Text component="span" size="sm" c="dimmed">
                click cell for equity curve
              </Text>
            </Title>
            <div style={{ overflowX: 'auto' }}>
              <Table withTableBorder withColumnBorders>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th style={{ backgroundColor: 'var(--mantine-color-dark-7)' }}>
                      fee ↓ \ slip →
                    </Table.Th>
                    {meta.slippage_bps_list.map((slip) => (
                      <Table.Th
                        key={slip}
                        style={{
                          textAlign: 'center',
                          backgroundColor: 'var(--mantine-color-dark-7)',
                        }}
                      >
                        {slip} bps
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {meta.fee_bps_list.map((fee) => (
                    <Table.Tr key={fee}>
                      <Table.Th
                        style={{
                          backgroundColor: 'var(--mantine-color-dark-7)',
                          textAlign: 'center',
                        }}
                      >
                        {fee.toFixed(1)} bps
                      </Table.Th>
                      {meta.slippage_bps_list.map((slip) => {
                        const label = `slip${slip}_fee${fee.toFixed(1)}`.replace(
                          '.',
                          'p',
                        )
                        const cell = cellByLabel.get(label)
                        const ret = cell?.ret_pct
                        const bg = heatColor(ret)
                        const viable = cell?.viable
                        return (
                          <Table.Td
                            key={slip}
                            style={{
                              backgroundColor: bg ?? 'var(--mantine-color-dark-9)',
                              cursor: cell?.has_equity ? 'pointer' : 'default',
                              textAlign: 'center',
                              padding: '10px 14px',
                              opacity: cell?.has_equity ? 1 : 0.5,
                            }}
                            onClick={() => {
                              if (cell?.has_equity) setSelectedCell(cell)
                            }}
                          >
                            {cell ? (
                              <Tooltip
                                label={
                                  <div style={{ fontSize: 11 }}>
                                    <div>ret: {fmtPct(ret, 3)}</div>
                                    <div>sharpe: {cell.sharpe?.toFixed(3) ?? '-'}</div>
                                    <div>trades: {cell.trades ?? '-'}</div>
                                    <div>viable: {viable ? '✅' : '❌'}</div>
                                  </div>
                                }
                                withArrow
                              >
                                <Stack gap={0} align="center">
                                  <Text
                                    size="sm"
                                    fw={700}
                                    c={bg && bg.includes('green') ? 'white' : bg && bg.includes('red') ? 'white' : undefined}
                                  >
                                    {fmtPct(ret, 2)}
                                  </Text>
                                  <Text
                                    size="xs"
                                    c={bg && bg.includes('green') ? 'white' : bg && bg.includes('red') ? 'white' : 'dimmed'}
                                  >
                                    {viable ? '✓ viable' : '✗'}
                                  </Text>
                                </Stack>
                              </Tooltip>
                            ) : (
                              <Text size="xs" c="dimmed">
                                N/A
                              </Text>
                            )}
                          </Table.Td>
                        )
                      })}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </div>
          </Card>

          {/* ── Top cells summary ── */}
          <Card withBorder shadow="sm" padding="md">
            <Title order={4} mb="xs">
              Top cells by Sharpe
            </Title>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Cell</Table.Th>
                  <Table.Th>Ret</Table.Th>
                  <Table.Th>Sharpe</Table.Th>
                  <Table.Th>MaxDD</Table.Th>
                  <Table.Th>Trades</Table.Th>
                  <Table.Th>Win%</Table.Th>
                  <Table.Th>Viable</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {[...cells]
                  .sort(
                    (a, b) => (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity),
                  )
                  .slice(0, 8)
                  .map((c) => (
                    <Table.Tr
                      key={c.label}
                      style={{ cursor: c.has_equity ? 'pointer' : 'default' }}
                      onClick={() => {
                        if (c.has_equity) setSelectedCell(c)
                      }}
                    >
                      <Table.Td ff="monospace">{c.label}</Table.Td>
                      <Table.Td>
                        <Text c={tone(c.ret_pct)} fw={600}>
                          {fmtPct(c.ret_pct, 3)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text c={tone(c.sharpe)}>{c.sharpe?.toFixed(3) ?? '-'}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Text c="red">{fmtPct(c.maxDD_pct, 2)}</Text>
                      </Table.Td>
                      <Table.Td>{c.trades ?? '-'}</Table.Td>
                      <Table.Td>
                        {c.win_rate_pct != null
                          ? `${c.win_rate_pct.toFixed(1)}%`
                          : '-'}
                      </Table.Td>
                      <Table.Td>
                        {c.viable === true && (
                          <Badge color="green" variant="light" size="sm">
                            ✓
                          </Badge>
                        )}
                        {c.viable === false && (
                          <Badge color="red" variant="light" size="sm">
                            ✗
                          </Badge>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
              </Table.Tbody>
            </Table>
          </Card>
        </>
      )}

      {/* ── Cell drill-down Modal ── */}
      <Modal
        opened={!!selectedCell}
        onClose={() => setSelectedCell(null)}
        title={
          selectedCell && (
            <Group>
              <Text fw={700} ff="monospace">
                {selectedCell.label}
              </Text>
              <Badge variant="light">
                slip={selectedCell.slippage_bps}bps / fee=
                {selectedCell.fee_bps.toFixed(1)}bps
              </Badge>
            </Group>
          )
        }
        size="xl"
      >
        {selectedCell && (
          <Stack gap="md">
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
              <StatCard
                label="Return"
                value={fmtPct(selectedCell.ret_pct, 3)}
                tone={tone(selectedCell.ret_pct)}
              />
              <StatCard
                label="Sharpe"
                value={selectedCell.sharpe?.toFixed(3) ?? '-'}
                tone={tone(selectedCell.sharpe)}
              />
              <StatCard
                label="MaxDD"
                value={fmtPct(selectedCell.maxDD_pct, 2)}
                tone="red"
              />
              <StatCard
                label="Win Rate"
                value={
                  selectedCell.win_rate_pct != null
                    ? `${selectedCell.win_rate_pct.toFixed(1)}%`
                    : '-'
                }
              />
            </SimpleGrid>

            {equityLoading && (
              <Center>
                <Loader size="sm" />
              </Center>
            )}
            {!equityLoading && equityChartData.length > 0 && (
              <LineChart
                h={320}
                data={equityChartData}
                dataKey="time"
                series={[
                  {
                    name: 'equity',
                    color: 'blue.6',
                    label: 'Equity',
                  },
                ]}
                curveType="monotone"
                withDots={false}
                withLegend={false}
                valueFormatter={(v) => `$${v.toFixed(2)}`}
                yAxisProps={{ width: 70 }}
                xAxisProps={{ angle: 0, textAnchor: 'middle' }}
                tickLine="y"
                gridAxis="xy"
              />
            )}
            {!equityLoading && equity.length === 0 && (
              <Alert color="yellow">
                No equity data available for this cell.
              </Alert>
            )}
            <Text size="xs" c="dimmed">
              equity curve downsampled to ~{equityChartData.length} points for chart rendering
              (raw: {equity.length})
            </Text>
          </Stack>
        )}
      </Modal>
    </Stack>
  )
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'red' | 'green'
}) {
  return (
    <Card withBorder padding="sm">
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      <Text size="lg" fw={700} c={tone} mt={4}>
        {value}
      </Text>
    </Card>
  )
}