<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Map from 'ol/Map.js'
import View from 'ol/View.js'
import TileLayer from 'ol/layer/Tile.js'
import ImageLayer from 'ol/layer/Image.js'
import XYZ from 'ol/source/XYZ.js'
import TileArcGISRest from 'ol/source/TileArcGISRest.js'
import ImageWMS from 'ol/source/ImageWMS.js'
import VectorSource from 'ol/source/Vector.js'
import VectorLayer from 'ol/layer/Vector.js'
import GeoJSON from 'ol/format/GeoJSON.js'
import html2canvas from 'html2canvas'
import Draw, { createBox } from 'ol/interaction/Draw.js'
import Overlay from 'ol/Overlay.js'
import { getArea, getLength } from 'ol/sphere.js'
import Feature from 'ol/Feature.js'
import Point from 'ol/geom/Point.js'
import Style from 'ol/style/Style.js'
import CircleStyle from 'ol/style/Circle.js'
import Fill from 'ol/style/Fill.js'
import Stroke from 'ol/style/Stroke.js'
import { transform, transformExtent } from 'ol/proj.js'
import proj4 from 'proj4'
import { register } from 'ol/proj/proj4.js'
import turfBuffer from '@turf/buffer'
import type BaseLayer from 'ol/layer/Base.js'
import 'ol/ol.css'
import './map-widget.css'

const MAP_PROJECTION = 'EPSG:100007'
proj4.defs(MAP_PROJECTION, '+proj=tmerc +lat_0=39.9061111111 +lon_0=116.3911111111 +k=1 +x_0=800000 +y_0=600000 +ellps=GRS80 +units=m +no_defs')
register(proj4)

type LayerConfig = {
  id?: string
  name?: string
  type?: 'XYZ' | 'ARCGIS_REST' | 'WMS'
  url: string
  /** 底图服务自身坐标系；与地图视图 projection 不同时由 OpenLayers 重投影。 */
  sourceProjection?: string
  visible?: boolean
  opacity?: number
  params?: Record<string, string | number | boolean>
  crossOrigin?: string
  searchFields?: string[]
  /** GeoServer WFS 分页时使用的稳定排序字段；无主键的图层必须配置。 */
  sortField?: string
  searchTypeName?: string
}

type MapData = {
  center?: number[]
  zoom?: number
  minZoom?: number
  maxZoom?: number
  projection?: string
  initialExtent?: number[]
  initialExtentMaxZoom?: number
  baseLayers?: LayerConfig[]
  basemap?: { vector: LayerConfig; imagery: LayerConfig }
  basemapAnnotations?: Partial<Record<'vector' | 'imagery', LayerConfig>>
  layers?: LayerConfig[]
  points?: Array<{ coordinates: number[]; weight?: number; properties?: Record<string, any> }>
  placeSearchEnabled?: boolean
  analysisEnabled?: boolean
  amapKey?: string
  toolbar?: Partial<Record<'layer' | 'property' | 'split' | 'swipe' | 'screenshot' | 'distance' | 'area' | 'draw' | 'buffer' | 'clear', boolean>>
}

const props = withDefaults(defineProps<{ data?: MapData }>(), {
  data: () => ({
    center: [799587, 602562],
    zoom: 11,
    projection: MAP_PROJECTION,
    baseLayers: [],
    layers: [],
  }),
})

const emit = defineEmits<{
  (event: 'ready', map: Map): void
  (event: 'map-click', payload: { coordinate: number[]; pixel: number[] }): void
}>()

const mapElement = ref<HTMLElement | null>(null)
const widgetElement = ref<HTMLElement | null>(null)
let map: Map | null = null
let layers: BaseLayer[] = []
let pointLayer: VectorLayer<VectorSource> | null = null
let focusFeature: Feature<Point> | null = null
let focusAnimationTimer: ReturnType<typeof setInterval> | null = null
const placeSearchText = ref('')
const layerSearchText = ref('')
const searching = ref(false)
const searchMessage = ref('')
const searchResultsCollapsed = ref(false)
type SearchTab = { id: string; label: string; kind: 'amap' | 'layer'; results: any[] }
type PropertyResult = { layerName: string; featureId?: string; properties: Record<string, any> }
const searchTabs = ref<SearchTab[]>([])
const activeSearchTab = ref('')
const searchLoadedByTab = ref<Record<string, number>>({})
const searchPageSize = 10
const analysisOpen = ref(false)
const chartHoverIndex = ref<number | null>(null)
const completedSearchText = ref('')
type AnalysisData = {
  name: string; total: number; exact: number; expanded: number
  topicCount: number; dated: number; missingDates: number; period: string; maxCount: number
  topics: Array<{ label: string; count: number; percent: number }>
  monthly: Array<{ label: string; count: number }>
  monthlyPath: string; normalPath: string; peak: { label: string; count: number }
}
type PropertyGroup = { id: string; name: string; config: LayerConfig; bbox: string; results: PropertyResult[]; total: number | null; hasMore: boolean; loading: boolean; error: string }
const propertyGroups = ref<PropertyGroup[]>([])
const externalSearchFilter = ref('')
const propertyResults = computed(() => propertyGroups.value.flatMap(group => group.results))
const expandedPropertyGroup = ref('')
let propertyQueryVersion = 0
function closePropertyResults() {
  propertyQueryVersion++
  propertyGroups.value = []
  propertyMessage.value = ''
  propertyQuerying.value = false
}

function showPropertyResult(result: any, kind: 'amap' | 'layer') {
  const properties = kind === 'amap'
    ? { 地址: result.formatted_address || result.address || '未命名地点', 省市区: `${result.province || ''}${result.city || ''}${result.district || ''}`, 坐标: result.location || '' }
    : (result.properties ?? {})
  propertyGroups.value = [{
    id: `search-${result.id ?? result.location ?? Date.now()}`,
    name: result.layerName || (kind === 'amap' ? '地名地址' : '图层结果'),
    config: {} as LayerConfig,
    bbox: '', results: [{ layerName: result.layerName || (kind === 'amap' ? '地名地址' : '图层结果'), featureId: result.id, properties }],
    total: 1, hasMore: false, loading: false, error: '',
  }]
  expandedPropertyGroup.value = propertyGroups.value[0].id
  propertyQuerying.value = false
  propertyMessage.value = ''
  activeTool.value = 'property'
}
async function loadPropertyPage(group: PropertyGroup) {
  if (group.loading) return
  group.loading = true
  group.error = ''
  try {
    const params = new URLSearchParams({ service: 'WFS', version: '1.0.0', request: 'GetFeature',
      typeName: layerTypeName(group.config), outputFormat: 'application/json', maxFeatures: '10',
      startIndex: String(group.results.length), srsName: 'EPSG:4326', bbox: group.bbox,
      sortBy: `${group.config.sortField ?? group.config.searchFields?.[0] ?? '业务主键'} A` })
    if (group.config.sortField) params.set('sortBy', `${group.config.sortField} A`)
    const response = await fetch(`${wfsUrl(group.config)}?${params}`)
    const data = await readWfsResponse(response, group.config)
    const features = data.features ?? []
    group.results.push(...features.map((feature: any) => ({ layerName: group.name, featureId: feature.id, properties: feature.properties ?? {} })))
    group.hasMore = group.total === null ? features.length === 10 : group.results.length < group.total
  } catch (error) {
    group.error = error instanceof Error ? error.message : '加载失败，请重试'
  } finally { group.loading = false }
}
const propertyQuerying = ref(false)
const propertyMessage = ref('')
const captureMessage = ref('')
const bufferActive = ref(false)
const bufferMode = ref<'draw' | 'feature'>('feature')
const bufferDistance = ref(100)
const bufferSourceLayerId = ref('subway-lines')
const bufferTargetLayerId = ref('livelihood-info')
const bufferQuerying = ref(false)
const bufferMessage = ref('')
const bufferResults = ref<any[]>([])
const bufferPage = ref(1)
const bufferPageSize = 10
const bufferVisibleCount = ref(10)
type PlotType = 'Point' | 'LineString' | 'Polygon' | 'Circle' | 'Rectangle'
const plotActive = ref(false)
const plotType = ref<PlotType>('Point')
const activeTool = ref('')
const layerPanelOpen = ref(false)
const layerManagerOpen = ref(false)
const draggedLayerId = ref<string | null>(null)
const managedLayers = computed(() => layerRows.value.filter(layer => layer.visible !== false).slice().reverse())
const splitActive = ref(false)
const splitLeftLayerId = ref('')
const splitRightLayerId = ref('')
const swipeActive = ref(false)
const swipeLayerId = ref('')
const swipePosition = ref(50)
const layerRows = ref<LayerConfig[]>([])
const basemapMode = ref<'vector' | 'imagery'>('vector')
let basemapLayer: BaseLayer | null = null
let basemapAnnotationLayer: BaseLayer | null = null
let searchLayer: VectorLayer<VectorSource> | null = null
const measureSource = new VectorSource()
const measureLayer = new VectorLayer({ source: measureSource, zIndex: 1001 })
let drawInteraction: Draw | null = null
let measureTooltip: Overlay | null = null
let measureTooltipElement: HTMLDivElement | null = null
const plotSource = new VectorSource()
const plotLayer = new VectorLayer({ source: plotSource, zIndex: 1002 })
let plotInteraction: Draw | null = null
const bufferSource = new VectorSource()
const bufferRangeSource = new VectorSource()
const bufferResultSource = new VectorSource()
const bufferLayer = new VectorLayer({ source: bufferSource, zIndex: 1003 })
const bufferRangeLayer = new VectorLayer({ source: bufferRangeSource, zIndex: 1002 })
const bufferResultLayer = new VectorLayer({ source: bufferResultSource, zIndex: 1004 })
let bufferDrawInteraction: Draw | null = null
let activeBufferGeometry: any = null
plotLayer.setStyle((feature) => {
  const geometryType = feature.getGeometry()?.getType()
  if (geometryType === 'Point' || geometryType === 'MultiPoint') {
    return new Style({
      image: new CircleStyle({ radius: 7, fill: new Fill({ color: '#ff8a00' }), stroke: new Stroke({ color: '#fff', width: 2 }) }),
    })
  }
  return new Style({
    stroke: new Stroke({ color: '#ff8a00', width: 3 }),
    fill: new Fill({ color: 'rgb(255 138 0 / 24%)' }),
  })
})
bufferLayer.setStyle(new Style({ stroke: new Stroke({ color: '#ff8a00', width: 5 }), fill: new Fill({ color: 'rgb(255 138 0 / 18%)' }) }))
bufferRangeLayer.setStyle(new Style({ stroke: new Stroke({ color: '#ffb000', width: 2, lineDash: [8, 5] }), fill: new Fill({ color: 'rgb(255 176 0 / 20%)' }) }))
bufferResultLayer.setStyle(new Style({
  image: new CircleStyle({ radius: 7, fill: new Fill({ color: '#23d34f' }), stroke: new Stroke({ color: '#fff', width: 2 }) }),
  stroke: new Stroke({ color: '#23d34f', width: 3 }),
  fill: new Fill({ color: 'rgb(35 211 79 / 18%)' }),
}))
const splitMapElement = ref<HTMLElement | null>(null)
let splitMap: Map | null = null
let splitLayers: BaseLayer[] = []
let syncingSplitView = false
let preSplitVisibility = new globalThis.Map<string | undefined, boolean>()
const swipeMapElement = ref<HTMLElement | null>(null)
let swipeMap: Map | null = null
let swipeLayer: BaseLayer | null = null
let syncingSwipeView = false

