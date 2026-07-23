import type { CSSProperties } from 'react'
import { Stack, Table, Text, Tooltip } from '@mantine/core'

// 与 fragility_scan cell label 一致：`slip5_fee4p5`
// 字段完全对齐 BacktestDetail 的 CellSummary（heatmap 不渲染额外字段，但保证
// 调用方可直接传 CellSummary 而 tsc 不报 contravariance 错误）。
// Phase 2C 抽出后保留这个形状以维持向后兼容。
export type HeatmapCell = {
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

export type HeatmapMeta = {
  slippage_bps_list: number[]
  fee_bps_list: number[]
}

type Props = {
  meta: HeatmapMeta
  cells: HeatmapCell[]
  /** 点击 cell 回调；不传则 cell 不可交互 */
  onCellClick?: (cell: HeatmapCell) => void
  /** 是否允许点击；默认 true（如 false 则纯展示） */
  interactive?: boolean
  /** compact 模式（更小字号 + padding，用于 compare 页并排） */
  compact?: boolean
}

// 颜色阶梯：ret_pct → Mantine 颜色 CSS var
// 绿色：正收益（mag 越大越深），红色：负收益
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

// cell label 构造：`slip5_fee4p5`（与 fragility_scan._persist_cell_parquet 一致）
function cellLabel(slip: number, fee: number): string {
  return `slip${slip}_fee${fee.toFixed(1)}`.replace('.', 'p')
}

export function Heatmap({
  meta,
  cells,
  onCellClick,
  interactive = true,
  compact = false,
}: Props) {
  const cellByLabel = new Map<string, HeatmapCell>()
  for (const c of cells) cellByLabel.set(c.label, c)

  const cellPadding = compact ? '6px 10px' : '10px 14px'
  const valueSize = compact ? 'xs' : 'sm'

  return (
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
                const label = cellLabel(slip, fee)
                const cell = cellByLabel.get(label)
                const ret = cell?.ret_pct
                const bg = heatColor(ret)
                const viable = cell?.viable
                const clickable =
                  interactive && cell?.has_equity && !!onCellClick
                return (
                  <Table.Td
                    key={slip}
                    style={{
                      backgroundColor:
                        bg ?? 'var(--mantine-color-dark-9)',
                      cursor: clickable ? 'pointer' : 'default',
                      textAlign: 'center',
                      padding: cellPadding,
                      opacity: cell?.has_equity ? 1 : 0.5,
                    } as CSSProperties}
                    onClick={() => {
                      if (clickable && cell && onCellClick) {
                        onCellClick(cell)
                      }
                    }}
                  >
                    {cell ? (
                      <Tooltip
                        label={
                          <div style={{ fontSize: 11 }}>
                            <div>
                              ret:{' '}
                              {ret != null
                                ? `${ret > 0 ? '+' : ''}${ret.toFixed(3)}%`
                                : '-'}
                            </div>
                            <div>sharpe: {cell.sharpe?.toFixed(3) ?? '-'}</div>
                            <div>viable: {viable ? '✅' : '❌'}</div>
                          </div>
                        }
                        withArrow
                      >
                        <Stack gap={0} align="center">
                          <Text
                            size={valueSize}
                            fw={700}
                            c={
                              bg && bg.includes('green')
                                ? 'white'
                                : bg && bg.includes('red')
                                  ? 'white'
                                  : undefined
                            }
                          >
                            {ret != null
                              ? `${ret > 0 ? '+' : ''}${ret.toFixed(compact ? 1 : 2)}%`
                              : '-'}
                          </Text>
                          <Text
                            size="xs"
                            c={
                              bg && bg.includes('green')
                                ? 'white'
                                : bg && bg.includes('red')
                                  ? 'white'
                                  : 'dimmed'
                            }
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
  )
}