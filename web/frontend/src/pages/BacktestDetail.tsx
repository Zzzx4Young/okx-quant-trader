import { Fragment, useEffect, useMemo, useState } from 'react'
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
  Tabs,
  Text,
  Title,
} from '@mantine/core'
import { LineChart } from '@mantine/charts'
import dayjs from 'dayjs'
import {
  KlineChart,
  type Candle as KlineCandle,
  type Marker as KlineMarker,
} from '../components/KlineChart'
import { Heatmap } from '../components/Heatmap'

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

export function BacktestDetailPage({ runId, onBack, onAddToCompare }: Props) {
  const [meta, setMeta] = useState<RunMeta | null>(null)
  const [cells, setCells] = useState<CellSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Modal state for cell drill-down (equity)
  const [selectedCell, setSelectedCell] = useState<CellSummary | null>(null)
  const [equity, setEquity] = useState<EquityPoint[]>([])
  const [equityLoading, setEquityLoading] = useState(false)

  // Modal state for trades (Phase 2A)
  type TradeRow = {
    entry_ts: number
    exit_ts: number
    direction: string
    entry_price: number
    entry_fill_price: number
    initial_size: number
    leverage: number
    margin: number
    gross_pnl: number
    funding_fee: number
    fee: number
    slippage_cost: number
    net_pnl: number
    strategy: string
    exit_reason: string
    bars_held: number
    n_fills: number
    fills_json: string
  }
  const [selectedTradesCell, setSelectedTradesCell] = useState<CellSummary | null>(null)
  const [trades, setTrades] = useState<TradeRow[] | null>(null)
  const [tradesLoading, setTradesLoading] = useState(false)

  // Phase 2B: K-line data (candles + markers)
  const [klineData, setKlineData] = useState<{ candles: KlineCandle[]; markers: KlineMarker[] } | null>(null)
  const [klineLoading, setKlineLoading] = useState(false)

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

  // Fetch trades when trades modal opens (Phase 2A)
  useEffect(() => {
    if (!selectedTradesCell) {
      setTrades(null)
      return
    }
    let cancelled = false
    setTradesLoading(true)
    ;(async () => {
      try {
        const r = await fetch(
          `/api/backtest/runs/${runId}/cells/${selectedTradesCell.label}/trades`,
        )
        if (!r.ok) throw new Error(`trades fetch ${r.status}`)
        const json = await r.json()
        if (cancelled) return
        // Spread all columns as TradeRow[] (defensive: missing columns → undefined)
        const cols = ['entry_ts','exit_ts','direction','entry_price','entry_fill_price','initial_size','leverage','margin','gross_pnl','funding_fee','fee','slippage_cost','net_pnl','strategy','exit_reason','bars_held','n_fills','fills_json'] as const
        const n = (json.entry_ts ?? []).length
        const rows: TradeRow[] = []
        for (let i = 0; i < n; i++) {
          const row: Partial<TradeRow> = {}
          for (const c of cols) row[c as keyof TradeRow] = json[c]?.[i]
          rows.push(row as TradeRow)
        }
        setTrades(rows)
      } catch (e: unknown) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setTradesLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedTradesCell, runId])

  // Fetch K-line + signal markers when trades modal opens (Phase 2B)
  useEffect(() => {
    if (!selectedTradesCell) {
      setKlineData(null)
      return
    }
    let cancelled = false
    setKlineLoading(true)
    ;(async () => {
      try {
        const r = await fetch(
          `/api/backtest/runs/${runId}/cells/${selectedTradesCell.label}/kline-with-signals`,
        )
        if (!r.ok) throw new Error(`kline fetch ${r.status}`)
        const json = await r.json()
        if (cancelled) return
        setKlineData({
          candles: json.candles ?? [],
          markers: json.markers ?? [],
        })
      } catch (e: unknown) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setKlineLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedTradesCell, runId])

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
            <Heatmap
              meta={{
                slippage_bps_list: meta.slippage_bps_list,
                fee_bps_list: meta.fee_bps_list,
              }}
              cells={cells}
              onCellClick={(cell: CellSummary) => setSelectedCell(cell)}
            />
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
                  <Table.Th>Action</Table.Th>
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
                      <Table.Td>
                        <Button
                          size="xs"
                          variant="subtle"
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedTradesCell(c)
                          }}
                          disabled={c.trades === 0}
                        >
                          trades →
                        </Button>
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

      {/* ── Trades + K-line Modal (Phase 2A + 2B) ── */}
      <Modal
        opened={!!selectedTradesCell}
        onClose={() => setSelectedTradesCell(null)}
        title={
          selectedTradesCell && (
            <Group>
              <Text fw={700} ff="monospace">
                {selectedTradesCell.label}
              </Text>
              <Badge variant="light">
                slip={selectedTradesCell.slippage_bps}bps / fee=
                {selectedTradesCell.fee_bps.toFixed(1)}bps
              </Badge>
              <Badge color={selectedTradesCell.viable ? 'green' : 'red'} variant="light">
                {selectedTradesCell.viable ? 'viable' : 'not viable'}
              </Badge>
            </Group>
          )
        }
        size="80%"
      >
        {selectedTradesCell && (
          <Tabs defaultValue="trades">
            <Tabs.List>
              <Tabs.Tab value="trades">
                Trades{trades ? ` (${trades.length})` : ''}
              </Tabs.Tab>
              <Tabs.Tab value="kline">
                K-line + Signals{klineData ? ` (${klineData.candles.length} candles · ${klineData.markers.length} signals)` : ''}
              </Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="trades" pt="md">
              {tradesLoading && (
                <Center><Loader size="sm" /></Center>
              )}

              {!tradesLoading && trades && trades.length > 0 && (() => {
              // Summary across all trades
              const totalNet = trades.reduce((a, t) => a + (t.net_pnl ?? 0), 0)
              const totalGross = trades.reduce((a, t) => a + (t.gross_pnl ?? 0), 0)
              const totalFee = trades.reduce((a, t) => a + (t.fee ?? 0), 0)
              const totalSlip = trades.reduce((a, t) => a + (t.slippage_cost ?? 0), 0)
              const totalFunding = trades.reduce((a, t) => a + (t.funding_fee ?? 0), 0)
              const wins = trades.filter((t) => t.net_pnl > 0).length
              const winRate = (wins / trades.length) * 100
              return (
                <>
                  <SimpleGrid cols={{ base: 2, sm: 3, md: 6 }} spacing="xs">
                    <StatCard label="# Trades" value={String(trades.length)} />
                    <StatCard label="Win Rate" value={`${winRate.toFixed(1)}%`} tone={winRate >= 50 ? 'green' : 'red'} />
                    <StatCard label="Net PnL" value={`${totalNet > 0 ? '+' : ''}${totalNet.toFixed(2)}`} tone={totalNet >= 0 ? 'green' : 'red'} />
                    <StatCard label="Gross PnL" value={`${totalGross > 0 ? '+' : ''}${totalGross.toFixed(2)}`} tone={totalGross >= 0 ? 'green' : 'red'} />
                    <StatCard label="Fees + Slip" value={`${(totalFee + totalSlip).toFixed(2)}`} tone="red" />
                    <StatCard label="Funding" value={`${totalFunding.toFixed(2)}`} tone="red" />
                  </SimpleGrid>

                  <Text size="xs" c="dimmed">Click ▶ fills to expand each trade's fill lifecycle</Text>

                  <Table striped highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Entry → Exit</Table.Th>
                        <Table.Th>Dir</Table.Th>
                        <Table.Th>Size</Table.Th>
                        <Table.Th>Entry</Table.Th>
                        <Table.Th>Exit</Table.Th>
                        <Table.Th>Reason</Table.Th>
                        <Table.Th>Bars</Table.Th>
                        <Table.Th>Net PnL</Table.Th>
                        <Table.Th>Breakdown</Table.Th>
                        <Table.Th>Fills</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {trades.map((t, i) => {
                        // Compute avg exit price from fills_json (defensive parse)
                        let avgExit: number | null = null
                        try {
                          const fills = JSON.parse(t.fills_json) as Array<{type: string; price: number; size: number}>
                          const exitFills = fills.filter((f) => f.type !== 'entry')
                          if (exitFills.length > 0) {
                            const totalNom = exitFills.reduce((a, f) => a + f.price * f.size, 0)
                            const totalSz = exitFills.reduce((a, f) => a + f.size, 0)
                            avgExit = totalSz > 0 ? totalNom / totalSz : null
                          }
                        } catch {
                          avgExit = null
                        }
                        return (
                          <Fragment key={i}>
                            <Table.Tr>
                              <Table.Td>
                                <Text size="xs">
                                  {dayjs(t.entry_ts).format('MM-DD HH:mm')}
                                  {' → '}
                                  {dayjs(t.exit_ts).format('MM-DD HH:mm')}
                                </Text>
                              </Table.Td>
                              <Table.Td>
                                <Badge color={t.direction === 'long' ? 'green' : 'red'} variant="light" size="sm">
                                  {t.direction}
                                </Badge>
                              </Table.Td>
                              <Table.Td>{(t.initial_size ?? 0).toFixed(4)}</Table.Td>
                              <Table.Td>{t.entry_fill_price.toFixed(2)}</Table.Td>
                              <Table.Td>{avgExit != null ? avgExit.toFixed(2) : '-'}</Table.Td>
                              <Table.Td>
                                <Badge variant="default" size="xs">{t.exit_reason}</Badge>
                              </Table.Td>
                              <Table.Td>{t.bars_held}</Table.Td>
                              <Table.Td>
                                <Text c={tone(t.net_pnl)} fw={600}>
                                  {t.net_pnl > 0 ? '+' : ''}{t.net_pnl.toFixed(2)}
                                </Text>
                              </Table.Td>
                              <Table.Td>
                                <Text size="xs" c="dimmed">
                                  g: {(t.gross_pnl ?? 0).toFixed(1)} · f: {(t.fee ?? 0).toFixed(1)} · s: {(t.slippage_cost ?? 0).toFixed(1)} · fd: {(t.funding_fee ?? 0).toFixed(1)}
                                </Text>
                              </Table.Td>
                              <Table.Td>
                                <details>
                                  <summary style={{ cursor: 'pointer', color: 'var(--mantine-color-blue-6)', fontSize: 12 }}>
                                    {t.n_fills} fills ▾
                                  </summary>
                                  <pre style={{
                                    fontSize: 10,
                                    margin: '4px 0 0',
                                    padding: 8,
                                    backgroundColor: 'var(--mantine-color-dark-9)',
                                    borderRadius: 4,
                                    overflow: 'auto',
                                    maxHeight: 200,
                                  }}>
                                    {(() => {
                                      try { return JSON.stringify(JSON.parse(t.fills_json), null, 2) }
                                      catch { return t.fills_json }
                                    })()}
                                  </pre>
                                </details>
                              </Table.Td>
                            </Table.Tr>
                          </Fragment>
                        )
                      })}
                    </Table.Tbody>
                  </Table>
                </>
              )
            })()}

              {!tradesLoading && trades && trades.length === 0 && (
                <Text c="dimmed">No trades recorded for this cell.</Text>
              )}
            </Tabs.Panel>

            <Tabs.Panel value="kline" pt="md">
              {klineLoading && (
                <Center><Loader size="sm" /></Center>
              )}
              {!klineLoading && klineData && klineData.candles.length > 0 && (
                <Stack gap="sm">
                  <KlineChart
                    candles={klineData.candles}
                    markers={klineData.markers}
                    height={420}
                  />
                  <Group gap="lg" justify="space-between">
                    <Text size="xs" c="dimmed">
                      {klineData.candles.length} candles · {klineData.markers.length} signal markers
                      · green ▲ = long entry · red ▼ = short entry
                    </Text>
                    <Text size="xs" c="dimmed">
                      click-drag to zoom · scroll to pan
                    </Text>
                  </Group>
                </Stack>
              )}
              {!klineLoading && (!klineData || klineData.candles.length === 0) && (
                <Text c="dimmed">No K-line data available for this cell.</Text>
              )}
            </Tabs.Panel>
          </Tabs>
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