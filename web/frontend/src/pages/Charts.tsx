import { useEffect, useState } from 'react'
import {
  Alert,
  Badge,
  Card,
  Center,
  Grid,
  Group,
  Loader,
  Stack,
  Text,
  Title,
  Select,
} from '@mantine/core'
import { AreaChart, BarChart } from '@mantine/charts'

// ────── Chart endpoint response types ──────

type EquityPoint = {
  timestamp: string
  equity_usdt: number
  daily_pnl_usdt: number | null
  position_count: number
  source: string
}

type EquityCurveResponse = {
  ok: boolean
  chart: 'equity-curve'
  count: number
  series: EquityPoint[]
  meta: { source: string; first_at: string | null; last_at: string | null }
}

type HealthPoint = {
  timestamp: string
  component: string
  level: 'ok' | 'warn' | 'critical'
  level_num: number  // ok=0, warn=1, critical=2
  age_seconds: number | null
}

type HealthTimelineResponse = {
  ok: boolean
  chart: 'health-timeline'
  count: number
  series: HealthPoint[]
  meta: { component: string; level_legend: string[] }
}

type CronSuccessStat = {
  cron_name: string
  total: number
  ok: number
  warn: number
  error: number
  skipped: number
  success_rate: number
}

type CronSuccessResponse = {
  ok: boolean
  chart: 'cron-success'
  count: number
  series: CronSuccessStat[]
  meta: { overall_success_rate: number; total_runs: number; total_ok: number }
}

type ChartCatalogItem = {
  id: string
  endpoint: string
  title: string
  type: 'line' | 'area' | 'bar'
  data_source: string
  params: string[]
  default_n: number
}

type ChartCatalogResponse = {
  ok: boolean
  charts: ChartCatalogItem[]
}

// ────── Component ──────