const filteredLayers = computed(() => layerRows.value.filter((layer) =>
  !layerSearchText.value || `${layer.name ?? ''} ${layer.id ?? ''}`.toLowerCase().includes(layerSearchText.value.toLowerCase()),
))

const bufferPageCount = computed(() => Math.max(1, Math.ceil(bufferResults.value.length / bufferPageSize)))
const pagedBufferResults = computed(() => {
  return bufferResults.value.slice(0, bufferVisibleCount.value)
})

function loadMoreBufferResults() {
  bufferVisibleCount.value = Math.min(bufferResults.value.length, bufferVisibleCount.value + bufferPageSize)
}

function pagedSearchResults(tab: SearchTab) {
  return tab.results.slice(0, searchLoadedByTab.value[tab.id] ?? searchPageSize)
}

function loadMoreSearch(tabId: string) {
  const tab = searchTabs.value.find((item) => item.id === tabId)
  if (!tab) return
  searchLoadedByTab.value[tabId] = Math.min(tab.results.length, (searchLoadedByTab.value[tabId] ?? searchPageSize) + searchPageSize)
}

function analysisValue(result: any, keys: string[]) {
  for (const key of keys) {
    const value = result?.properties?.[key]
    if (value !== null && value !== undefined && String(value).trim()) return String(value).trim()
  }
  return ''
}

function buildAnalysis(tab: SearchTab): AnalysisData {
  const query = completedSearchText.value.trim().toLowerCase()
  const records = tab.results
  const exact = records.filter((result) => {
    const address = analysisValue(result, ['地址', '空间地址文本', '标准地址']).toLowerCase()
    return Boolean(query && address === query)
  }).length
  const topicCounts = new globalThis.Map<string, number>()
  records.forEach((result) => {
    const topic = analysisValue(result, ['标题', '问题标题'])
    if (!topic) return
    topicCounts.set(topic, (topicCounts.get(topic) ?? 0) + 1)
  })
  const topics = [...topicCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3)
    .map(([label, count]) => ({ label, count, percent: records.length ? Math.round(count / records.length * 100) : 0 }))
  const monthCounts = new globalThis.Map<string, number>()
  const days: string[] = []
  records.forEach((result) => {
    const raw = analysisValue(result, ['派单时间'])
    const match = raw.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
    if (match && Number(match[2]) >= 1 && Number(match[2]) <= 12 && Number(match[3]) >= 1 && Number(match[3]) <= 31) {
      const label = `${match[1]}-${match[2].padStart(2, '0')}`
      const day = `${label}-${match[3].padStart(2, '0')}`
      const parsed = new Date(`${day}T00:00:00Z`)
      if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== day) return
      days.push(day)
      monthCounts.set(label, (monthCounts.get(label) ?? 0) + 1)
    }
  })
  days.sort()
  const monthly: Array<{ label: string; count: number }> = []
  if (days.length) {
    const first = new Date(`${days[0].slice(0, 7)}-01T00:00:00Z`)
    const last = days[days.length - 1].slice(0, 7)
    while (first.toISOString().slice(0, 7) <= last) {
      const label = first.toISOString().slice(0, 7)
      monthly.push({ label, count: monthCounts.get(label) ?? 0 })
      first.setUTCMonth(first.getUTCMonth() + 1)
    }
  }
  const dated = days.length
  const mean = dated ? monthly.reduce((sum, item, index) => sum + index * item.count, 0) / dated : 0
  const variance = dated ? monthly.reduce((sum, item, index) => sum + (index - mean) ** 2 * item.count, 0) / dated : 0
  const sd = Math.sqrt(variance)
  const normalValues = sd > 0 ? monthly.map((_, index) => dated / (sd * Math.sqrt(2 * Math.PI)) * Math.exp(-0.5 * ((index - mean) / sd) ** 2)) : []
  const chartWidth = 470; const chartHeight = 180; const maxCount = Math.ceil(Math.max(1, ...monthly.map((item) => item.count), ...normalValues))
  const point = (index: number, count: number) => {
    const x = monthly.length <= 1 ? chartWidth / 2 : index / (monthly.length - 1) * chartWidth
    const y = chartHeight - count / maxCount * (chartHeight - 18)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }
  const monthlyPath = monthly.map((item, index) => point(index, item.count)).join(' ')
  const normalPath = normalValues.map((count, index) => point(index, count)).join(' ')
  const peak = monthly.reduce((best, item) => item.count > best.count ? item : best, { label: '暂无数据', count: 0 })
  return { name: completedSearchText.value || tab.label, total: records.length, exact, expanded: Math.max(0, records.length - exact), topics, topicCount: topicCounts.size, dated, missingDates: records.length - dated, period: dated ? `${days[0]} — ${days[days.length - 1]}` : '暂无有效派单时间', maxCount, monthly, monthlyPath, normalPath, peak }
}

const analysisData = computed(() => {
  const tab = searchTabs.value.find((item) => item.id === activeSearchTab.value)
  if (activeSearchTab.value === 'buffer-analysis' && bufferResults.value.length) {
    return buildAnalysis({ id: 'buffer-analysis', label: '民生民情信息', kind: 'layer', results: bufferResults.value })
  }
  return tab ? buildAnalysis(tab) : {
    name: '诉求', total: 0, exact: 0, expanded: 0, topics: [], topicCount: 0, dated: 0, missingDates: 0, period: '暂无有效派单时间', maxCount: 1, monthly: [], monthlyPath: '', normalPath: '', peak: { label: '暂无数据', count: 0 },
  }
})

function openAnalysis(tab: SearchTab) {
  activeSearchTab.value = tab.id
  analysisOpen.value = true
}

function openBufferAnalysis() {
  if (bufferTargetLayerId.value !== 'livelihood-info' || !bufferResults.value.length) return
  activeSearchTab.value = 'buffer-analysis'
  analysisOpen.value = true
}

function updateChartHover(event: MouseEvent) {
  const svg = event.currentTarget as SVGSVGElement
  const isBufferAnalysis = activeSearchTab.value === 'buffer-analysis'
  const tab = isBufferAnalysis
    ? { id: 'buffer-analysis', label: '民生民情信息', kind: 'layer' as const, results: bufferResults.value }
    : searchTabs.value.find((item) => item.id === activeSearchTab.value)
  if (!tab || !analysisData.value || !analysisData.value.monthly.length) return
  const rect = svg.getBoundingClientRect()
  const chartX = Math.max(28, Math.min(rect.width - 10, event.clientX - rect.left))
  const ratio = (chartX / rect.width - 28 / 520) / (470 / 520)
  chartHoverIndex.value = Math.max(0, Math.min(analysisData.value.monthly.length - 1, Math.round(ratio * (analysisData.value.monthly.length - 1))))
}

function clearChartHover() {
  chartHoverIndex.value = null
}

function chartPointX(index: number, count: number) {
  return 28 + (count <= 1 ? 235 : index / (count - 1) * 470)
}

function chartPointY(value: number, max: number) {
  return 190 - value / Math.max(1, max) * 162
}

const toolbarItems = computed(() => [
  { id: 'property', label: '属性', icon: 'ⓘ' },
  { id: 'split', label: '分屏', icon: '◫' },
  { id: 'swipe', label: '卷帘', icon: '▣' },
  { id: 'screenshot', label: '截图', icon: '▤' },
  { id: 'distance', label: '测距', icon: '╱' },
  { id: 'area', label: '测面', icon: '⌂' },
  { id: 'draw', label: '标绘', icon: '✎' },
  { id: 'buffer', label: '缓冲', icon: '◎' },
  { id: 'clear', label: '清除', icon: '⌫' },
].filter((tool) => props.data.toolbar?.[tool.id as keyof NonNullable<MapData['toolbar']>] !== false))

const showLayerTool = computed(() => props.data.toolbar?.layer !== false)
const showPlaceSearch = computed(() => props.data.placeSearchEnabled !== false)
// 数据分析入口由外部配置控制；未配置时默认显示，只有明确传 false 才关闭。
const analysisEnabled = computed(() => props.data.analysisEnabled !== false)

function createLayer(config: LayerConfig, projection: string) {
  const sourceProjection = config.sourceProjection ?? projection
  const source = config.type === 'WMS'
      ? new ImageWMS({
        // 本地 GeoServer 通过 Vite 同源代理加载，避免地图画布被跨域资源污染。
        url: browserRequestUrl(config.url),
        params: {
          SERVICE: 'WMS',
          REQUEST: 'GetMap',
          VERSION: '1.1.1',
          FORMAT: 'image/png',
          TRANSPARENT: true,
          SRS: projection,
          ...(config.params ?? {}),
        },
        projection,
        serverType: 'geoserver',
        // 本地 GeoServer 当前未返回 Access-Control-Allow-Origin；不设置匿名跨域，先保证地图可显示。
        // 本地 GeoServer 经 Vite 同源代理访问时不应强制 anonymous，否则无 CORS 头的图片会被浏览器拦截。
        ...(config.crossOrigin ? { crossOrigin: config.crossOrigin } : {}),
      })
    : config.type === 'ARCGIS_REST'
      ? new TileArcGISRest({
        url: browserRequestUrl(config.url),
        params: {
          F: 'image',
          FORMAT: 'PNG32',
          TRANSPARENT: true,
          ...(config.params ?? {}),
        },
        projection: sourceProjection,
        crossOrigin: config.crossOrigin ?? 'anonymous',
      })
      : new XYZ({
          url: config.url,
          projection: sourceProjection,
          // 公共底图服务若支持 CORS，匿名模式可使其参与 PNG 导出。
          crossOrigin: config.crossOrigin ?? 'anonymous',
        })

  const LayerType = config.type === 'WMS' ? ImageLayer : TileLayer
  return new LayerType({
    source: source as any,
    visible: config.visible !== false,
    opacity: config.opacity ?? 1,
    properties: { id: config.id, name: config.name },
  })
}

function getLayerConfigs(data: MapData) {
  return [...(data.baseLayers ?? []), ...(data.layers ?? [])]
}

