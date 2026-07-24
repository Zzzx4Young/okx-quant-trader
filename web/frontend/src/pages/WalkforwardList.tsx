import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Card,
  Center,
  Loader,
  Stack,
  Table,
  Text,
  Title,
  Anchor,
} from '@mantine/core'
import dayjs from 'dayjs'

type WalkforwardSummary = {
  id: string
  scan_name: string | null
  timestamp: string | null
  strategy: string | null
  symbol: string | null
  bar: string | null
  leverage: number | null
  window_days: number | null
  stride_days: number | null
  n_windows: number
  viable_window_pct: number | null
  best_ret_pct: number | null
  worst_ret_pct: number | null
  git_commit: string | null
}

type Props = {
  onSelect: (runId: string) => void
}

export function WalkforwardListPage({ onSelect }: Props) {
  const [runs, setRuns] = useState<WalkforwardSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      try {
        const r = await fetch('/api/walkforward/runs')
        if (!r.ok) throw new Error(`/api/walkforward/runs ${r.status}`)
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

  const totals = useMemo(() => {
    return {
      runs: runs.length,
      totalWindows: runs.reduce((acc, r) => acc + r.n_windows, 0),
      avgViablePct:
        runs.length === 0
          ? 0
          : runs.reduce((acc, r) => acc + (r.viable_window_pct ?? 0), 0) / runs.length,
      strategies: new Set(runs.map((r) => r.strategy).filter(Boolean)).size,
    }
  }, [runs])

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Walkforward Analysis</Title>
        <Text size="xs" c="dimmed">
          滚动窗口跨 regime 稳健性扫描 · mtime desc · {totals.runs} runs /{' '}
          {totals.totalWindows} windows total · {totals.avgViablePct.toFixed(1)}% avg viable
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
            No walkforward runs found. Run{' '}
            <Text component="code">okx.scripts.walkforward</Text> to create one.
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
                <Table.Th>Window</Table.Th>
                <Table.Th>Windows</Table.Th>
                <Table.Th>Viable %</Table.Th>
                <Table.Th>Best Ret</Table.Th>
                <Table.Th>Worst Ret</Table.Th>
                <Table.Th>Time</Table.Th>
                <Table.Th>Git</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {runs.map((r) => {
                const viableColor =
                  (r.viable_window_pct ?? 0) >= 80
                    ? 'green'
                    : (r.viable_window_pct ?? 0) >= 50
                    ? 'yellow'
                    : 'red'
                return (
                  <Table.Tr
                    key={r.id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => onSelect(r.id)}
                  >
                    <Table.Td>
                      <Anchor size="sm" fw={600}>
                        {r.scan_name || r.id}
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
                      <Text size="sm">{r.symbol ?? '—'}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{r.bar ?? '—'}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">
                        {r.window_days ?? '?'}d / {r.stride_days ?? '?'}d
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {r.n_windows}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge color={viableColor} variant="light" size="sm">
                        {r.viable_window_pct?.toFixed(1) ?? '—'}%
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text
                        size="sm"
                        c={(r.best_ret_pct ?? 0) >= 0 ? 'green' : 'red'}
                        fw={500}
                      >
                        {r.best_ret_pct != null
                          ? `${r.best_ret_pct >= 0 ? '+' : ''}${r.best_ret_pct.toFixed(2)}%`
                          : '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text
                        size="sm"
                        c={(r.worst_ret_pct ?? 0) >= 0 ? 'green' : 'red'}
                      >
                        {r.worst_ret_pct != null
                          ? `${r.worst_ret_pct >= 0 ? '+' : ''}${r.worst_ret_pct.toFixed(2)}%`
                          : '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {r.timestamp
                          ? dayjs(r.timestamp).format('YYYY-MM-DD HH:mm')
                          : '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed" ff="monospace">
                        {r.git_commit ? r.git_commit.slice(0, 7) : '—'}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </Stack>
  )
}
