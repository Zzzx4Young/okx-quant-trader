import { useEffect, useRef } from 'react'
import {
  createChart,
  CandlestickSeries,
  createSeriesMarkers,
  type ISeriesApi,
  type IChartApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'

// 后端 /api/backtest/.../kline-with-signals 返回的 candle/marker 格式
export type Candle = {
  time: number // UTC 秒（lightweight-charts 要求）
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

export type Marker = {
  time: number
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown'
  text: string
}

type Props = {
  candles: Candle[]
  markers: Marker[]
  height?: number
}

// 把 seconds → UTCTimestamp（lightweight-charts v5 强类型）
function toUtcTimestamp(seconds: number): UTCTimestamp {
  return seconds as UTCTimestamp
}

export function KlineChart({ candles, markers, height = 400 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  // 一次性初始化 chart + series
  useEffect(() => {
    if (!containerRef.current) return
    const chart: IChartApi = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#c9c9c9',
      },
      grid: {
        vertLines: { color: '#2a2a2a' },
        horzLines: { color: '#2a2a2a' },
      },
      width: containerRef.current.clientWidth,
      height,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: '#3a3a3a',
      },
      rightPriceScale: {
        borderColor: '#3a3a3a',
      },
      crosshair: {
        mode: 1, // Magnet
      },
    })

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderUpColor: '#26a69a',
      borderDownColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    })

    chartRef.current = chart
    seriesRef.current = series

    // resize 响应
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [height])

  // candles 变化时 → setData
  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return
    const data = candles.map((c) => ({
      time: toUtcTimestamp(c.time),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
    seriesRef.current.setData(data)
    // auto-fit 一次（mount 后第一次 setData）
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent()
    }
  }, [candles])

  // markers 变化时 → setMarkers（独立 effect）
  useEffect(() => {
    if (!seriesRef.current) return
    if (markers.length === 0) return
    const markersPrimitive = createSeriesMarkers(seriesRef.current)
    const ms = markers.map(
      (m) =>
        ({
          time: toUtcTimestamp(m.time),
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }) as SeriesMarker<Time>,
    )
    markersPrimitive.setMarkers(ms)
    return () => {
      // lightweight-charts v5 primitive 自动跟随 chart.remove()；不需显式 destroy
    }
  }, [markers])

  return <div ref={containerRef} style={{ width: '100%', height }} />
}