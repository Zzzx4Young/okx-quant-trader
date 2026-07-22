import { useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Divider,
  Grid,
  Group,
  Loader,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core'

type QueryResponse = {
  ok: boolean
  intent: string
  query: string
  answer: string
  extras: Record<string, unknown>
  version: string
}

const SAMPLE_QUERIES = [
  'BTC 仓位怎么样?',
  'ETH 仓位?',
  '今日 PnL?',
  '策略分布?',
  '所有持仓?',
]

export function QueryPage() {
  const [query, setQuery] = useState('')
  const [response, setResponse] = useState<QueryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (q: string) => {
    if (!q.trim()) return
    setLoading(true)
    setError(null)
    setQuery(q)
    try {
      const r = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      })
      if (!r.ok) throw new Error(`/api/query ${r.status}`)
      const json = await r.json()
      setResponse(json)
    } catch (e: unknown) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Query · 自然语言查询持仓</Title>
        <Text size="sm" c="dimmed" mt={4}>
          Phase 2a: keyword-routed stub. Phase 2b: LLM via api.minimaxi.com —
          active when <Code>OKX_WEB_LLM_API_KEY</Code> is configured.
        </Text>
      </div>

      <Card withBorder shadow="sm" padding="md">
        <Textarea
          placeholder="输入 query,例如 'BTC 仓位'"
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={4}
          onKeyDown={(e) => {
            if (
              e.key === 'Enter' &&
              (e.metaKey || e.ctrlKey) &&
              !loading
            ) {
              submit(query)
            }
          }}
        />
        <Group justify="space-between" mt="sm">
          <Text size="xs" c="dimmed">
            ⌘/Ctrl + Enter 提交
          </Text>
          <Button
            loading={loading}
            disabled={!query.trim()}
            onClick={() => submit(query)}
          >
            提交
          </Button>
        </Group>
      </Card>

      <Card withBorder shadow="sm" padding="md">
        <Text size="sm" c="dimmed" mb="xs">
          样例 queries:
        </Text>
        <Group gap="xs">
          {SAMPLE_QUERIES.map((q, i) => (
            <Button
              key={i}
              variant="default"
              size="xs"
              radius="xl"
              onClick={() => submit(q)}
              disabled={loading}
            >
              {q}
            </Button>
          ))}
        </Group>
      </Card>

      {error && (
        <Alert color="red" title="Fetch error">
          <pre style={{ margin: 0 }}>{error}</pre>
        </Alert>
      )}

      {loading && (
        <Card withBorder shadow="sm" padding="md">
          <Group>
            <Loader size="sm" />
            <Text c="dimmed">查询中…</Text>
          </Group>
        </Card>
      )}

      {response && !loading && (
        <Card withBorder shadow="sm" padding="md">
          <Group justify="space-between" mb="xs">
            <Title order={4}>Response</Title>
            <Group gap="xs">
              <Badge color="blue" variant="light">
                intent: {response.intent}
              </Badge>
              <Badge
                color={response.ok ? 'green' : 'red'}
                variant="light"
              >
                {response.ok ? 'ok' : 'failed'}
              </Badge>
              <Text size="xs" c="dimmed">
                v{response.version}
              </Text>
            </Group>
          </Group>

          <Grid>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Stack gap={4}>
                <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                  query
                </Text>
                <Code block>{response.query}</Code>
              </Stack>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 8 }}>
              <Stack gap={4}>
                <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                  answer
                </Text>
                <Text style={{ whiteSpace: 'pre-wrap' }}>
                  {response.answer}
                </Text>
              </Stack>
            </Grid.Col>
          </Grid>

          {Object.keys(response.extras).length > 0 && (
            <>
              <Divider my="md" />
              <Stack gap={4}>
                <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                  extras
                </Text>
                <pre
                  style={{
                    background: 'var(--mantine-color-dark-7)',
                    padding: 12,
                    borderRadius: 6,
                    fontSize: 12,
                    margin: 0,
                    maxHeight: 320,
                    overflow: 'auto',
                  }}
                >
                  {JSON.stringify(response.extras, null, 2)}
                </pre>
              </Stack>
            </>
          )}
        </Card>
      )}
    </Stack>
  )
}