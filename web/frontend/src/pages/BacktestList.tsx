import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Card,
  Center,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
  Anchor,
} from '@mantine/core'
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
  slippage_bps_list: number[]
  fee_bps_list: number[]
  buy_hold_ret_pct: number | null
  n_cells: number
  viable_count: number
  best_ret_pct: number | null
  best_sharpe: number | null
}

type Props = {
  onSelect: (runId: string) => void
}

export function BacktestListPage({ onSelect }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      try {
        const r = await fetch('/api/backtest/runs')
        if (!r.ok) throw new Error(`/api/backtest/runs ${r.status}`)
        const json = await r.json()
        if (cancelled) return
        setRuns(json.runs ?? [])
        setError(null)
      } catch (e: unknown) {
        if (cancelled) return
        setError(String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchData()
    return () => {
      cancelled = true
    }
  }, [])

  // ── summary stats ──
  const totals = useMemo(() => {
    return {
      runs: runs.length,
      totalCells: runs.reduce((acc, r) => acc + r.n_cells, 0),
      totalViable: runs.reduce((acc, r) => acc + r.viable_count, 0),
      strategies: new Set(runs.map((r) => r.strategy).filter(Boolean)).size,
    }
  }, [runs])

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Backtest Experiments</Title>
        <Text size="xs" c="dimmed">
          fragility_scan 输出 · mtime desc · {totals.runs} runs / {totals.totalCells}{' '}
          cells total · {totals.totalViable} viable
        </Text>
      </div>

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

      {!loading && runs.length === 0 && (
        <Card withBorder padding="lg">
          <Text c="dimmed">
            No backtest experiments found. Run{' '}
            <Text component="code">okx.scripts.fragility_scan</Text> to create one.
          </Text>
        </Card>
      )}

      {!loading && runs.length > 0 && (
        <Card withBorder shadow="sm" padding="md">
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Strategy</Table.Th>
                <Table.Th>Symbol</Table.Th>
                <Table.Th>Bar</Table.Th>
                <Table.Th>Viable</Table.Th>
                <Table.Th>Best Ret</Table.Th>
                <Table.Th>Best Sharpe</Table.Th>
                <Table.Th>Time</Table.Th>
                <Table.Th>Git</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {runs.map((r) => (
                <Table.Tr
                  key={r.id}
                  style={{ cursor: 'pointer' }}
                  onClick={() => onSelect(r.id)}
                >
                  <Table.Td>
                    <Anchor size="sm" fw={600}>
                      {r.name || r.id}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>
                    {r.strategy && (
                      <Badge variant="light" size="sm">
                        {r.strategy}
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{r.symbol}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">
                      {r.bar}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      <Text size="sm" fw={600} c={r.viable_count > 0 ? 'green' : 'red'}>
                        {r.viable_count}
                      </Text>
                      <Text size="sm" c="dimmed">
                        / {r.n_cells}
                      </Text>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text
                      size="sm"
                      fw={600}
                      c={r.best_ret_pct != null && r.best_ret_pct > 0 ? 'green' : 'red'}
                    >
                      {r.best_ret_pct != null
                        ? `${r.best_ret_pct > 0 ? '+' : ''}${r.best_ret_pct.toFixed(2)}%`
                        : '-'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text
                      size="sm"
                      c={r.best_sharpe != null && r.best_sharpe > 0 ? 'green' : 'red'}
                    >
                      {r.best_sharpe != null ? r.best_sharpe.toFixed(3) : '-'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {r.timestamp ? dayjs(r.timestamp).format('MM-DD HH:mm') : '-'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {r.git_commit ? (
                      <Tooltip label={r.git_commit} withArrow>
                        <Text size="xs" c="dimmed" ff="monospace">
                          {r.git_commit.slice(0, 7)}
                        </Text>
                      </Tooltip>
                    ) : (
                      <Text size="xs" c="dimmed">
                        -
                      </Text>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </Stack>
  )
}