function syncPointLayer(data: MapData) {
  if (!pointLayer) return
  const source = pointLayer.getSource()
  source.clear(true)
  const features = (data.points ?? []).filter((point) => Array.isArray(point.coordinates) && point.coordinates.length >= 2)
    .map((point) => new Feature({
      geometry: new Point(point.coordinates),
      ...(point.properties ?? {}),
      weight: point.weight ?? point.properties?.weight ?? 1,
    }))
  source.addFeatures(features)
  pointLayer.setVisible(features.length > 0)
}

function syncLayers(data: MapData) {
  if (!map) return
  // 兼容旧配置：未单独提供 layers 时，将 baseLayers 作为可管理图层使用。
  const configuredLayers = data.layers?.length ? data.layers : (data.baseLayers ?? [])
  layerRows.value = configuredLayers.map((layer, index) => ({ ...layer, id: layer.id ?? `configured-layer-${index}` }))
  const nextLayers = layerRows.value.map((config) => createLayer(config, data.projection ?? 'EPSG:4326'))
  map.getLayers().clear()
  if (data.basemap) {
    basemapLayer = createLayer(data.basemap[basemapMode.value], data.projection ?? 'EPSG:4326')
    map.addLayer(basemapLayer)
  }
  const annotationConfig = data.basemapAnnotations?.[basemapMode.value]
  basemapAnnotationLayer = annotationConfig
    ? createLayer(annotationConfig, data.projection ?? 'EPSG:4326')
    : null
  if (basemapAnnotationLayer) map.addLayer(basemapAnnotationLayer)
  nextLayers.forEach((layer) => map?.addLayer(layer))
  if (!pointLayer) {
    pointLayer = new VectorLayer({
      source: new VectorSource(),
      zIndex: 20,
      style: new Style({
        image: new CircleStyle({
          radius: 4,
          fill: new Fill({ color: 'rgba(220, 50, 55, .88)' }),
          stroke: new Stroke({ color: '#fff', width: 1.2 }),
        }),
      }),
    })
  }
  map.addLayer(pointLayer)
  syncPointLayer(data)
  layers = nextLayers
  if (map && !map.getLayers().getArray().includes(measureLayer)) map.addLayer(measureLayer)
  if (splitActive.value) rebuildSplitLayers(data)
  if (swipeActive.value) rebuildSwipeLayer()
}

function replaceBasemap(data: MapData) {
  if (!map || !data.basemap) return
  if (basemapLayer) map.removeLayer(basemapLayer)
  if (basemapAnnotationLayer) map.removeLayer(basemapAnnotationLayer)
  basemapLayer = createLayer(data.basemap[basemapMode.value], data.projection ?? 'EPSG:4326')
  map.getLayers().insertAt(0, basemapLayer)
  const annotationConfig = data.basemapAnnotations?.[basemapMode.value]
  basemapAnnotationLayer = annotationConfig
    ? createLayer(annotationConfig, data.projection ?? 'EPSG:4326')
    : null
  if (basemapAnnotationLayer) map.getLayers().insertAt(1, basemapAnnotationLayer)
  if (splitActive.value) rebuildSplitLayers(data)
}

function switchBasemap(mode: 'vector' | 'imagery') {
  if (basemapMode.value === mode) return
  basemapMode.value = mode
  // 只替换底图，保留已创建的业务图层和它们的显隐、透明度及加载状态。
  replaceBasemap(props.data)
}

function toggleLayer(config: LayerConfig) {
  config.visible = config.visible === false
  const index = layerRows.value.findIndex((layer) => layer.id === config.id)
  if (index >= 0) layerRows.value[index].visible = config.visible
  const layer = layers[index]
  layer?.setVisible(config.visible !== false)
  if (splitActive.value) preSplitVisibility.set(config.id, config.visible !== false)
  syncManagedLayerStack()
}

// 图层数组从下到上排列，管理列表反向展示。只调整业务图层，不重建地图与临时成果。
function syncManagedLayerStack() {
  if (!map) return
  layers.forEach(layer => map?.removeLayer(layer))
  let position = basemapLayer && map.getLayers().getArray().includes(basemapLayer) ? 1 : 0
  if (basemapAnnotationLayer && map.getLayers().getArray().includes(basemapAnnotationLayer)) position++
  layers.forEach((layer, index) => {
    if (layerRows.value[index]?.visible !== false) map?.getLayers().insertAt(position++, layer)
  })
}

function moveManagedLayer(sourceId: string, targetId: string) {
  const source = layerRows.value.findIndex(layer => layer.id === sourceId)
  const target = layerRows.value.findIndex(layer => layer.id === targetId)
  if (source < 0 || target < 0 || source === target) return
  const [config] = layerRows.value.splice(source, 1)
  const [layer] = layers.splice(source, 1)
  layerRows.value.splice(target, 0, config)
  layers.splice(target, 0, layer)
  syncManagedLayerStack()
}

function startLayerDrag(event: DragEvent, id: string) {
  draggedLayerId.value = id
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', id)
  }
}

function dropManagedLayer(targetId: string) {
  if (draggedLayerId.value) moveManagedLayer(draggedLayerId.value, targetId)
  draggedLayerId.value = null
}

function changeLayerOpacity(config: LayerConfig, event: Event) {
  const opacity = Math.min(1, Math.max(0, Number((event.target as HTMLInputElement).value) / 100))
  config.opacity = opacity
  layers[layerRows.value.findIndex(layer => layer.id === config.id)]?.setOpacity(opacity)
  splitLayers.find(layer => layer.get('id') === config.id)?.setOpacity(opacity)
  if (swipeLayer?.get('id') === config.id) swipeLayer.setOpacity(opacity)
}

function removeManagedLayer(config: LayerConfig) {
  if (config.visible !== false) toggleLayer(config)
  if (splitActive.value) closeSplit()
  if (swipeActive.value && swipeLayerId.value === config.id) closeSwipe()
}

function activateTool(tool: string) {
  if (tool === 'split') {
    if (swipeActive.value) closeSwipe()
    if (splitActive.value) closeSplit()
    else openSplit()
    return
  }
  if (tool === 'swipe') {
    if (swipeActive.value) closeSwipe()
    else openSwipe()
    return
  }
  if (tool === 'screenshot') {
    captureMap()
    return
  }
  if (tool === 'clear') {
    clearMeasurements()
    clearPlots()
    clearBuffer()
    activeTool.value = ''
    return
  }
  if (tool === 'buffer') {
    if (bufferActive.value) closeBuffer()
    else openBuffer()
    return
  }
  if (tool === 'draw') {
    if (plotActive.value) closePlot()
    else openPlot()
    return
  }
  if (plotActive.value) closePlot()
  if (splitActive.value) closeSplit()
  activeTool.value = activeTool.value === tool ? '' : tool
  if (activeTool.value !== 'property') {
    propertyGroups.value = []
    propertyMessage.value = ''
  }
  if (activeTool.value === 'distance' || activeTool.value === 'area') startMeasurement(activeTool.value)
  else stopMeasurement()
}

function startPlot(type: PlotType) {
  if (!map) return
  stopPlotInteraction()
  if (!map.getLayers().getArray().includes(plotLayer)) map.addLayer(plotLayer)
  plotType.value = type
  plotInteraction = new Draw({
    source: plotSource,
    type: type === 'Rectangle' ? 'Circle' : type,
    geometryFunction: type === 'Rectangle' ? createBox() : undefined,
    stopClick: true,
  })
  map.addInteraction(plotInteraction)
}

function openPlot() {
  plotActive.value = true
  activeTool.value = 'draw'
  startPlot(plotType.value)
}

function choosePlotType(type: PlotType) {
  plotActive.value = true
  activeTool.value = 'draw'
  startPlot(type)
}

function stopPlotInteraction() {
  if (plotInteraction && map) map.removeInteraction(plotInteraction)
  plotInteraction = null
}

function closePlot() {
  stopPlotInteraction()
  plotActive.value = false
  activeTool.value = ''
}

function clearPlots() {
  stopPlotInteraction()
  plotSource.clear()
}

function bufferConfig(id: string) {
  return layerRows.value.find((layer) => layer.id === id)
}

function startBufferDrawing() {
  if (!map) return
  if (bufferDrawInteraction) map.removeInteraction(bufferDrawInteraction)
  bufferDrawInteraction = new Draw({ source: bufferSource, type: 'Polygon', stopClick: true })
  map.addInteraction(bufferDrawInteraction)
  bufferDrawInteraction.on('drawend', (event) => {
    const geometry = event.feature.getGeometry()
    if (geometry) {
      activeBufferGeometry = geometry
      updateBufferRange(geometry)
      runBufferQuery(geometry)
    }
    if (bufferDrawInteraction && map) map.removeInteraction(bufferDrawInteraction)
    bufferDrawInteraction = null
  })
}

function openBuffer() {
  bufferActive.value = true
  activeTool.value = 'buffer'
  bufferMessage.value = ''
  bufferResults.value = []
  bufferPage.value = 1
  bufferVisibleCount.value = 10
  bufferVisibleCount.value = 10
  bufferSource.clear()
  bufferRangeSource.clear()
  bufferResultSource.clear()
  if (map) {
    if (!map.getLayers().getArray().includes(bufferLayer)) map.addLayer(bufferLayer)
    if (!map.getLayers().getArray().includes(bufferRangeLayer)) map.addLayer(bufferRangeLayer)
    if (!map.getLayers().getArray().includes(bufferResultLayer)) map.addLayer(bufferResultLayer)
  }
  if (!bufferConfig(bufferSourceLayerId.value)) bufferSourceLayerId.value = layerRows.value[0]?.id ?? ''
  if (!bufferConfig(bufferTargetLayerId.value)) bufferTargetLayerId.value = layerRows.value.find((layer) => layer.id !== bufferSourceLayerId.value)?.id ?? ''
  if (bufferMode.value === 'draw') startBufferDrawing()
}

function stopBufferDrawing() {
  if (bufferDrawInteraction && map) map.removeInteraction(bufferDrawInteraction)
  bufferDrawInteraction = null
}

function closeBuffer() {
  stopBufferDrawing()
  bufferActive.value = false
  bufferMessage.value = ''
  activeBufferGeometry = null
  bufferPage.value = 1
  bufferRangeSource.clear()
  activeTool.value = ''
}

function clearBuffer() {
  closeBuffer()
  bufferSource.clear()
  bufferRangeSource.clear()
  bufferResultSource.clear()
  bufferResults.value = []
  bufferPage.value = 1
  bufferVisibleCount.value = 10
}

function applyBufferMode() {
  bufferMessage.value = ''
  bufferSource.clear()
  bufferRangeSource.clear()
  bufferResultSource.clear()
  bufferResults.value = []
  bufferPage.value = 1
  activeBufferGeometry = null
  stopBufferDrawing()
  if (bufferMode.value === 'draw') startBufferDrawing()
}

