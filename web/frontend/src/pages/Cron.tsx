import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Card,
  Center,
  Code,
  Divider,
  Grid,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { AreaChart } from '@mantine/charts'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

type Drift = {
  threshold_seconds: number
  drift_seconds: number | null
  drift_status: 'unknown' | 'on_time' | 'early' | 'late'
  fallback_used: boolean
  boundary: string | null
  last_run_at: string | null
}

type Heartbeat = {
  last_run_at: string | null
  timeframe: string | null
  warmup_ms: number | null
  signal_triggered: boolean | null
  errors_count: number | null
}

type LastWorkflow = {
  success: boolean | null
  open_tick: boolean | null
  signal_triggered: boolean | null
  reconcile: Record<string, unknown> | null
  errors: unknown[] | null
  timestamp: string | null
}

type RecentSync = {
  at: string
  reason: string
  drift_detected: boolean
  ghost_closed_count: number
  new_synced_count: number
  actions: string[]
}

type CronData = {
  now: string
  drift: Drift
  heartbeat: Heartbeat
  last_workflow: LastWorkflow
  recent_syncs: RecentSync[]
  health_probe: {
    files: string[]
    probe_log_text: string | null
  }
  cron_jobs?: CronJob[]
  cron_source?: 'okx_live' | 'cache_fresh' | 'cache_stale' | 'unavailable'
}

type CronJob = {
  id: string
  name: string
  description?: string
  enabled: boolean
  schedule: {
    kind: 'cron' | 'every' | 'at'
    expr?: string
    tz?: string
    everyMs?: number
  }
  nextRunAtMs?: number
  lastRunAtMs?: number
  lastRunStatus?: 'ok' | 'failed' | 'timeout' | string
  state?: {
    lastDurationMs?: number
    consecutiveErrors?: number
    consecutiveSkipped?: number
    lastDeliveryStatus?: string
  }
  payload?: {
    kind: 'systemEvent' | 'agentTurn'
    message?: string
    text?: string
    timeoutSeconds?: number
    model?: string
  }
  delivery?: {
    mode?: string
    channel?: string
    to?: string
  }
  // Web-enriched fields (added by backend from `openclaw cron runs --id`):
  last_run_summary?: string | null
  last_run_at?: string | number | null
  last_run_duration_ms?: number
  last_run_model?: string
}

// H9 (2026-07-22): highlight key numbers in summary text for at-a-glance scanning.
// Pure regex tokenizer (no markdown/highlight libs). 3 categories:
//   - USDT amounts: green if positive, red if negative
//   - Percentages: yellow if >=50% (risk threshold), blue otherwise
//   - Status markers: ✓ 健康/NO_REPLY → green, ⚠️/警告/失败/[STRUCTURAL] → red/yellow
type Segment = {
  text: string
  type: 'plain' | 'pnl' | 'pct' | 'mark-ok' | 'mark-warn' | 'mark-bad'
}

const HIGHLIGHT_REGEX =
  /(\+?-?\d[\d,]*\.?\d*\s*USDT)|(\d+\.?\d*%)|(\[STRUCTURAL\]|⚠️|警告|NO_REPLY|✓ 健康|失败)/g

function tokenize(text: string): Segment[] {
  const segments: Segment[] = []
  let lastIndex = 0
  let m: RegExpExecArray | null
  HIGHLIGHT_REGEX.lastIndex = 0
  while ((m = HIGHLIGHT_REGEX.exec(text)) !== null) {
    if (m.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, m.index), type: 'plain' })
    }
    const matched = m[0]
    let type: Segment['type'] = 'mark-ok'
    if (m[1]) {
      // USDT: green if positive (or no sign), red if negative
      type = matched.trim().startsWith('-') ? 'pnl' : 'pnl'
      // Note: 'pnl' type; color decided in component by sign
    } else if (m[2]) {
      // Percentage: color depends on value (done in component)
      type = 'pct'
    } else {
      // Mark: classify by content
      if (/\bNO_REPLY\b|✓ 健康/.test(matched)) type = 'mark-ok'
      else if (/\[STRUCTURAL\]|⚠️|警告/.test(matched)) type = 'mark-warn'
      else if (/失败/.test(matched)) type = 'mark-bad'
    }
    segments.push({ text: matched, type })
    lastIndex = m.index + matched.length
  }
  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex), type: 'plain' })
  }
  return segments
}

