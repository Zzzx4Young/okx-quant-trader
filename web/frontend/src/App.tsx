import { useEffect, useState } from 'react'
import {
  AppShell,
  Burger,
  Group,
  NavLink,
  ScrollArea,
  Text,
  Title,
  Badge,
  Stack,
  Divider,
  Anchor,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { PortfolioPage } from './pages/Portfolio'
import { CronPage } from './pages/Cron'
import { QueryPage } from './pages/Query'

type PageId = 'portfolio' | 'cron' | 'query'

const NAV_ITEMS: Array<{
  id: PageId
  label: string
  description: string
  badge?: string
}> = [
  {
    id: 'portfolio',
    label: 'Portfolio',
    description: '持仓 · 历史 · 累计 PnL',
  },
  {
    id: 'cron',
    label: 'Cron Health',
    description: 'Drift · Heartbeat · Syncs',
  },
  {
    id: 'query',
    label: 'Query (AI)',
    description: '自然语言查询 · Phase 2b',
    badge: 'stub',
  },
]

const PAGE_TITLES: Record<PageId, string> = {
  portfolio: 'Portfolio · OKX Web',
  cron: 'Cron · OKX Web',
  query: 'Query · OKX Web',
}

export default function App() {
  const [page, setPage] = useState<PageId>('portfolio')
  const [opened, { toggle }] = useDisclosure()

  useEffect(() => {
    document.title = PAGE_TITLES[page] ?? 'OKX Web'
  }, [page])

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !opened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
            />
            <Title order={4}>OKX Web Dashboard</Title>
            <Badge variant="light" color="blue" size="sm">
              v1.3.0
            </Badge>
            <Badge variant="light" color="gray" size="sm">
              bind 127.0.0.1:18787
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {new Date().toLocaleDateString('zh-CN', {
              year: 'numeric',
              month: '2-digit',
              day: '2-digit',
            })}
          </Text>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <AppShell.Section>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb="xs">
            Pages
          </Text>
        </AppShell.Section>
        <AppShell.Section grow component={ScrollArea}>
          <Stack gap={4}>
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.id}
                active={page === item.id}
                label={item.label}
                description={item.description}
                rightSection={
                  item.badge ? (
                    <Badge size="xs" color="yellow" variant="light">
                      {item.badge}
                    </Badge>
                  ) : null
                }
                onClick={() => {
                  setPage(item.id)
                  if (opened) toggle()
                }}
              />
            ))}
          </Stack>
        </AppShell.Section>
        <Divider my="sm" />
        <AppShell.Section>
          <Text size="xs" c="dimmed">
            全只读 · 后端 uvicorn 单进程 serve <br />
            <Anchor
              size="xs"
              href="https://api.minimaxi.com"
              target="_blank"
              rel="noreferrer"
            >
              Phase 2b · api.minimaxi.com
            </Anchor>
          </Text>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        {page === 'portfolio' && <PortfolioPage />}
        {page === 'cron' && <CronPage />}
        {page === 'query' && <QueryPage />}
      </AppShell.Main>
    </AppShell>
  )
}