function bufferFeatureGeometry(feature: any) {
  const format = new GeoJSON()
  const features = format.readFeatures({ type: 'FeatureCollection', features: [feature] } as any, {
    dataProjection: 'EPSG:4326', featureProjection: props.data.projection ?? 'EPSG:4326',
  })
  return features[0]?.getGeometry()
}

function updateBufferRange(sourceGeometry: any) {
  const projection = props.data.projection ?? 'EPSG:4326'
  const sourceFeature = new Feature({ geometry: sourceGeometry })
  const geoJson = new GeoJSON().writeFeatureObject(sourceFeature, {
    dataProjection: 'EPSG:4326',
    featureProjection: projection,
  }) as any
  const buffered = turfBuffer(geoJson, bufferDistance.value / 1000, { units: 'kilometers', steps: 32 })
  bufferRangeSource.clear()
  if (!buffered) return
  const rangeFeatures = new GeoJSON().readFeatures(buffered as any, {
    dataProjection: 'EPSG:4326',
    featureProjection: projection,
  })
  bufferRangeSource.addFeatures(rangeFeatures)
}

async function selectBufferFeature(coordinate: number[]) {
  const config = bufferConfig(bufferSourceLayerId.value)
  if (!config || !map) return
  const resolution = map.getView().getResolution() ?? 0.01
  const tolerance = resolution * 5
  const extent = [coordinate[0] - tolerance, coordinate[1] - tolerance, coordinate[0] + tolerance, coordinate[1] + tolerance]
  const bbox = props.data.projection === 'EPSG:4326' ? extent : transformExtent(extent, props.data.projection ?? 'EPSG:4326', 'EPSG:4326')
  try {
    bufferQuerying.value = true
    const features = await fetchWfsFeatures(config, bbox, 100)
    const candidates = features.map((feature: any) => {
      const geometry = bufferFeatureGeometry(feature)
      return geometry ? { feature, distance: geometryDistanceToCoordinateMeters(geometry, coordinate) } : null
    }).filter(Boolean) as Array<{ feature: any; distance: number }>
    const selected = candidates.sort((a, b) => a.distance - b.distance)[0]?.feature
    if (!selected) {
      bufferMessage.value = '点击位置未找到可缓冲要素'
      return
    }
    const geometry = bufferFeatureGeometry(selected)
    if (geometry) {
      bufferSource.clear()
      bufferSource.addFeature(new Feature({ geometry }))
      activeBufferGeometry = geometry
      updateBufferRange(geometry)
      await runBufferQuery(geometry)
    }
  } catch (error) {
    bufferMessage.value = error instanceof Error ? error.message : '源要素查询失败'
  } finally {
    bufferQuerying.value = false
  }
}

function geometryDistanceMeters(sourceGeometry: any, targetGeometry: any) {
  // 当前地图为北京2000投影坐标，单位是米；直接在当前投影中计算，
  // 不再转换到 Web Mercator，避免二次投影带来的距离偏差。
  const targetExtent = targetGeometry.getExtent()
  const targetCoordinate = [(targetExtent[0] + targetExtent[2]) / 2, (targetExtent[1] + targetExtent[3]) / 2]
  if (sourceGeometry.getType() === 'Polygon' && sourceGeometry.intersectsCoordinate(targetCoordinate)) return 0
  const closest = sourceGeometry.getClosestPoint(targetCoordinate)
  return Math.hypot(closest[0] - targetCoordinate[0], closest[1] - targetCoordinate[1])
}

function geometryDistanceToCoordinateMeters(geometry: any, coordinate: number[]) {
  if (geometry.getType() === 'Polygon' && geometry.intersectsCoordinate(coordinate)) return 0
  const closest = geometry.getClosestPoint(coordinate)
  return Math.hypot(closest[0] - coordinate[0], closest[1] - coordinate[1])
}

async function runBufferQuery(sourceGeometry: any) {
  const target = bufferConfig(bufferTargetLayerId.value)
  if (!target || !map) return
  bufferQuerying.value = true
  bufferMessage.value = ''
  bufferResultSource.clear()
  try {
    updateBufferRange(sourceGeometry)
    const projection = props.data.projection ?? 'EPSG:4326'
    const sourceExtent = sourceGeometry.getExtent()
    const extent4326 = projection === 'EPSG:4326' ? sourceExtent : transformExtent(sourceExtent, projection, 'EPSG:4326')
    const lat = (extent4326[1] + extent4326[3]) / 2
    const degreeLat = bufferDistance.value / 111320
    const degreeLon = bufferDistance.value / (111320 * Math.max(0.2, Math.cos(lat * Math.PI / 180)))
    const bbox: [number, number, number, number] = [extent4326[0] - degreeLon, extent4326[1] - degreeLat, extent4326[2] + degreeLon, extent4326[3] + degreeLat]
    const rawFeatures = await fetchWfsFeatures(target, bbox, 5000)
    const sourceForDistance = sourceGeometry
    const matched = rawFeatures.filter((feature) => {
      const geometry = bufferFeatureGeometry(feature)
      return geometry && geometryDistanceMeters(sourceForDistance, geometry) <= bufferDistance.value
    })
    const olFeatures = new GeoJSON().readFeatures({ type: 'FeatureCollection', features: matched } as any, {
      dataProjection: 'EPSG:4326', featureProjection: projection,
    })
    bufferResultSource.addFeatures(olFeatures)
    bufferResults.value = matched.map((feature: any) => ({
      id: feature.id, label: featureLabel(feature, target.name ?? '查询结果'), properties: feature.properties ?? {},
    }))
    bufferPage.value = 1
    bufferVisibleCount.value = 10
    if (!bufferResults.value.length) bufferMessage.value = '缓冲范围内未找到匹配要素'
  } catch (error) {
    bufferMessage.value = error instanceof Error ? error.message : '缓冲查询失败'
  } finally {
    bufferQuerying.value = false
  }
}

async function fetchWfsFeatures(config: LayerConfig, bbox?: number[], maxFeatures = 100) {
  const typeName = layerTypeName(config)
  if (!typeName) return []
  const params = new URLSearchParams({ service: 'WFS', version: '1.0.0', request: 'GetFeature', typeName,
    outputFormat: 'application/json', maxFeatures: String(maxFeatures), srsName: 'EPSG:4326',
    sortBy: `${config.sortField ?? config.searchFields?.[0] ?? '业务主键'} A` })
  if (bbox) params.set('bbox', `${bbox.join(',')},EPSG:4326`)
  const response = await fetch(`${wfsUrl(config)}?${params}`)
  const data = await readWfsResponse(response, config)
  return data.features ?? []
}

watch([bufferDistance, bufferTargetLayerId], () => {
  if (bufferActive.value && activeBufferGeometry) {
    updateBufferRange(activeBufferGeometry)
    runBufferQuery(activeBufferGeometry)
  }
})

function formatLength(length: number) {
  return length >= 1000 ? `${(length / 1000).toFixed(2)} 千米` : `${length.toFixed(2)} 米`
}

function formatArea(area: number) {
  return area >= 1_000_000 ? `${(area / 1_000_000).toFixed(2)} 平方千米` : `${area.toFixed(2)} 平方米`
}

function createMeasureTooltip() {
  measureTooltipElement = document.createElement('div')
  measureTooltipElement.className = 'measure-tooltip'
  measureTooltip = new Overlay({
    element: measureTooltipElement,
    offset: [0, -12],
    positioning: 'bottom-center',
    stopEvent: false,
  })
  map?.addOverlay(measureTooltip)
}

function startMeasurement(type: 'distance' | 'area') {
  if (!map) return
  stopMeasurement()
  if (!map.getLayers().getArray().includes(measureLayer)) map.addLayer(measureLayer)
  createMeasureTooltip()
  drawInteraction = new Draw({
    source: measureSource,
    type: type === 'distance' ? 'LineString' : 'Polygon',
    stopClick: true,
  })
  map.addInteraction(drawInteraction)
  drawInteraction.on('drawstart', (event) => {
    measureTooltipElement?.classList.remove('measure-tooltip-static')
    const geometry = event.feature.getGeometry()
    geometry?.on('change', () => {
      if (!geometry || !measureTooltip || !measureTooltipElement) return
      const projection = map?.getView().getProjection()
      const value = type === 'distance'
        ? formatLength(getLength(geometry as any, { projection }))
        : formatArea(getArea(geometry as any, { projection }))
      measureTooltipElement.textContent = value
      const coordinate = type === 'distance'
        ? (geometry as any).getLastCoordinate()
        : (geometry as any).getInteriorPoint().getCoordinates()
      measureTooltip.setPosition(coordinate)
    })
  })
  drawInteraction.on('drawend', () => {
    measureTooltipElement?.classList.add('measure-tooltip-static')
    measureTooltip = null
    measureTooltipElement = null
    // 保持工具激活，允许继续绘制下一条线或下一个面。
    window.setTimeout(() => { if (activeTool.value === type) startMeasurement(type) }, 0)
  })
}

function stopMeasurement() {
  if (drawInteraction && map) map.removeInteraction(drawInteraction)
  drawInteraction = null
  if (measureTooltip) map?.removeOverlay(measureTooltip)
  measureTooltip = null
  measureTooltipElement = null
}

function clearMeasurements() {
  stopMeasurement()
  measureSource.clear()
  map?.getOverlays().getArray().slice().forEach((overlay) => {
    const element = overlay.getElement()
    if (element?.classList.contains('measure-tooltip')) map?.removeOverlay(overlay)
  })
}

function captureMap() {
  if (!map || !widgetElement.value) return
  captureMessage.value = '正在生成截图…'
  map.once('rendercomplete', () => {
    html2canvas(widgetElement.value as HTMLElement, {
      useCORS: true,
      allowTaint: false,
      backgroundColor: null,
      scale: window.devicePixelRatio || 1,
      onclone: (clonedDocument) => clonedDocument.querySelector('.capture-message')?.remove(),
    }).then((output) => {
      output.toBlob((blob) => {
        if (!blob) {
          captureMessage.value = '截图生成失败'
          return
        }
        const link = document.createElement('a')
        link.href = URL.createObjectURL(blob)
        link.download = `map-screenshot-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`
        link.click()
        URL.revokeObjectURL(link.href)
        captureMessage.value = '截图已下载'
        window.setTimeout(() => { captureMessage.value = '' }, 2200)
      }, 'image/png')
    }).catch((error: unknown) => {
      captureMessage.value = error instanceof Error ? `截图失败：${error.message}` : '截图失败'
    })
  })
  map.renderSync()
}

function rebuildSwipeLayer() {
  if (!swipeMap) return
  swipeMap.getLayers().clear()
  swipeLayer = null
  const config = layerRows.value.find((layer) => layer.id === swipeLayerId.value)
  if (!config) return
  swipeLayer = createLayer({ ...config, visible: true }, props.data.projection ?? 'EPSG:4326')
  swipeMap.addLayer(swipeLayer)
}