function HighlightedText({ text }: { text: string }) {
  const segments = tokenize(text)
  return (
    <Text size="xs" ff="monospace" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
      {segments.map((seg, i) => {
        if (seg.type === 'plain') return <span key={i}>{seg.text}</span>
        let color = 'inherit'
        let fw = 600
        if (seg.type === 'pnl') {
          color = seg.text.trim().startsWith('-')
            ? 'var(--mantine-color-red-4)'
            : 'var(--mantine-color-green-4)'
        } else if (seg.type === 'pct') {
          const v = parseFloat(seg.text)
          color = v >= 50 ? 'var(--mantine-color-yellow-4)' : 'var(--mantine-color-blue-4)'
        } else if (seg.type === 'mark-ok') {
          color = 'var(--mantine-color-green-4)'
        } else if (seg.type === 'mark-warn') {
          color = 'var(--mantine-color-yellow-4)'
        } else if (seg.type === 'mark-bad') {
          color = 'var(--mantine-color-red-4)'
        }
        return (
          <span key={i} style={{ color, fontWeight: fw }}>
            {seg.text}
          </span>
        )
      })}
    </Text>
  )
}

const POLL_MS = 10_000

export function CronPage() {
  const [data, setData] = useState<CronData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<string>('-')

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      try {
        const r = await fetch('/api/cron')
        if (!r.ok) throw new Error(`/api/cron ${r.status}`)
        const json = await r.json()
        if (cancelled) return
        setData(json)
        setError(null)
        setLastFetch(
          new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        )
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

  // recent_syncs newest → oldest. Reverse for chart.
  const syncSeries = useMemo(() => {
    if (!data) return []
    const sorted = [...data.recent_syncs].sort(
      (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime(),
    )
    return sorted.map((s) => ({
      time: dayjs(s.at).format('MM-DD HH:mm'),
      ghost: s.ghost_closed_count,
      synced: s.new_synced_count,
      drift: s.drift_detected ? 1 : 0,
    }))
  }, [data])

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Cron · Signal Runner Health</Title>
          <Text size="xs" c="dimmed">
            poll every {POLL_MS / 1000}s · server now {data?.now ?? '-'}
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
          {data.cron_jobs && data.cron_jobs.length > 0 && (
            <Card withBorder shadow="sm" padding="md">
              <Group justify="space-between" mb="xs">
                <Title order={4}>
                  Scheduled Tasks{' '}
                  <Text component="span" size="sm" c="dimmed">
                    OpenClaw · {data.cron_jobs.length} jobs
                  </Text>
                </Title>
              </Group>
              <Stack gap="sm">
                {data.cron_jobs.map((job) => {
                  const lastDur =
                    (job.last_run_duration_ms ?? 0) > 0
                      ? `${Math.round(job.last_run_duration_ms! / 1000)}s`
                      : null
                  const consec = job.state?.consecutiveErrors ?? 0
                  return (
                    <Card
                      key={job.id}
                      withBorder
                      padding="md"
                      bg="var(--mantine-color-dark-7)"
                    >
                      <Group justify="space-between" align="flex-start" mb={6}>
                        <div>
                          <Group gap={6} align="center" wrap="nowrap">
                            <Text fw={600}>{job.name}</Text>
                            {job.name === 'okx-signal-runner' &&
                              data.drift.drift_status !== 'unknown' &&
                              data.drift.drift_status !== 'on_time' && (
                                <Badge
                                  size="xs"
                                  color={data.drift.drift_status === 'late' ? 'red' : 'yellow'}
                                  variant="light"
                                >
                                  drift {data.drift.drift_status}{' '}
                                  {data.drift.drift_seconds != null
                                    ? `${Math.abs(data.drift.drift_seconds)}s`
                                    : ''}
                                </Badge>
                              )}
                          </Group>
                          {job.description && (
                            <Text size="xs" c="dimmed" mt={2}>
                              {job.description}
                            </Text>
                          )}
                        </div>
                        <Group gap="xs" wrap="nowrap">
                          {consec > 0 && (
                            <Badge color="red" size="xs" variant="filled">
                              {consec} err
                            </Badge>
                          )}
                          <Badge
                            color={job.lastRunStatus === 'ok' ? 'green' : 'red'}
                            variant="light"
                            size="sm"
                          >
                            {job.lastRunStatus ?? 'unknown'}
                          </Badge>
                        </Group>
                      </Group>
                      {job.last_run_summary ? (
                        <HighlightedText text={job.last_run_summary} />
                      ) : (
                        <Text size="xs" c="dimmed" fs="italic">
                          (no run summary available)
                        </Text>
                      )}
                      <Text size="xs" c="dimmed" mt={6}>
                        last run{' '}
                        {job.last_run_at
                          ? dayjs(job.last_run_at).fromNow()
                          : '—'}
                        {lastDur && ` · ${lastDur}`}
                      </Text>
                    </Card>
                  )
                })}
              </Stack>
            </Card>
          )}

          {/* Heartbeat + last workflow side-by-side */}
          <Grid>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Card withBorder shadow="sm" padding="md">
                <Title order={4} mb="xs">
                  Latest Heartbeat
                </Title>
                <Table withTableBorder withColumnBorders>
                  <Table.Tbody>
                    <Table.Tr>
                      <Table.Td c="dimmed">last_run_at</Table.Td>
                      <Table.Td>
                        <Code>{data.heartbeat.last_run_at ?? '-'}</Code>
                      </Table.Td>
                    </Table.Tr>
                    <Table.Tr>
                      <Table.Td c="dimmed">timeframe</Table.Td>
                      <Table.Td>{data.heartbeat.timeframe ?? '-'}</Table.Td>
                    </Table.Tr>
                    <Table.Tr>
                      <Table.Td c="dimmed">warmup_ms</Table.Td>
                      <Table.Td>{data.heartbeat.warmup_ms ?? '-'}</Table.Td>
                    </Table.Tr>
                    <Table.Tr>
                      <Table.Td c="dimmed">signal_triggered</Table.Td>
                      <Table.Td>
                        <Badge
                          color={
                            data.heartbeat.signal_triggered ? 'yellow' : 'gray'
                          }
                          variant="light"
                        >
                          {String(data.heartbeat.signal_triggered ?? '-')}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                    <Table.Tr>
                      <Table.Td c="dimmed">errors_count</Table.Td>
                      <Table.Td>
                        <Badge
                          color={
                            data.heartbeat.errors_count ? 'red' : 'green'
                          }
                          variant="light"
                        >
                          {String(data.heartbeat.errors_count ?? 0)}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                  </Table.Tbody>
                </Table>
              </Card>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Card withBorder shadow="sm" padding="md">
                <Title order={4} mb="xs">
                  Last Workflow Result
                </Title>
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text c="dimmed">success</Text>
                    <Badge
                      color={
                        data.last_workflow.success == null
                          ? 'gray'
                          : data.last_workflow.success
                            ? 'green'
                            : 'red'
                      }
                      variant="light"
                    >
                      {String(data.last_workflow.success ?? '-')}
                    </Badge>
                  </Group>
                  <Group justify="space-between">
                    <Text c="dimmed">open_tick</Text>
                    <Text>{String(data.last_workflow.open_tick ?? '-')}</Text>
                  </Group>
                  <Group justify="space-between">
                    <Text c="dimmed">signal_triggered</Text>
                    <Text>
                      {String(data.last_workflow.signal_triggered ?? '-')}
                    </Text>
                  </Group>
                  <Divider my={4} />
                  <Text c="dimmed" size="sm">
                    timestamp
                  </Text>
                  <Code>{data.last_workflow.timestamp ?? '-'}</Code>
                  {data.last_workflow.errors &&
                    Array.isArray(data.last_workflow.errors) &&
                    data.last_workflow.errors.length > 0 && (
                      <Alert color="red" mt="xs" title="Errors">
                        <pre style={{ margin: 0 }}>
                          {JSON.stringify(data.last_workflow.errors, null, 2)}
                        </pre>
                      </Alert>
                    )}
                </Stack>
              </Card>
            </Grid.Col>
          </Grid>

          {/* Sync activity chart (NEW — replaces what v1 didn't have) */}
          {syncSeries.length > 0 && (
            <Card withBorder shadow="sm" padding="md">
              <Group justify="space-between" mb="xs">
                <Title order={4}>Recent Syncs · timeline</Title>
                <Text size="sm" c="dimmed">
                  {data.recent_syncs.length} events (oldest → newest)
                </Text>
              </Group>
              <AreaChart
                h={220}
                data={syncSeries}
                dataKey="time"
                series={[
                  { name: 'ghost', color: 'red.6', label: 'Ghost Closed' },
                  { name: 'synced', color: 'blue.6', label: 'New Synced' },
                ]}
                curveType="monotone"
                withDots={false}
                withLegend
                valueFormatter={(v) => String(v)}
              />
            </Card>
          )}

          {/* Recent syncs table */}
          <Card withBorder shadow="sm" padding="md">
            <Title order={4} mb="xs">
              Recent Syncs · detail
            </Title>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>at</Table.Th>
                  <Table.Th>reason</Table.Th>
                  <Table.Th>drift</Table.Th>
                  <Table.Th>ghost</Table.Th>
                  <Table.Th>synced</Table.Th>
                  <Table.Th>actions</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.recent_syncs.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={6}>
                      <Text c="dimmed">No recent syncs.</Text>
                    </Table.Td>
                  </Table.Tr>
                ) : (
                  data.recent_syncs.map((s, i) => (
                    <Table.Tr key={i}>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {s.at}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge variant="default" size="sm">
                          {s.reason}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Badge
                          color={s.drift_detected ? 'red' : 'green'}
                          variant="light"
                          size="sm"
                        >
                          {s.drift_detected ? 'YES' : 'no'}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text c={s.ghost_closed_count > 0 ? 'red' : undefined}>
                          {s.ghost_closed_count}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text c={s.new_synced_count > 0 ? 'blue' : undefined}>
                          {s.new_synced_count}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4}>
                          {s.actions.map((a, j) => (
                            <Code key={j} style={{ fontSize: 11 }}>
                              {a}
                            </Code>
                          ))}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))
                )}
              </Table.Tbody>
            </Table>
          </Card>

          {/* Health probe */}
          <Card withBorder shadow="sm" padding="md">
            <Title order={4} mb="xs">
              Health Probe
            </Title>
            <Text size="sm" c="dimmed" mb="xs">
              files checked:
            </Text>
            <Group gap={4} mb="md">
              {data.health_probe.files.map((f, i) => (
                <Code key={i} style={{ fontSize: 11 }}>
                  {f}
                </Code>
              ))}
            </Group>
            {data.health_probe.probe_log_text ? (
              <pre
                style={{
                  background: 'var(--mantine-color-dark-7)',
                  padding: 12,
                  borderRadius: 6,
                  fontSize: 12,
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  maxHeight: 240,
                  overflow: 'auto',
                }}
              >
                {data.health_probe.probe_log_text}
              </pre>
            ) : (
              <Text c="dimmed">No probe log.</Text>
            )}
          </Card>
        </>
      )}
    </Stack>
  )
}

