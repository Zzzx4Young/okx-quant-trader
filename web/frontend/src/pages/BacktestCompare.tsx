import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Checkbox,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core'
import { LineChart } from '@mantine/charts'
import dayjs from 'dayjs'

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
  n_cells: number
  viable_count: number
  best_ret_pct: number | null
  best_sharpe: number | null
}

type CellSummary = {
  label: string
  slippage_bps: number
  fee_bps: number
  ret_pct: number | null
  sharpe: number | null
  maxDD_pct: number | null
  trades: number | null
  win_rate_pct: number | null
  viable: boolean | null
  has_equity: boolean
}

type RunComparison = {
  run: RunSummary
  firstCell: CellSummary | null
  equity: { time: string; equity: number }[]
  loading: boolean
  error: string | null
}

// Up to 8 distinct colors for chart series (Mantine palette).
const SERIES_COLORS = [
  'blue.6',
  'red.6',
  'green.6',
  'yellow.6',
  'violet.6',
  'cyan.6',
  'pink.6',
  'orange.6',
]

type Props = {
  runIds: string[]
  setRunIds: (ids: string[]) => void
  allRuns: RunSummary[]
  onSelect: (runId: string) => void
}

export function BacktestComparePage({
  runIds,
  setRunIds,
  allRuns,
  onSelect,
}: Props) {
  const [comps, setComps] = useState<Record<string, RunComparison>>({})

  // ── Fetch meta + cells + equity for each selected run ──
  useEffect(() => {
    let cancelled = false
    setComps((prev) => {
      const next: Record<string, RunComparison> = {}
      for (const id of runIds) {
        // Preserve existing if same id
        next[id] =
          prev[id] ??
          ({
            run: allRuns.find((r) => r.id === id) ?? {
              id,
              name: id,
              timestamp: null,
              git_commit: null,
              strategy: null,
              symbol: null,
              bar: null,
              leverage: null,
              buy_hold_ret_pct: null,
              n_cells: 0,
              viable_count: 0,
              best_ret_pct: null,
              best_sharpe: null,
            },
            firstCell: null,
            equity: [],
            loading: true,
            error: null,
          } as RunComparison)
      }
      return next
    })

    ;(async () => {
      for (const id of runIds) {
        try {
          const [metaR, cellsR] = await Promise.all([
            fetch(`/api/backtest/runs/${id}`),
            fetch(`/api/backtest/runs/${id}/cells`),
          ])
          if (!metaR.ok) throw new Error(`meta ${metaR.status}`)
          if (!cellsR.ok) throw new Error(`cells ${cellsR.status}`)
          const [metaJson, cellsJson] = await Promise.all([
            metaR.json(),
            cellsR.json(),
          ])
          if (cancelled) return
          const cells: CellSummary[] = cellsJson.cells ?? []
          // Use first cell as representative (slippage_bps_list[0] × fee_bps_list[0])
          const firstCell = cells[0] ?? null
          setComps((prev) => ({
            ...prev,
            [id]: {
              ...prev[id],
              run: prev[id]?.run ?? {
                id,
                name: metaJson.scan_name ?? id,
                timestamp: metaJson.timestamp ?? null,
                git_commit: metaJson.git_commit ?? null,
                strategy: metaJson.strategy ?? null,
                symbol: metaJson.symbol ?? null,
                bar: metaJson.bar ?? null,
                leverage: metaJson.leverage ?? null,
                buy_hold_ret_pct: metaJson.buy_hold_ret_pct ?? null,
                n_cells: cells.length,
                viable_count: cells.filter((c) => c.viable).length,
                best_ret_pct:
                  cells.length > 0
                    ? Math.max(...cells.map((c) => c.ret_pct ?? -Infinity))
                    : null,
                best_sharpe:
                  cells.length > 0
                    ? Math.max(...cells.map((c) => c.sharpe ?? -Infinity))
                    : null,
              },
              firstCell,
              loading: true,
              error: null,
            },
          }))

          // Fetch equity for first cell
          if (firstCell?.has_equity) {
            const eqR = await fetch(
              `/api/backtest/runs/${id}/cells/${firstCell.label}/equity`,
            )
            if (!eqR.ok) throw new Error(`equity ${eqR.status}`)
            const eqJson = await eqR.json()
            if (cancelled) return
            const ts: number[] = eqJson.timestamp ?? []
            const eq: number[] = eqJson.equity ?? []
            const TARGET = 500
            const step = Math.max(1, Math.floor(ts.length / TARGET))
            const chartData: { time: string; equity: number }[] = []
            for (let i = 0; i < ts.length; i += step) {
              chartData.push({
                time: dayjs(ts[i]).format('YYYY-MM-DD HH:mm'),
                equity: parseFloat(eq[i].toFixed(4)),
              })
            }
            // Always include last point
            const lastIdx = ts.length - 1
            if (chartData[chartData.length - 1].time !== dayjs(ts[lastIdx]).format('YYYY-MM-DD HH:mm')) {
              chartData.push({
                time: dayjs(ts[lastIdx]).format('YYYY-MM-DD HH:mm'),
                equity: parseFloat(eq[lastIdx].toFixed(4)),
              })
            }
            setComps((prev) => ({
              ...prev,
              [id]: { ...prev[id], equity: chartData, loading: false },
            }))
          } else {
            setComps((prev) => ({
              ...prev,
              [id]: {
                ...prev[id],
                equity: [],
                loading: false,
                error: firstCell
                  ? 'No equity data'
                  : 'No cells available',
              },
            }))
          }
        } catch (e: unknown) {
          if (!cancelled) {
            setComps((prev) => ({
              ...prev,
              [id]: { ...prev[id], loading: false, error: String(e) },
            }))
          }
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [runIds.join(','), allRuns])

  // ── Build overlay chart data (align by index — assumes same start/end) ──
  const overlayChartData = useMemo(() => {
    const series = Object.values(comps).filter((c) => c.equity.length > 0)
    if (series.length === 0) return { data: [], series: [] }
    // Use longest series as anchor
    const anchor = series.reduce((a, b) =>
      a.equity.length >= b.equity.length ? a : b,
    )
    const data = anchor.equity.map((pt, i) => {
      const row: Record<string, string | number> = {
        time: pt.time,
        [anchor.run.name || anchor.run.id]: pt.equity,
      }
      for (const s of series) {
        if (s === anchor) continue
        const v = s.equity[Math.min(i * Math.floor(s.equity.length / anchor.equity.length), s.equity.length - 1)]
        row[s.run.name || s.run.id] = v?.equity ?? 0
      }
      return row
    })
    return {
      data,
      series: series.map((s, i) => ({
        name: s.run.name || s.run.id,
        color: SERIES_COLORS[i % SERIES_COLORS.length],
        label: s.run.name || s.run.id,
      })),
    }
  }, [comps])

  const toggleRun = (id: string) => {
    if (runIds.includes(id)) {
      setRunIds(runIds.filter((x) => x !== id))
    } else {
      setRunIds([...runIds, id])
    }
  }

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Compare Backtest Runs</Title>
        <Text size="xs" c="dimmed">
          overlay equity curves of selected runs ·{' '}
          {runIds.length === 0
            ? 'select runs from the list below'
            : `${runIds.length} run${runIds.length > 1 ? 's' : ''} selected`}
        </Text>
      </div>

      {/* ── Run picker (multi-select list) ── */}
      <Card withBorder shadow="sm" padding="md">
        <Title order={4} mb="xs">
          Available runs
        </Title>
        <ScrollArea h={300}>
          <Stack gap={4}>
            {allRuns.map((r) => (
              <Group
                key={r.id}
                justify="space-between"
                p="xs"
                style={{
                  borderRadius: 4,
                  backgroundColor: runIds.includes(r.id)
                    ? 'var(--mantine-color-blue-9)'
                    : undefined,
                }}
              >
                <Checkbox
                  checked={runIds.includes(r.id)}
                  onChange={() => toggleRun(r.id)}
                  label={
                    <Group gap="xs">
                      <Text size="sm" fw={600}>
                        {r.name}
                      </Text>
                      {r.strategy && (
                        <Badge variant="light" size="xs">
                          {r.strategy}
                        </Badge>
                      )}
                      <Text size="xs" c="dimmed">
                        {r.symbol} ({r.bar})
                      </Text>
                      <Text size="xs" c="dimmed">
                        {r.timestamp ? dayjs(r.timestamp).format('MM-DD HH:mm') : ''}
                      </Text>
                      {r.git_commit && (
                        <Text size="xs" c="dimmed" ff="monospace">
                          {r.git_commit.slice(0, 7)}
                        </Text>
                      )}
                    </Group>
                  }
                />
                <Button
                  variant="subtle"
                  size="xs"
                  onClick={() => onSelect(r.id)}
                >
                  detail →
                </Button>
              </Group>
            ))}
          </Stack>
        </ScrollArea>
      </Card>

      {/* ── Overlay chart ── */}
      {runIds.length > 0 && (
        <Card withBorder shadow="sm" padding="md">
          <Group justify="space-between" mb="xs">
            <Title order={4}>Equity Overlay</Title>
            <Text size="xs" c="dimmed">
              first cell of each run (slip={comps[runIds[0]]?.firstCell?.slippage_bps}bps / fee=
              {comps[runIds[0]]?.firstCell?.fee_bps?.toFixed(1)}bps)
            </Text>
          </Group>
          {overlayChartData.data.length > 0 ? (
            <LineChart
              h={360}
              data={overlayChartData.data}
              dataKey="time"
              series={overlayChartData.series}
              curveType="monotone"
              withDots={false}
              withLegend={true}
              legendProps={{ verticalAlign: 'bottom', height: 50 }}
              valueFormatter={(v) => `$${v.toFixed(2)}`}
              yAxisProps={{ width: 70 }}
              xAxisProps={{ angle: 0, textAnchor: 'middle' }}
              tickLine="y"
              gridAxis="xy"
            />
          ) : (
            <Center>
              <Loader size="sm" />
            </Center>
          )}
        </Card>
      )}

      {/* ── Side-by-side metrics table ── */}
      {runIds.length > 0 && (
        <Card withBorder shadow="sm" padding="md">
          <Title order={4} mb="xs">
            Side-by-side metrics
          </Title>
          <ScrollArea>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Run</Table.Th>
                  <Table.Th>Strategy</Table.Th>
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
                {runIds.map((id, idx) => {
                  const c = comps[id]
                  if (!c) return null
                  const color = SERIES_COLORS[idx % SERIES_COLORS.length]
                  return (
                    <Table.Tr key={id}>
                      <Table.Td>
                        <Group gap="xs">
                          <div
                            style={{
                              width: 12,
                              height: 12,
                              borderRadius: 2,
                              backgroundColor: `var(--mantine-color-${color.replace('.', '-')})`,
                            }}
                          />
                          <Text size="sm" fw={600}>
                            {c.run.name}
                          </Text>
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        {c.run.strategy && (
                          <Badge variant="light" size="xs">
                            {c.run.strategy}
                          </Badge>
                        )}
                      </Table.Td>
                      <Table.Td ff="monospace" c="dimmed">
                        {c.firstCell?.label ?? '-'}
                      </Table.Td>
                      <Table.Td>
                        <Text
                          c={
                            c.firstCell?.ret_pct != null &&
                            c.firstCell.ret_pct > 0
                              ? 'green'
                              : 'red'
                          }
                          fw={600}
                        >
                          {c.firstCell?.ret_pct != null
                            ? `${c.firstCell.ret_pct > 0 ? '+' : ''}${c.firstCell.ret_pct.toFixed(2)}%`
                            : '-'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {c.firstCell?.sharpe?.toFixed(3) ?? '-'}
                      </Table.Td>
                      <Table.Td c="red">
                        {c.firstCell?.maxDD_pct != null
                          ? `${c.firstCell.maxDD_pct.toFixed(2)}%`
                          : '-'}
                      </Table.Td>
                      <Table.Td>{c.firstCell?.trades ?? '-'}</Table.Td>
                      <Table.Td>
                        {c.firstCell?.win_rate_pct != null
                          ? `${c.firstCell.win_rate_pct.toFixed(1)}%`
                          : '-'}
                      </Table.Td>
                      <Table.Td>
                        {c.firstCell?.viable === true && (
                          <Badge color="green" size="xs">
                            ✓
                          </Badge>
                        )}
                        {c.firstCell?.viable === false && (
                          <Badge color="red" size="xs">
                            ✗
                          </Badge>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Card>
      )}

      {runIds.some((id) => comps[id]?.error) && (
        <Alert color="yellow" title="Some runs had errors">
          {runIds
            .map((id) => comps[id]?.error)
            .filter(Boolean)
            .join('; ')}
        </Alert>
      )}

      {runIds.length === 0 && (
        <Card withBorder padding="lg">
          <Text c="dimmed">
            Select 1-8 runs above to overlay their equity curves.{' '}
            <Tooltip label="Each run uses its first cell (lowest slip × lowest fee) as the representative baseline">
              <Text component="span" c="blue">
                Why first cell?
              </Text>
            </Tooltip>
          </Text>
        </Card>
      )}
    </Stack>
  )
}