function openSwipe() {
  swipeActive.value = true
  activeTool.value = 'swipe'
  const candidates = layerRows.value.filter((layer) => layer.type === 'WMS')
  swipeLayerId.value = candidates[1]?.id ?? candidates[0]?.id ?? ''
  swipePosition.value = 50
  nextTick(() => {
    if (!swipeMapElement.value || !map) return
    const view = map.getView()
    swipeMap = new Map({
      target: swipeMapElement.value,
      controls: [],
      view: new View({
        center: view.getCenter(),
        zoom: view.getZoom(),
        projection: props.data.projection ?? 'EPSG:4326',
      }),
    })
    rebuildSwipeLayer()
    map.on('moveend', syncPrimaryToSwipe)
    swipeMap.on('moveend', syncSwipeToPrimary)
  })
}

function applySwipeSelection() {
  if (swipeActive.value) rebuildSwipeLayer()
}

function updateSwipePosition(event: PointerEvent) {
  const rect = mapElement.value?.getBoundingClientRect()
  if (!rect) return
  swipePosition.value = Math.min(90, Math.max(10, ((event.clientX - rect.left) / rect.width) * 100))
}

function startSwipeDrag(event: PointerEvent) {
  event.preventDefault()
  window.addEventListener('pointermove', updateSwipePosition)
  window.addEventListener('pointerup', stopSwipeDrag, { once: true })
}

function stopSwipeDrag() {
  window.removeEventListener('pointermove', updateSwipePosition)
}

function syncPrimaryToSwipe() {
  if (!swipeMap || syncingSwipeView || !map) return
  syncingSwipeView = true
  swipeMap.getView().setCenter(map.getView().getCenter())
  swipeMap.getView().setZoom(map.getView().getZoom())
  syncingSwipeView = false
}

function syncSwipeToPrimary() {
  if (!swipeMap || syncingSwipeView || !map) return
  syncingSwipeView = true
  map.getView().setCenter(swipeMap.getView().getCenter())
  map.getView().setZoom(swipeMap.getView().getZoom())
  syncingSwipeView = false
}

function closeSwipe() {
  if (map) map.un('moveend', syncPrimaryToSwipe)
  swipeMap?.un('moveend', syncSwipeToPrimary)
  swipeMap?.setTarget(undefined)
  swipeMap = null
  swipeLayer = null
  swipeActive.value = false
  activeTool.value = ''
}

function visibleSplitLayerIds() {
  return new Set([splitRightLayerId.value].filter(Boolean))
}

function rebuildSplitLayers(data: MapData = props.data) {
  if (!splitMap) return
  splitMap.getLayers().clear()
  splitLayers = []
  if (data.basemap) {
    splitLayers.push(createLayer(data.basemap[basemapMode.value], data.projection ?? 'EPSG:4326'))
    splitMap.addLayer(splitLayers[0])
  }
  const annotationConfig = data.basemapAnnotations?.[basemapMode.value]
  if (annotationConfig) {
    const annotationLayer = createLayer(annotationConfig, data.projection ?? 'EPSG:4326')
    splitLayers.push(annotationLayer)
    splitMap.addLayer(annotationLayer)
  }
  const selected = visibleSplitLayerIds()
  layerRows.value.forEach((config) => {
    if (selected.has(config.id)) {
      const layer = createLayer({ ...config, visible: true }, data.projection ?? 'EPSG:4326')
      splitLayers.push(layer)
      splitMap?.addLayer(layer)
    }
  })
}

function applySplitSelection() {
  if (!splitActive.value) return
  layerRows.value.forEach((config, index) => layers[index]?.setVisible(config.id === splitLeftLayerId.value))
  rebuildSplitLayers()
}

function openSplit() {
  splitActive.value = true
  activeTool.value = 'split'
  const candidates = layerRows.value.filter((layer) => layer.type === 'WMS')
  splitLeftLayerId.value = candidates[0]?.id ?? ''
  splitRightLayerId.value = candidates[1]?.id ?? candidates[0]?.id ?? ''
  preSplitVisibility = new globalThis.Map(layerRows.value.map((layer) => [layer.id, layer.visible !== false]))
  nextTick(() => {
    if (!splitMapElement.value || !map) return
    const view = map.getView()
    splitMap = new Map({
      target: splitMapElement.value,
      controls: [],
      view: new View({
        center: view.getCenter(),
        zoom: view.getZoom(),
        projection: props.data.projection ?? 'EPSG:4326',
      }),
    })
    rebuildSplitLayers()
    map.on('moveend', syncPrimaryToSplit)
    splitMap.on('moveend', syncSplitToPrimary)
    applySplitSelection()
  })
}

function syncPrimaryToSplit() {
  if (!splitMap || syncingSplitView || !map) return
  syncingSplitView = true
  splitMap.getView().setCenter(map.getView().getCenter())
  splitMap.getView().setZoom(map.getView().getZoom())
  syncingSplitView = false
}

function syncSplitToPrimary() {
  if (!splitMap || syncingSplitView || !map) return
  syncingSplitView = true
  map.getView().setCenter(splitMap.getView().getCenter())
  map.getView().setZoom(splitMap.getView().getZoom())
  syncingSplitView = false
}

function closeSplit() {
  layerRows.value.forEach((config, index) => {
    const restored = preSplitVisibility.get(config.id)
    if (restored !== undefined) {
      config.visible = restored
      layers[index]?.setVisible(restored)
    }
  })
  if (map) map.un('moveend', syncPrimaryToSplit)
  splitMap?.un('moveend', syncSplitToPrimary)
  splitMap?.setTarget(undefined)
  splitMap = null
  splitLayers = []
  splitActive.value = false
  activeTool.value = ''
}

async function queryProperties(coordinate: number[]) {
  if (!map) return
  const version = ++propertyQueryVersion
  propertyQuerying.value = true
  propertyMessage.value = ''
  propertyGroups.value = []
  expandedPropertyGroup.value = ''
  const view = map.getView()
  const resolution = view.getResolution()
  if (!resolution) { propertyQuerying.value = false; return }
  const tolerance = resolution * 5
  const extent = [coordinate[0] - tolerance, coordinate[1] - tolerance, coordinate[0] + tolerance, coordinate[1] + tolerance]
  const bbox = `${transformExtent(extent, view.getProjection(), 'EPSG:4326').join(',')},EPSG:4326`
  const groups = await Promise.all(layerRows.value.filter(config => config.type === 'WMS' && config.visible !== false && layerTypeName(config)).map(async (config, index) => {
    const group: PropertyGroup = { id: config.id ?? `${index}`, name: config.name ?? config.id ?? '未命名图层', config, bbox,
      results: [], total: null, hasMore: true, loading: false, error: '' }
    // hits 只查询数量；属性数据按 10 条分批获取，避免预先下载全部记录。
    try {
      const params = new URLSearchParams({ service: 'WFS', version: '1.1.0', request: 'GetFeature',
        typeName: layerTypeName(config), resultType: 'hits', srsName: 'EPSG:4326', bbox,
        sortBy: `${config.sortField ?? config.searchFields?.[0] ?? '业务主键'} A` })
      const response = await fetch(`${wfsUrl(config)}?${params}`)
      if (!response.ok) throw new Error('数量查询失败')
      const body = await response.text()
      const xml = new DOMParser().parseFromString(body, 'text/xml')
      const raw = xml.documentElement.getAttribute('numberOfFeatures') ?? xml.documentElement.getAttribute('numberMatched')
      if (raw !== null && /^\d+$/.test(raw)) group.total = Number(raw)
    } catch { /* 数量不可用时仍允许逐批查询，不将已加载条数冒充总数。 */ }
    if (group.total !== 0) await loadPropertyPage(group)
    return group
  }))
  if (version !== propertyQueryVersion) return
  propertyGroups.value = groups.filter(group => group.results.length || group.error || (group.total ?? 0) > 0)
  if (!propertyGroups.value.length) propertyMessage.value = '点击位置未查询到图层要素'
  propertyQuerying.value = false
}

function ensureSearchLayer() {
  if (!map) return null
  if (!searchLayer) {
    searchLayer = new VectorLayer({ source: new VectorSource(), zIndex: 1000 })
    map.addLayer(searchLayer)
  }
  return searchLayer
}

function layerTypeName(config: LayerConfig) {
  return config.searchTypeName ?? String(config.params?.LAYERS ?? '')
}

function wfsUrl(config: LayerConfig) {
  const configured = new URL(config.url, window.location.origin)
  if (configured.hostname === '127.0.0.1' && configured.port === '8080') {
    const path = configured.pathname.replace(/\/wms\/?$/, '/ows')
    return `/geoserver${path.split('/geoserver').pop() ?? '/bjchy/ows'}`
  }
  // DataV 部署后 GeoServer 通常是跨域服务，必须保留 origin，不能只返回相对路径。
  return `${configured.origin}${configured.pathname.replace(/\/wms\/?$/, '/ows')}${configured.search}`
}

async function readWfsResponse(response: Response, config: LayerConfig) {
  const body = await response.text()
  if (!response.ok) {
    const message = body.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
    throw new Error(`${config.name ?? config.id ?? 'WFS'} 查询失败（${response.status}）：${message.slice(0, 180)}`)
  }
  try {
    return JSON.parse(body)
  } catch {
    const message = body.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
    throw new Error(`${config.name ?? config.id ?? 'WFS'} 返回的不是 JSON：${message.slice(0, 180)}`)
  }
}

function browserRequestUrl(rawUrl: string) {
  const configured = new URL(rawUrl, window.location.origin)
  if (configured.hostname === '127.0.0.1' && configured.port === '8080') {
    const path = configured.pathname.split('/geoserver').pop() ?? configured.pathname
    return `/geoserver${path}${configured.search}`
  }
  return rawUrl
}

