// M2 — style config for the in-house lightweight-charts v5 canvas.
// Upgraded from the v4 shapes that were never wired to any component:
// v5 renames the series option types (*SeriesOptions → *StyleOptions)
// and adds series via chart.addSeries(CandlestickSeries, …).
// Marker / price-line colors live in candle-aggregation.ts (pure, testable).
import type {
  ChartOptions,
  DeepPartial,
  CandlestickSeriesPartialOptions,
  HistogramSeriesPartialOptions,
  LineSeriesPartialOptions,
} from 'lightweight-charts';
import { CrosshairMode, LineStyle } from 'lightweight-charts';

export const DARK_CHART_OPTIONS: DeepPartial<ChartOptions> = {
  layout: {
    background: { color: 'transparent' },
    textColor: '#9898b0',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    fontSize: 11,
  },
  grid: {
    vertLines: { color: '#1a1a2e', style: LineStyle.Dotted },
    horzLines: { color: '#1a1a2e', style: LineStyle.Dotted },
  },
  crosshair: {
    mode: CrosshairMode.Normal,
    vertLine: {
      color: '#5a5a78',
      width: 1,
      style: LineStyle.Dashed,
      labelBackgroundColor: '#2a2a3e',
    },
    horzLine: {
      color: '#5a5a78',
      width: 1,
      style: LineStyle.Dashed,
      labelBackgroundColor: '#2a2a3e',
    },
  },
  timeScale: {
    borderColor: '#2a2a3e',
    timeVisible: true,
    secondsVisible: false,
    rightOffset: 5,
    barSpacing: 8,
    minBarSpacing: 3,
  },
  rightPriceScale: {
    borderColor: '#2a2a3e',
    scaleMargins: {
      top: 0.1,
      bottom: 0.2,
    },
  },
  handleScroll: {
    mouseWheel: true,
    pressedMouseMove: true,
    horzTouchDrag: true,
    vertTouchDrag: false,
  },
  handleScale: {
    axisPressedMouseMove: true,
    mouseWheel: true,
    pinch: true,
  },
};

export const CANDLESTICK_OPTIONS: DeepPartial<CandlestickSeriesPartialOptions> = {
  upColor: '#39ff14',
  downColor: '#ff3b5c',
  borderUpColor: '#39ff14',
  borderDownColor: '#ff3b5c',
  wickUpColor: '#39ff14',
  wickDownColor: '#ff3b5c',
};

/** Overlay histogram (v5 overlay convention: priceScaleId ''). */
export const VOLUME_OPTIONS: DeepPartial<HistogramSeriesPartialOptions> = {
  color: 'rgba(0, 212, 255, 0.3)',
  priceFormat: {
    type: 'volume',
  },
  priceScaleId: '',
};

export const VOLUME_SCALE_OPTIONS = {
  scaleMargins: {
    top: 0.8,
    bottom: 0,
  },
};

export const VOLUME_UP_COLOR = 'rgba(57, 255, 20, 0.25)';
export const VOLUME_DOWN_COLOR = 'rgba(255, 59, 92, 0.25)';

export const MA20_OPTIONS: DeepPartial<LineSeriesPartialOptions> = {
  color: '#00d4ff',
  lineWidth: 1,
  priceLineVisible: false,
  lastValueVisible: false,
  crosshairMarkerVisible: false,
};

export const MA50_OPTIONS: DeepPartial<LineSeriesPartialOptions> = {
  color: '#bf5af2',
  lineWidth: 1,
  priceLineVisible: false,
  lastValueVisible: false,
  crosshairMarkerVisible: false,
};

export const BB_UPPER_OPTIONS: DeepPartial<LineSeriesPartialOptions> = {
  color: 'rgba(255, 215, 0, 0.4)',
  lineWidth: 1,
  lineStyle: LineStyle.Dashed,
  priceLineVisible: false,
  lastValueVisible: false,
  crosshairMarkerVisible: false,
};

export const BB_LOWER_OPTIONS: DeepPartial<LineSeriesPartialOptions> = {
  ...BB_UPPER_OPTIONS,
};

export function createChartOptions(
  overrides?: DeepPartial<ChartOptions>
): DeepPartial<ChartOptions> {
  return {
    ...DARK_CHART_OPTIONS,
    ...overrides,
  };
}