export function ChartsPage() {
  const [equityData, setEquityData] = useState<EquityCurveResponse | null>(null)
  const [healthData, setHealthData] = useState<HealthTimelineResponse | null>(null)
  const [cronData, setCronData] = useState<CronSuccessResponse | null>(null)
  const [catalog, setCatalog] = useState<ChartCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [n, setN] = useState<string | number>(90)

  useEffect(() => {
    let cancelled = false

    async function fetchAll() {
      setLoading(true)
      setError(null)
      try {
        const [catalogRes, equityRes, healthRes, cronRes] = await Promise.all([
          fetch('/api/charts/catalog'),
          fetch(`/api/charts/equity-curve?n=${n}`),
          fetch(`/api/charts/health-timeline?n=100`),
          fetch(`/api/charts/cron-success?n=100`),
        ])
        if (cancelled) return

        if (!catalogRes.ok || !equityRes.ok || !healthRes.ok || !cronRes.ok) {
          throw new Error(
            `API error: catalog=${catalogRes.status}, equity=${equityRes.status}`
          )
        }

        const catalogJson: ChartCatalogResponse = await catalogRes.json()
        const equityJson: EquityCurveResponse = await equityRes.json()
        const healthJson: HealthTimelineResponse = await healthRes.json()
        const cronJson: CronSuccessResponse = await cronRes.json()

        setCatalog(catalogJson.charts)
        setEquityData(equityJson)
        setHealthData(healthJson)
        setCronData(cronJson)
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    fetchAll()
    return () => {
      cancelled = true
    }
  }, [n])

  if (loading && !equityData) {
    return (
      <Center h="60vh">
        <Loader />
      </Center>
    )
  }

  if (error) {
    return (
      <Stack p="md">
        <Alert color="red" title="加载失败">
          {error}
        </Alert>
      </Stack>
    )
  }

  // 转换 equity 数据为 AreaChart 格式
  const equityChartData = (equityData?.series || []).map((p) => ({
    date: p.timestamp.substring(0, 10),  // YYYY-MM-DD
    Equity: p.equity_usdt,
    PnL: p.daily_pnl_usdt ?? 0,
  }))

  // 转换 cron success 为 BarChart 格式
  const cronChartData = (cronData?.series || []).map((s) => ({
    cron_name: s.cron_name.replace('okx-', ''),
    Success: s.success_rate * 100,  // 0-100 percentage
  }))

  // health-timeline: 按 component 聚合 (取最近 N 条, 分组显示)
  const healthByComponent: Record<string, HealthPoint[]> = {}
  ;(healthData?.series || []).forEach((p) => {
    if (!healthByComponent[p.component]) healthByComponent[p.component] = []
    healthByComponent[p.component].push(p)
  })

  return (
    <Stack p="md" gap="md">
      <Group justify="space-between">
        <Title order={2}>📈 历史数据 Charts (v1.4 Phase 3)</Title>
        <Group>
          <Select
            label="Equity Curve 窗口"
            value={String(n)}
            onChange={(v) => setN(v || 90)}
            data={[
              { value: '30', label: '30 天' },
              { value: '60', label: '60 天' },
              { value: '90', label: '90 天 (默认)' },
              { value: '180', label: '180 天' },
              { value: '365', label: '1 年' },
            ]}
            w={140}
          />
        </Group>
      </Group>

      <Group gap="xs">
        <Badge color="blue" variant="light">
          {catalog.length} charts available
        </Badge>
        <Badge color="green" variant="light">
          equity: {equityData?.count ?? 0} pts
        </Badge>
        <Badge color="grape" variant="light">
          health: {healthData?.count ?? 0} pts
        </Badge>
        <Badge color="orange" variant="light">
          cron: {cronData?.count ?? 0} jobs
        </Badge>
      </Group>

      <Grid>
        {/* Chart 1: Equity Curve */}
        <Grid.Col span={12}>
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="sm">
              <Group justify="space-between">
                <Title order={3}>Portfolio Equity Curve</Title>
                <Badge color="blue">{equityData?.count ?? 0} records</Badge>
              </Group>
              {equityChartData.length > 0 ? (
                <AreaChart
                  h={300}
                  data={equityChartData}
                  dataKey="date"
                  series={[
                    { name: 'Equity', color: 'blue.6' },
                    { name: 'PnL', color: 'green.5' },
                  ]}
                  curveType="monotone"
                  withDots={false}
                  withLegend
                />
              ) : (
                <Center h={300}>
                  <Text c="dimmed">暂无 equity snapshot 数据</Text>
                </Center>
              )}
              {equityData?.meta && (
                <Text size="xs" c="dimmed">
                  Source: {equityData.meta.source} |{' '}
                  {equityData.meta.first_at} → {equityData.meta.last_at}
                </Text>
              )}
            </Stack>
          </Card>
        </Grid.Col>

        {/* Chart 2: Cron Success Rate */}
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="sm">
              <Group justify="space-between">
                <Title order={3}>Cron Success Rate</Title>
                <Badge color="orange">{cronData?.count ?? 0} jobs</Badge>
              </Group>
              {cronChartData.length > 0 ? (
                <BarChart
                  h={300}
                  data={cronChartData}
                  dataKey="cron_name"
                  series={[{ name: 'Success', color: 'green.6' }]}
                  withLegend
                  withYAxis
                  yAxisProps={{ domain: [0, 100] }}
                  unit="%"
                />
              ) : (
                <Center h={300}>
                  <Text c="dimmed">暂无 cron run 数据</Text>
                </Center>
              )}
              {cronData?.meta && (
                <Text size="xs" c="dimmed">
                  Overall: {(cronData.meta.overall_success_rate * 100).toFixed(1)}% |{' '}
                  {cronData.meta.total_ok}/{cronData.meta.total_runs} runs ok
                </Text>
              )}
            </Stack>
          </Card>
        </Grid.Col>

        {/* Chart 3: Health Summary (by component) */}
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card shadow="sm" p="lg" radius="md" withBorder>
            <Stack gap="sm">
              <Group justify="space-between">
                <Title order={3}>Health Summary</Title>
                <Badge color="grape">{healthData?.count ?? 0} records</Badge>
              </Group>
              {Object.keys(healthByComponent).length > 0 ? (
                <Stack gap="xs">
                  {Object.entries(healthByComponent).map(([component, points]) => {
                    const latest = points[points.length - 1]
                    const color =
                      latest.level === 'ok'
                        ? 'green'
                        : latest.level === 'warn'
                          ? 'yellow'
                          : 'red'
                    return (
                      <Group key={component} justify="space-between">
                        <Text size="sm">{component}</Text>
                        <Group gap="xs">
                          <Badge color={color} variant="filled">
                            {latest.level}
                          </Badge>
                          <Text size="xs" c="dimmed">
                            ({points.length} records)
                          </Text>
                        </Group>
                      </Group>
                    )
                  })}
                </Stack>
              ) : (
                <Center h={300}>
                  <Text c="dimmed">暂无 health metric 数据</Text>
                </Center>
              )}
              {healthData?.meta?.level_legend && (
                <Text size="xs" c="dimmed">
                  Levels: {healthData.meta.level_legend.join(' < ')}
                </Text>
              )}
            </Stack>
          </Card>
        </Grid.Col>
      </Grid>

      <Card shadow="xs" p="sm" radius="sm" withBorder>
        <Text size="xs" c="dimmed">
          💡 数据源: SQLite (P3#4-B) | SSE event bus 已 wired (4-A) |{' '}
          {catalog.length} chart endpoints via <code>/api/charts/*</code>
        </Text>
      </Card>
    </Stack>
  )
}