function escapeCqlText(text: string) {
  return text.replace(/'/g, "''")
}

function featureLabel(feature: any, fallback: string) {
  const properties = feature.properties ?? {}
  const preferred = ['名称', '标准名称', '站点名称', '站点标准名称', 'line_name', 'osm_name', '标题', '地址', '主要内容']
  const key = preferred.find((field) => properties[field] !== null && properties[field] !== undefined && properties[field] !== '')
  return key ? String(properties[key]) : fallback
}

async function searchLayerData(config: LayerConfig, text: string, extraFilter = '') {
  if (config.type !== 'WMS' || !config.searchFields?.length || !layerTypeName(config)) return []
  const textCql = config.searchFields
    .map((field) => `"${field.replace(/"/g, '')}" LIKE '%${escapeCqlText(text)}%'`)
    .join(' OR ')
  const cql = extraFilter ? `(${textCql}) AND (${extraFilter})` : textCql
  const pageSize = 100
  const allFeatures: any[] = []
  let startIndex = 0
  while (true) {
    const params = new URLSearchParams({
      service: 'WFS', version: '1.0.0', request: 'GetFeature',
      typeName: layerTypeName(config), outputFormat: 'application/json',
      maxFeatures: String(pageSize), startIndex: String(startIndex), cql_filter: cql,
      // GeoServer 对没有主键的图层分页时要求显式 sortBy，否则会返回
      // "Cannot do natural order without a primary key"。
      sortBy: `${config.sortField ?? config.searchFields[0]} A`,
    })
    const response = await fetch(`${wfsUrl(config)}?${params}`)
    const data = await readWfsResponse(response, config)
    const pageFeatures = data.features ?? []
    allFeatures.push(...pageFeatures)
    if (pageFeatures.length < pageSize) break
    startIndex += pageSize
  }
  return allFeatures.map((feature: any) => ({
    ...feature,
    layerId: config.id,
    layerName: config.name ?? config.id,
    label: featureLabel(feature, config.name ?? '图层要素'),
  }))
}

function drawLayerResults(features: any[]) {
  const resultLayer = ensureSearchLayer()
  const source = resultLayer?.getSource()
  if (!source) return
  source.clear()
  if (!features.length) return
  const format = new GeoJSON()
  const featureCollection = { type: 'FeatureCollection', features }
  const olFeatures = format.readFeatures(featureCollection as any, {
    dataProjection: 'EPSG:4326',
    featureProjection: props.data.projection ?? 'EPSG:4326',
  })
  olFeatures.forEach((feature, index) => feature.set('searchFeatureId', features[index].id ?? `${features[index].layerId}-${index}`))
  source.addFeatures(olFeatures)
  resultLayer.setStyle((feature) => {
    const geometryType = feature.getGeometry()?.getType()
    if (geometryType === 'Point' || geometryType === 'MultiPoint') {
      return new Style({
        image: new CircleStyle({ radius: 7, fill: new Fill({ color: '#23d34f' }), stroke: new Stroke({ color: '#fff', width: 2 }) }),
      })
    }
    return new Style({
      stroke: new Stroke({ color: '#ff3b30', width: 4 }),
      fill: new Fill({ color: 'rgb(255 59 48 / 20%)' }),
    })
  })
}

function locateLayerResult(result: any) {
  const resultLayer = ensureSearchLayer()
  const source = resultLayer?.getSource()
  if (!source || !map) return
  const feature = source.getFeatures().find((item) => item.get('searchFeatureId') === result.id)
  const extent = feature?.getGeometry()?.getExtent()
  if (!extent) return
  map.getView().fit(extent, { duration: 600, padding: [100, 420, 100, 100], maxZoom: 15 })
}

function zoomIn() {
  const view = map?.getView()
  if (view) view.setZoom((view.getZoom() ?? 0) + 1)
}

function zoomOut() {
  const view = map?.getView()
  if (view) view.setZoom((view.getZoom() ?? 0) - 1)
}

// 高德地理编码返回 GCJ-02；地图数据使用 WGS84，因此定位前转换回 WGS84。
function gcj02ToWgs84(lon: number, lat: number): [number, number] {
  const pi = Math.PI
  const a = 6378245.0
  const ee = 0.00669342162296594323
  const transformLat = (x: number, y: number) => {
    let ret = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
    ret += (20 * Math.sin(6 * x * pi) + 20 * Math.sin(2 * x * pi)) * 2 / 3
    ret += (20 * Math.sin(y * pi) + 40 * Math.sin(y / 3 * pi)) * 2 / 3
    ret += (160 * Math.sin(y / 12 * pi) + 320 * Math.sin(y * pi / 30)) * 2 / 3
    return ret
  }
  const transformLon = (x: number, y: number) => {
    let ret = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
    ret += (20 * Math.sin(6 * x * pi) + 20 * Math.sin(2 * x * pi)) * 2 / 3
    ret += (20 * Math.sin(x * pi) + 40 * Math.sin(x / 3 * pi)) * 2 / 3
    ret += (150 * Math.sin(x / 12 * pi) + 300 * Math.sin(x / 30 * pi)) * 2 / 3
    return ret
  }
  if (lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271) return [lon, lat]
  const dLat = transformLat(lon - 105, lat - 35)
  const dLon = transformLon(lon - 105, lat - 35)
  const radLat = lat / 180 * pi
  const magic = 1 - ee * Math.sin(radLat) ** 2
  const sqrtMagic = Math.sqrt(magic)
  const mgLat = lat + dLat * 180 / ((a * (1 - ee)) / (magic * sqrtMagic) * pi)
  const mgLon = lon + dLon * 180 / (a / sqrtMagic * Math.cos(radLat) * pi)
  return [lon * 2 - mgLon, lat * 2 - mgLat]
}

function locateResult(result: any) {
  const [lon, lat] = result.location.split(',').map(Number)
  const wgs84 = gcj02ToWgs84(lon, lat)
  const projection = props.data.projection ?? 'EPSG:4326'
  const coordinate = projection === 'EPSG:4326' ? wgs84 : transform(wgs84, 'EPSG:4326', projection)
  const resultLayer = ensureSearchLayer()
  if (!map || !resultLayer) return
  const source = resultLayer.getSource()
  source?.getFeatures().filter((feature) => feature.get('searchKind') === 'amap').forEach((feature) => source.removeFeature(feature))
  const marker = new Feature({ geometry: new Point(coordinate), searchKind: 'amap' })
  source?.addFeature(marker)
  marker.setStyle(new Style({
    image: new CircleStyle({ radius: 8, fill: new Fill({ color: '#ff4d4f' }), stroke: new Stroke({ color: '#fff', width: 3 }) }),
  }))
  map.getView().animate({ center: coordinate, zoom: Math.max(map.getView().getZoom() ?? 0, 14), duration: 600 })
  searchMessage.value = ''
}

function clearPlaceSearch() {
  placeSearchText.value = ''
  searchTabs.value = []
  activeSearchTab.value = ''
  searchLoadedByTab.value = {}
  searchMessage.value = ''
  searchResultsCollapsed.value = false
  analysisOpen.value = false
  ensureSearchLayer()?.getSource()?.clear()
  // 清空搜索后回到组件配置的初始视图。
  if (map) {
    map.getView().setCenter(props.data.center ?? [116.397, 39.916])
    map.getView().setZoom(props.data.zoom ?? 10)
  }
}

async function searchPlace() {
  const address = placeSearchText.value.trim()
  const key = props.data.amapKey || (import.meta.env.VITE_AMAP_KEY as string | undefined)
  if (!address) return
  searching.value = true
  searchMessage.value = ''
  searchTabs.value = []
  activeSearchTab.value = ''
  searchResultsCollapsed.value = false
  analysisOpen.value = false
  ensureSearchLayer()?.getSource()?.clear()
  try {
    const amapPromise = key ? (async () => {
      const params = new URLSearchParams({ key, address, city: '北京', output: 'JSON' })
      const response = await fetch(`https://restapi.amap.com/v3/geocode/geo?${params}`)
      const result = await response.json()
      return result.status === '1' ? (result.geocodes ?? []) : []
    })().catch(() => []) : Promise.resolve([])
    const layerConfigs = getLayerConfigs(props.data)
    const layerPromises = layerConfigs.map(async (config) => ({ config, results: await searchLayerData(config, address, config.id === 'livelihood-info' ? externalSearchFilter.value : '') }))
    const [amapResults, ...layerResults] = await Promise.all([amapPromise, ...layerPromises])
    const tabs: SearchTab[] = []
    if (amapResults.length) tabs.push({ id: 'amap', label: '地名地址', kind: 'amap', results: amapResults })
    const matchedFeatures = layerResults.flatMap(({ config, results }) => {
      if (results.length) tabs.push({ id: config.id ?? config.name ?? 'layer', label: config.name ?? '图层结果', kind: 'layer', results })
      return results
    })
  searchTabs.value = tabs
    completedSearchText.value = address
    searchLoadedByTab.value = Object.fromEntries(tabs.map((tab) => [tab.id, searchPageSize]))
    activeSearchTab.value = tabs[0]?.id ?? ''
    drawLayerResults(matchedFeatures)
    if (amapResults.length) locateResult(amapResults[0])
    else if (matchedFeatures.length) locateLayerResult(matchedFeatures[0])
    if (!tabs.length) searchMessage.value = key ? '未找到相关地名或图层要素' : '未找到图层要素；配置 VITE_AMAP_KEY 后可启用高德地址搜索'
    return { tabs, matchedCount: matchedFeatures.length }
  } catch (error) {
    searchMessage.value = error instanceof Error ? error.message : '搜索失败'
  } finally {
    searching.value = false
  }
}

async function searchExternal(text: string, options: { from?: string; to?: string } = {}) {
  const clauses: string[] = []
  if (options.from) clauses.push(`"派单时间" >= '${escapeCqlText(options.from)}T00:00:00Z'`)
  if (options.to) clauses.push(`"派单时间" <= '${escapeCqlText(options.to)}T23:59:59Z'`)
  externalSearchFilter.value = clauses.join(' AND ')
  placeSearchText.value = String(text ?? '').trim()
  if (!placeSearchText.value) return
  await searchPlace()
}

function focusCoordinate(coordinate: number[], zoom = 15) {
  if (!map || !Array.isArray(coordinate) || coordinate.length < 2) return false
  const x = Number(coordinate[0])
  const y = Number(coordinate[1])
  if (!Number.isFinite(x) || !Number.isFinite(y)) return false
  const resultLayer = ensureSearchLayer()
  const source = resultLayer?.getSource()
  if (focusAnimationTimer) clearInterval(focusAnimationTimer)
  if (focusFeature && source) source.removeFeature(focusFeature)
  focusFeature = new Feature({ geometry: new Point([x, y]), searchKind: 'record-focus' })
  let phase = false
  const applyFocusStyle = () => {
    phase = !phase
    focusFeature?.setStyle(new Style({
      image: new CircleStyle({
        radius: phase ? 13 : 8,
        fill: new Fill({ color: phase ? 'rgba(22,119,255,.28)' : 'rgba(22,119,255,.58)' }),
        stroke: new Stroke({ color: '#ffffff', width: 3 }),
      }),
    }))
  }
  source?.addFeature(focusFeature)
  applyFocusStyle()
  focusAnimationTimer = setInterval(applyFocusStyle, 520)
  map.getView().animate({ center: [x, y], zoom, duration: 600 })
  return true
}

defineExpose({ searchExternal, clearPlaceSearch, focusCoordinate })

function syncView(data: MapData) {
  if (!map) return
  map.setView(new View({
    center: data.center ?? [799587, 602562],
    zoom: data.zoom ?? 10,
    minZoom: data.minZoom,
    maxZoom: data.maxZoom,
    projection: data.projection ?? 'EPSG:4326',
  }))
}

function fitInitialExtent(data: MapData) {
  if (!map || !data.initialExtent || data.initialExtent.length !== 4) return
  map.getView().fit(data.initialExtent, {
    padding: [48, 48, 48, 48],
    maxZoom: data.initialExtentMaxZoom ?? 13,
    duration: 0,
  })
  if (data.center) map.getView().setCenter(data.center)
}

onMounted(() => {
  if (!mapElement.value) return
  map = new Map({
    target: mapElement.value,
    // 使用组件自己的右下角缩放按钮，避免 OpenLayers 默认控件出现在左上角。
    controls: [],
    view: new View({
      center: props.data.center ?? [799587, 602562],
      zoom: props.data.zoom ?? 10,
      projection: props.data.projection ?? 'EPSG:4326',
    }),
  })
  syncLayers(props.data)
  fitInitialExtent(props.data)
  map.on('click', (event) => {
    emit('map-click', { coordinate: event.coordinate, pixel: event.pixel })
    if (activeTool.value === 'property') queryProperties(event.coordinate)
    if (activeTool.value === 'buffer' && bufferMode.value === 'feature') selectBufferFeature(event.coordinate)
  })
  emit('ready', map)
})

watch(() => props.data, (data) => {
  syncView(data)
  syncLayers(data)
}, { deep: true })

onBeforeUnmount(() => {
  if (focusAnimationTimer) clearInterval(focusAnimationTimer)
  focusAnimationTimer = null
  focusFeature = null
  stopSwipeDrag()
  stopPlotInteraction()
  stopMeasurement()
  layers = []
  splitMap?.setTarget(undefined)
  splitMap = null
  swipeMap?.setTarget(undefined)
  swipeMap = null
  map?.setTarget(undefined)
  map = null
  pointLayer = null
})
</script>

<template>
  <div ref="widgetElement" class="map-widget" :class="{ 'split-active': splitActive }" aria-label="基础地图组件">
    <div ref="mapElement" class="map-canvas" />
    <div v-if="splitActive" ref="splitMapElement" class="split-map-canvas" aria-label="右侧分屏地图" />
    <div v-if="swipeActive" class="swipe-map-canvas" :style="{ clipPath: `inset(0 0 0 ${swipePosition}%)` }">
      <div ref="swipeMapElement" class="swipe-map-target" aria-label="卷帘图层" />
    </div>
    <div v-if="swipeActive" class="swipe-divider" :style="{ left: `${swipePosition}%` }" aria-label="拖动卷帘分界线"
      @pointerdown="startSwipeDrag">
      <span>⋮</span>
    </div>

    <section v-if="swipeActive" class="swipe-controls" aria-label="卷帘图层设置">
      <label>对比图层
        <select v-model="swipeLayerId" @change="applySwipeSelection">
          <option v-for="layer in layerRows" :key="`swipe-${layer.id}`" :value="layer.id">{{ layer.name || layer.id }}</option>
        </select>
      </label>
      <input v-model.number="swipePosition" type="range" min="10" max="90" aria-label="卷帘位置" />
    </section>

    <section v-if="splitActive" class="split-controls" aria-label="分屏图层设置">
      <label>左屏
        <select v-model="splitLeftLayerId" @change="applySplitSelection">
          <option v-for="layer in layerRows" :key="`left-${layer.id}`" :value="layer.id">{{ layer.name || layer.id }}</option>
        </select>
      </label>
      <label>右屏
        <select v-model="splitRightLayerId" @change="applySplitSelection">
          <option v-for="layer in layerRows" :key="`right-${layer.id}`" :value="layer.id">{{ layer.name || layer.id }}</option>
        </select>
      </label>
    </section>

    <section v-if="plotActive" class="plot-controls" aria-label="标绘类型选择">
      <span>标绘</span>
      <button v-for="item in [
        { type: 'Point', label: '点' },
        { type: 'LineString', label: '线' },
        { type: 'Polygon', label: '面' },
        { type: 'Circle', label: '圆' },
        { type: 'Rectangle', label: '矩形' },
      ]" :key="item.type" :class="{ active: plotType === item.type }"
        @click="choosePlotType(item.type as PlotType)">{{ item.label }}</button>
    </section>

    <section v-if="bufferActive" class="buffer-controls" aria-label="缓冲查询设置">
      <div class="buffer-control-row">
        <strong>缓冲查询</strong>
        <button :class="{ active: bufferMode === 'feature' }" @click="bufferMode = 'feature'; applyBufferMode()">选取要素</button>
        <button :class="{ active: bufferMode === 'draw' }" @click="bufferMode = 'draw'; applyBufferMode()">绘制范围</button>
      </div>
      <div class="buffer-control-row">
        <label>源图层
          <select v-model="bufferSourceLayerId" @change="applyBufferMode">
            <option v-for="layer in layerRows" :key="`buffer-source-${layer.id}`" :value="layer.id">{{ layer.name || layer.id }}</option>
          </select>
        </label>
        <label>查询图层
          <select v-model="bufferTargetLayerId" @change="bufferResults = []; bufferPage = 1; bufferVisibleCount = 10; bufferResultSource.clear()">
            <option v-for="layer in layerRows" :key="`buffer-target-${layer.id}`" :value="layer.id">{{ layer.name || layer.id }}</option>
          </select>
        </label>
      </div>
      <label class="buffer-distance">距离 {{ bufferDistance }} 米
        <input v-model.number="bufferDistance" type="range" min="10" max="3000" step="10" />
      </label>
      <div class="buffer-help">{{ bufferMode === 'feature' ? '请点击地图上的源图层要素' : '请在地图上绘制一个范围' }}</div>
      <div v-if="bufferQuerying" class="buffer-help">正在查询…</div>
      <div v-if="bufferMessage" class="buffer-help">{{ bufferMessage }}</div>
      <div v-if="bufferResults.length" class="buffer-results">
        <div class="buffer-result-title">查询结果（{{ bufferResults.length }}）</div>
        <button v-for="(result, index) in pagedBufferResults" :key="result.id ?? index" class="buffer-result-row"
          @click="showPropertyResult({ ...result, layerName: bufferConfig(bufferTargetLayerId)?.name || '缓冲查询结果' }, 'layer')">
          <strong>{{ result.label }}</strong>
          <small>{{ result.properties?.地址 || result.properties?.标题 || result.properties?.站点名称 || '查看属性' }}</small>
        </button>
        <div v-if="bufferVisibleCount < bufferResults.length" class="buffer-pagination">
          <span>已加载 {{ Math.min(bufferVisibleCount, bufferResults.length) }} / {{ bufferResults.length }} 条</span>
          <button v-if="bufferTargetLayerId === 'livelihood-info' && analysisEnabled" class="analysis-trigger" @click="openBufferAnalysis">数据分析</button>
          <button @click="loadMoreBufferResults">加载更多（10 条）</button>
        </div>
        <div v-else class="buffer-pagination buffer-pagination-done">
          <span>已加载全部 {{ bufferResults.length }} 条</span>
          <button v-if="bufferTargetLayerId === 'livelihood-info' && analysisEnabled" class="analysis-trigger" @click="openBufferAnalysis">数据分析</button>
        </div>
      </div>
    </section>

    <section v-if="layerPanelOpen" class="layer-panel" aria-label="图层列表">
      <div class="panel-search">
      <input v-model="layerSearchText" placeholder="请输入资源名称" aria-label="搜索图层" />
        <span>⌕</span>
      </div>
      <div class="panel-title"><span>⌄</span> 图层列表</div>
      <div class="layer-group"><span>⌄</span> 基础图层</div>
      <label v-for="layer in filteredLayers" :key="layer.id" class="layer-row">
        <input type="checkbox" :checked="layer.visible !== false" @change="toggleLayer(layer)" />
        <span class="layer-name">{{ layer.name || layer.id }}</span>
        <span class="layer-kind">{{ layer.type }}</span>
      </label>
      <div v-if="!filteredLayers.length" class="empty-layer">未找到图层</div>
    </section>

    <div v-if="showPlaceSearch" class="top-search">
      <input v-model="placeSearchText" placeholder="请输入搜索词" aria-label="地图搜索" @keyup.enter="searchPlace" />
      <button v-if="placeSearchText || searchTabs.length || searchMessage" class="search-clear" aria-label="清空地图搜索" @click="clearPlaceSearch">×</button>
      <button v-if="searchTabs.length" class="search-collapse" :aria-label="searchResultsCollapsed ? '展开搜索结果' : '收起搜索结果'"
        :title="searchResultsCollapsed ? '展开搜索结果' : '收起搜索结果'" @click="searchResultsCollapsed = !searchResultsCollapsed">
        {{ searchResultsCollapsed ? '⌄' : '⌃' }}
      </button>
      <button aria-label="搜索" :disabled="searching" @click="searchPlace">{{ searching ? '…' : '⌕' }}</button>
    </div>

    <div v-if="searchTabs.length && !searchResultsCollapsed" class="search-results" aria-label="搜索结果">
      <div class="search-tabs" role="tablist">
        <button v-for="tab in searchTabs" :key="tab.id" class="search-tab" :class="{ active: activeSearchTab === tab.id }"
          role="tab" :aria-selected="activeSearchTab === tab.id" @click="activeSearchTab = tab.id">
          {{ tab.label }} <span>{{ tab.results.length }}</span>
        </button>
      </div>
      <div v-for="tab in searchTabs" v-show="activeSearchTab === tab.id" :key="`${tab.id}-results`" class="search-tab-content">
        <button v-for="(result, index) in pagedSearchResults(tab)" :key="`${result.location ?? result.id}-${index}`" class="search-result"
          @click="tab.kind === 'amap' ? (locateResult(result), showPropertyResult(result, 'amap')) : (locateLayerResult(result), showPropertyResult(result, 'layer'))">
          <strong>{{ tab.kind === 'amap' ? (result.formatted_address || result.address || '未命名地点') : (result.properties?.标题 || result.label) }}</strong>
          <small v-if="tab.kind === 'amap'">{{ result.province }}{{ result.city }}{{ result.district || '' }} · {{ result.location }}</small>
          <small v-else>{{ result.properties?.地址 || result.properties?.站点标准名称 || result.properties?.line_name || '未提供地址' }}</small>
        </button>
        <div v-if="(searchLoadedByTab[tab.id] ?? searchPageSize) < tab.results.length" class="search-pagination">
          <span>已加载 {{ Math.min(searchLoadedByTab[tab.id] ?? searchPageSize, tab.results.length) }} / {{ tab.results.length }} 条</span>
          <button v-if="tab.kind === 'layer' && analysisEnabled" class="analysis-trigger" @click.stop="openAnalysis(tab)">数据分析</button>
          <button @click="loadMoreSearch(tab.id)">加载更多（10 条）</button>
        </div>
        <div v-else-if="tab.kind === 'layer'" class="search-pagination">
          <span>已加载全部 {{ tab.results.length }} 条</span>
          <button v-if="analysisEnabled" class="analysis-trigger" @click.stop="openAnalysis(tab)">数据分析</button>
        </div>
      </div>
    </div>

    <aside v-if="analysisOpen" class="analysis-panel" aria-label="诉求数据分析">
      <header class="analysis-header">
        <div><strong>{{ analysisData.name }} · 诉求分析</strong><small>基于全部 {{ analysisData.total }} 条结果 · {{ analysisData.period }}</small></div>
        <button aria-label="关闭数据分析" @click="analysisOpen = false">×</button>
      </header>
      <div class="analysis-body">
        <div class="analysis-cards">
          <div><span>精准匹配</span><strong>{{ analysisData.exact }}</strong><em>条</em></div>
          <div><span>扩展匹配</span><strong>{{ analysisData.expanded }}</strong><em>条</em></div>
          <div><span>标题主题数</span><strong>{{ analysisData.topicCount }}</strong><em>组</em></div>
        </div>
        <small class="analysis-definition">匹配口径：地址与搜索词完全一致为精准匹配，其余当前检索结果为扩展匹配；不是空间匹配精度评级。</small>
        <h3>主要诉求主题 · 标题频次前三</h3>
        <div class="analysis-topics">
          <div v-for="topic in analysisData.topics" :key="topic.label"><b>{{ topic.percent }}%</b><span>{{ topic.label }}（{{ topic.count }}条）</span></div>
        </div>
        <p class="analysis-summary">已检索到 {{ analysisData.total }} 条相关诉求，其中精准匹配 {{ analysisData.exact }} 条、扩展匹配 {{ analysisData.expanded }} 条。根据标题出现频次，当前诉求主要集中在以上主题，建议结合派单时间分布安排后续研判和办理。</p>
        <details v-if="analysisData.name === '公园懿府'" class="analysis-reference" open>
          <summary>参考总结（示例文案，办理结论待核实）</summary>
          <p>公园懿府、阳光星苑等小区诉求集中于增加19号线南延站点、改善出行条件。参考图中的研判认为，可结合《北京市轨道交通线网规划（2020年—2035年）》及新宫南站规划进一步分析服务距离和诉求变化。此段沿用参考图的总结方向，实际落实情况须结合规划与办理记录核实。</p>
        </details>
        <h3>{{ analysisData.name }}诉求派单时间分布</h3>
        <div class="analysis-chart" v-if="analysisData.monthly.length">
          <div class="analysis-chart-legend"><span class="actual-line" /> 月度派单数 <span class="normal-line" /> 正态分布拟合</div>
          <svg viewBox="0 0 520 220" role="img" aria-label="派单时间分布图" @mousemove="updateChartHover" @mouseleave="clearChartHover">
            <line x1="28" y1="190" x2="510" y2="190" /><line x1="28" y1="20" x2="28" y2="190" />
            <line x1="28" y1="109" x2="498" y2="109" />
            <text x="2" y="29">{{ analysisData.maxCount }}</text>
            <text x="2" y="111">{{ Math.round(analysisData.maxCount / 2) }}</text>
            <text x="12" y="190">0</text>
            <polyline :points="analysisData.normalPath" class="normal-path" transform="translate(28 10)" />
            <polyline :points="analysisData.monthlyPath" class="actual-path" transform="translate(28 10)" />
            <template v-if="chartHoverIndex !== null">
              <line :x1="chartPointX(chartHoverIndex, analysisData.monthly.length)" y1="20"
                :x2="chartPointX(chartHoverIndex, analysisData.monthly.length)" y2="190" class="chart-crosshair" />
              <circle :cx="chartPointX(chartHoverIndex, analysisData.monthly.length)"
                :cy="chartPointY(analysisData.monthly[chartHoverIndex].count, analysisData.maxCount)" r="5" class="chart-hover-dot" />
            </template>
            <text x="30" y="210">{{ analysisData.monthly[0].label }}</text>
            <text x="430" y="210">{{ analysisData.monthly[analysisData.monthly.length - 1].label }}</text>
          </svg>
          <div v-if="chartHoverIndex !== null" class="chart-hover-tip"
            :style="{ left: `${chartPointX(chartHoverIndex, analysisData.monthly.length) / 520 * 100}%` }">
            <strong>{{ analysisData.monthly[chartHoverIndex].label }}</strong>
            <span>派单数：{{ analysisData.monthly[chartHoverIndex].count }} 条</span>
          </div>
          <div class="analysis-peak">峰值 {{ analysisData.peak.label }}：{{ analysisData.peak.count }} 条</div>
          <small class="analysis-definition">按派单月份统计 {{ analysisData.dated }} 条，缺失或无效日期 {{ analysisData.missingDates }} 条不计入；空缺月份补零。橙线为按派单时间加权估计的正态参考曲线，不代表数据符合正态分布。</small>
        </div>
        <div v-else class="analysis-empty">当前结果没有可识别的派单时间</div>
      </div>
    </aside>

    <div v-if="searchMessage" class="search-message">{{ searchMessage }}</div>
    <div v-if="captureMessage" class="capture-message">{{ captureMessage }}</div>

    <section v-if="activeTool === 'property' && (propertyQuerying || propertyMessage || propertyGroups.length)"
      class="property-popup" aria-label="属性查询结果">
      <header class="property-header">
        <div><strong>属性查询结果</strong><small v-if="propertyGroups.length">{{ propertyGroups.length }} 个图层 · 按图层查看要素</small></div>
        <button class="property-close" aria-label="关闭属性结果" @click="closePropertyResults">×</button>
      </header>
      <div class="property-body">
        <div v-if="propertyQuerying" class="property-empty">正在查询属性…</div>
        <div v-else-if="propertyMessage" class="property-empty">{{ propertyMessage }}</div>
        <section v-for="group in propertyGroups" :key="group.id" class="property-group">
          <button class="property-group-toggle" :aria-expanded="expandedPropertyGroup === group.id"
            @click="expandedPropertyGroup = expandedPropertyGroup === group.id ? '' : group.id">
            <span>{{ group.name }}（{{ group.total === null ? '总数待确认' : group.total }}）</span>
            <span aria-hidden="true">{{ expandedPropertyGroup === group.id ? '⌃' : '⌄' }}</span>
          </button>
          <div v-if="expandedPropertyGroup === group.id" class="property-group-content">
            <section v-for="(result, index) in group.results" :key="`${result.featureId ?? index}-${index}`" class="property-result">
              <h3><span class="property-record-index">{{ index + 1 }}</span>{{ featureLabel({ properties: result.properties }, result.featureId || '要素详情') }}</h3>
              <dl>
                <template v-for="(value, key) in result.properties" :key="key">
                  <div v-if="value !== null && value !== ''" class="property-row"><dt>{{ key }}</dt><dd>{{ value }}</dd></div>
                </template>
              </dl>
            </section>
            <div class="property-more">
              <small>已加载 {{ group.results.length }} 条{{ group.total === null ? '' : ` / 共 ${group.total} 条` }}</small>
              <p v-if="group.error" role="alert">{{ group.error }}</p>
              <button v-if="group.hasMore || group.error" :disabled="group.loading" @click="loadPropertyPage(group)">
                {{ group.loading ? '正在加载…' : group.error ? '重试加载' : '查看更多（10 条）' }}
              </button>
              <small v-else>已全部加载</small>
            </div>
          </div>
        </section>
      </div>
    </section>

    <nav class="tool-panel" aria-label="地图工具栏">
      <button v-if="showLayerTool" class="layer-toggle" :class="{ active: layerPanelOpen }" title="图层"
        @click="layerPanelOpen = !layerPanelOpen">
        <span class="tool-icon">▤</span>
        <span>图层</span>
      </button>
      <button v-for="tool in toolbarItems" :key="tool.id" :class="{ active: activeTool === tool.id }" :title="tool.label"
        @click="activateTool(tool.id)">
        <span class="tool-icon">{{ tool.icon }}</span>
        <span>{{ tool.label }}</span>
      </button>
    </nav>

    <button v-if="showLayerTool" class="layer-manager-trigger" :aria-expanded="layerManagerOpen"
      @click="layerManagerOpen = !layerManagerOpen" aria-label="图层管理">
      <span class="layer-manager-icon" aria-hidden="true">▱</span>
      <span class="layer-manager-label">图层<br />管理</span>
      <span class="layer-manager-count">{{ managedLayers.length }}</span>
    </button>
    <section v-if="layerManagerOpen" class="layer-manager" aria-label="图层管理">
      <header class="layer-manager-header">
        <div><strong>图层管理</strong><small>上方图层覆盖下方图层 · 拖动 ⠿ 调整顺序</small></div>
        <button aria-label="关闭图层管理" @click="layerManagerOpen = false">×</button>
      </header>
      <div class="layer-manager-list">
        <p v-if="!managedLayers.length" class="layer-manager-empty">暂无已选图层，请从右侧“图层”列表勾选。</p>
        <article v-for="(layer, index) in managedLayers" :key="layer.id" class="managed-layer"
          :class="{ dragging: draggedLayerId === layer.id }" :aria-label="layer.name || layer.id"
          @dragover.prevent @drop.prevent="dropManagedLayer(layer.id!)">
          <div class="managed-layer-heading">
            <button draggable="true" class="layer-drag-handle" :aria-label="`拖动${layer.name || layer.id}`"
              @dragstart="startLayerDrag($event, layer.id!)" @dragend="draggedLayerId = null">⠿</button>
            <strong>{{ layer.name || layer.id }}</strong>
            <button :disabled="index === 0" :aria-label="`上移${layer.name || layer.id}`"
              @click="moveManagedLayer(layer.id!, managedLayers[index - 1].id!)">↑</button>
            <button :disabled="index === managedLayers.length - 1" :aria-label="`下移${layer.name || layer.id}`"
              @click="moveManagedLayer(layer.id!, managedLayers[index + 1].id!)">↓</button>
            <button class="layer-remove" :aria-label="`移除${layer.name || layer.id}`" @click="removeManagedLayer(layer)">×</button>
          </div>
          <label class="managed-layer-opacity"><span>不透明度</span>
            <input type="range" min="0" max="100" step="1" :value="Math.round((layer.opacity ?? 1) * 100)"
              :aria-label="`${layer.name || layer.id}不透明度`" @input="changeLayerOpacity(layer, $event)" />
            <output>{{ Math.round((layer.opacity ?? 1) * 100) }}%</output>
          </label>
        </article>
      </div>
    </section>

    <div class="basemap-switcher" aria-label="底图切换">
      <button :class="{ active: basemapMode === 'vector' }" @click="switchBasemap('vector')">矢量</button>
      <button :class="{ active: basemapMode === 'imagery' }" @click="switchBasemap('imagery')">影像</button>
    </div>

    <div class="map-zoom" aria-label="地图缩放">
      <button aria-label="放大" title="放大" @click="zoomIn">＋</button>
      <button aria-label="缩小" title="缩小" @click="zoomOut">－</button>
    </div>

  </div>
</template>
