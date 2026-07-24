import { useEffect, useState } from 'react'
import {
  Alert,
  Anchor,
  Badge,
  Button,
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
import dayjs from 'dayjs'

type WindowSummary = {
  idx: number
  start_ts: number
  end_ts: number
  bar_count: number
  buy_hold_ret_pct: number
  viable_count: number
  total_cells: number
  best_ret_pct: number
  best_sharpe: number
  best_slip_bps: number
  best_fee_bps: number
  worst_ret_pct: number
  ret_spread_pct: number
}

type WalkforwardDetail = {
  id: string
  scan_name: string
  timestamp: string
  strategy: string
  symbol: string
  bar: string
  leverage: number
  initial_capital: number
  window_days: number
  stride_days: number
  data_start_ts: number
  data_end_ts: number
  slippage_bps_list: number[]
  fee_bps_list: number[]
  git_commit: string
  n_windows: number
  windows: WindowSummary[]
  result_md: string | null
}

type Props = {
  runId: string
  onBack: () => void
}

function tsToIso(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10)
}

export function WalkforwardDetailPage({ runId, onBack }: Props) {
  const [data, setData] = useState<WalkforwardDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      try {
        const r = await fetch(`/api/walkforward/runs/${runId}`)
        if (!r.ok) throw new Error(`/api/walkforward/runs/${runId} ${r.status}`)
        const json = await r.json()
        if (cancelled) return
        setData(json)
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
  }, [runId])

  if (error) {
    return (
      <Stack gap="md">
        <Button variant="subtle" onClick={onBack} w="fit-content">
          ← Back
        </Button>
        <Alert color="red" title="Fetch error">
          <pre style={{ margin: 0 }}>{error}</pre>
        </Alert>
      </Stack>
    )
  }

  if (loading || !data) {
    return (
      <Stack gap="md">
        <Button variant="subtle" onClick={onBack} w="fit-content">
          ← Back
        </Button>
        <Center>
          <Loader />
        </Center>
      </Stack>
    )
  }

  // 跨窗口一致性
  const viableWindows = data.windows.filter((w) => w.viable_count > 0).length
  const viablePct =
    data.n_windows === 0 ? 0 : (viableWindows / data.n_windows) * 100
  const rets = data.windows.map((w) => w.best_ret_pct)
  const bestRet = rets.length ? Math.max(...rets) : 0
  const worstRet = rets.length ? Math.min(...rets) : 0
  const meanRet = rets.length ? rets.reduce((a, b) => a + b, 0) / rets.length : 0
  const stdRet =
    rets.length > 1
      ? Math.sqrt(
          rets.reduce((acc, r) => acc + (r - meanRet) ** 2, 0) / (rets.length - 1)
        )
      : 0
  const bestWindow = data.windows.reduce(
    (a, b) => (b.best_ret_pct > a.best_ret_pct ? b : a),
    data.windows[0]
  )
  const worstWindow = data.windows.reduce(
    (a, b) => (b.best_ret_pct < a.best_ret_pct ? b : a),
    data.windows[0]
  )

  const viableColor = viablePct >= 80 ? 'green' : viablePct >= 50 ? 'yellow' : 'red'

  return (
    <Stack gap="lg">
      {/* Header */}
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Anchor size="sm" onClick={onBack} style={{ cursor: 'pointer' }}>
            ← Back to Walkforward list
          </Anchor>
          <Title order={2}>{data.scan_name}</Title>
          <Group gap="xs">
            <Badge variant="light" size="sm">
              {data.strategy}
            </Badge>
            <Badge variant="light" color="gray" size="sm">
              {data.symbol} ({data.bar})
            </Badge>
            <Badge variant="light" color="gray" size="sm">
              {data.leverage}x
            </Badge>
            <Text size="xs" c="dimmed">
              {dayjs(data.timestamp).format('YYYY-MM-DD HH:mm')}
            </Text>
            <Text size="xs" c="dimmed" ff="monospace">
              {data.git_commit.slice(0, 7)}
            </Text>
          </Group>
        </Stack>
      </Group>

      {/* 汇总卡片 */}
      <SimpleGrid cols={{ base: 2, sm: 3, md: 6 }} spacing="md">
        <Card withBorder padding="sm">
          <Text size="xs" c="dimmed">
            Windows
          </Text>
          <Text size="xl" fw={700}>
            {data.n_windows}
          </Text>
          <Text size="xs" c="dimmed">
            {data.window_days}d / {data.stride_days}d
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text size="xs" c="dimmed">
            Viable Windows
          </Text>
          <Text size="xl" fw={700} c={viableColor}>
            {viableWindows}/{data.n_windows}
          </Text>
          <Text size="xs" c="dimmed">
            {viablePct.toFixed(1)}%
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text size="xs" c="dimmed">
            Best Ret (window)
          </Text>
          <Text size="xl" fw={700} c={bestRet >= 0 ? 'green' : 'red'}>
            {bestRet >= 0 ? '+' : ''}
            {bestRet.toFixed(2)}%
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text size="xs" c="dimmed">
            Worst Ret (window)
          </Text>
          <Text size="xl" fw={700} c={worstRet >= 0 ? 'green' : 'red'}>
            {worstRet >= 0 ? '+' : ''}
            {worstRet.toFixed(2)}%
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text size="xs" c="dimmed">
            Mean ± Std
          </Text>
          <Text size="xl" fw={700}>
            {meanRet >= 0 ? '+' : ''}
            {meanRet.toFixed(2)}%
          </Text>
          <Text size="xs" c="dimmed">
            ±{stdRet.toFixed(2)}pp
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text size="xs" c="dimmed">
            Data Range
          </Text>
          <Text size="sm" fw={500}>
            {tsToIso(data.data_start_ts)}
          </Text>
          <Text size="sm" fw={500}>
            → {tsToIso(data.data_end_ts)}
          </Text>
        </Card>
      </SimpleGrid>

      {/* Best/Worst 窗口卡片 */}
      {bestWindow && worstWindow && (
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
          <Card withBorder padding="md">
            <Group justify="space-between" mb="xs">
              <Text size="sm" fw={600} c="green">
                🏆 Best Window
              </Text>
              <Badge color="green" variant="light">
                w{bestWindow.idx.toString().padStart(2, '0')}
              </Badge>
            </Group>
            <Text size="sm">
              {tsToIso(bestWindow.start_ts)} → {tsToIso(bestWindow.end_ts)} (
              {bestWindow.bar_count} bars)
            </Text>
            <Text size="xs" c="dimmed">
              best_ret = <b>{bestWindow.best_ret_pct >= 0 ? '+' : ''}{bestWindow.best_ret_pct.toFixed(2)}%</b>, buy&hold = {bestWindow.buy_hold_ret_pct >= 0 ? '+' : ''}{bestWindow.buy_hold_ret_pct.toFixed(2)}%
            </Text>
            <Text size="xs" c="dimmed">
              viable {bestWindow.viable_count}/{bestWindow.total_cells} · best cell{' '}
              {bestWindow.best_slip_bps}/{bestWindow.best_fee_bps} · sharpe{' '}
              {bestWindow.best_sharpe >= 0 ? '+' : ''}
              {bestWindow.best_sharpe.toFixed(3)}
            </Text>
          </Card>
          <Card withBorder padding="md">
            <Group justify="space-between" mb="xs">
              <Text size="sm" fw={600} c="red">
                📉 Worst Window
              </Text>
              <Badge color="red" variant="light">
                w{worstWindow.idx.toString().padStart(2, '0')}
              </Badge>
            </Group>
            <Text size="sm">
              {tsToIso(worstWindow.start_ts)} → {tsToIso(worstWindow.end_ts)} (
              {worstWindow.bar_count} bars)
            </Text>
            <Text size="xs" c="dimmed">
              best_ret = <b>{worstWindow.best_ret_pct >= 0 ? '+' : ''}{worstWindow.best_ret_pct.toFixed(2)}%</b>, buy&hold = {worstWindow.buy_hold_ret_pct >= 0 ? '+' : ''}{worstWindow.buy_hold_ret_pct.toFixed(2)}%
            </Text>
            <Text size="xs" c="dimmed">
              viable {worstWindow.viable_count}/{worstWindow.total_cells} · best cell{' '}
              {worstWindow.best_slip_bps}/{worstWindow.best_fee_bps} · sharpe{' '}
              {worstWindow.best_sharpe >= 0 ? '+' : ''}
              {worstWindow.best_sharpe.toFixed(3)}
            </Text>
          </Card>
        </SimpleGrid>
      )}

      {/* Per-window 表格 */}
      <Card withBorder shadow="sm" padding="md">
        <Title order={4} mb="sm">
          Per-Windows 详细
        </Title>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>#</Table.Th>
              <Table.Th>窗口起止</Table.Th>
              <Table.Th>bars</Table.Th>
              <Table.Th>buy&hold</Table.Th>
              <Table.Th>viable/total</Table.Th>
              <Table.Th>best_ret</Table.Th>
              <Table.Th>best_sharpe</Table.Th>
              <Table.Th>best cell</Table.Th>
              <Table.Th>spread</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.windows.map((w) => (
              <Table.Tr key={w.idx}>
                <Table.Td>
                  <Text size="sm" fw={500}>
                    w{w.idx.toString().padStart(2, '0')}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">
                    {tsToIso(w.start_ts)} → {tsToIso(w.end_ts)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{w.bar_count}</Text>
                </Table.Td>
                <Table.Td>
                  <Text
                    size="sm"
                    c={w.buy_hold_ret_pct >= 0 ? 'green' : 'red'}
                  >
                    {w.buy_hold_ret_pct >= 0 ? '+' : ''}
                    {w.buy_hold_ret_pct.toFixed(2)}%
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge
                    size="sm"
                    color={w.viable_count > 0 ? 'green' : 'red'}
                    variant="light"
                  >
                    {w.viable_count}/{w.total_cells}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text
                    size="sm"
                    fw={500}
                    c={w.best_ret_pct >= 0 ? 'green' : 'red'}
                  >
                    {w.best_ret_pct >= 0 ? '+' : ''}
                    {w.best_ret_pct.toFixed(2)}%
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{w.best_sharpe >= 0 ? '+' : ''}{w.best_sharpe.toFixed(3)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {w.best_slip_bps}/{w.best_fee_bps}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{w.ret_spread_pct.toFixed(2)}pp</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      {/* result.md（人类阅读） */}
      {data.result_md && (
        <Card withBorder padding="md">
          <Title order={4} mb="sm">
            result.md
          </Title>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontFamily: 'ui-monospace, SFMono-Regular, monospace',
              fontSize: 12,
              lineHeight: 1.5,
              maxHeight: 480,
              overflow: 'auto',
              margin: 0,
            }}
          >
            {data.result_md}
          </pre>
        </Card>
      )}
    </Stack>
  )
}
