import { createApp, type App as VueApp } from 'vue'
import MapWidget from './MapWidget.vue'
import proj4 from 'proj4'
import { register } from 'ol/proj/proj4.js'

const mapProjection = 'EPSG:100007'
const mapProj4 = '+proj=tmerc +lat_0=39.9061111111 +lon_0=116.3911111111 +k=1 +x_0=800000 +y_0=600000 +ellps=GRS80 +units=m +no_defs'
const defaultCenter = [799587, 602562]
proj4.defs(mapProjection, mapProj4)
register(proj4)

type DataVConfig = Record<string, any>

const defaultLayers = [
  ['city-boundary', '北京市市级行政区划边界', 'beijing_city_boundary_bj2000', true],
  ['district-boundary', '北京市区级行政区划边界', 'beijing_district_boundary_bj2000', true],
  ['township-boundary', '北京市乡镇级行政边界', 'beijing_township_boundary_bj2000', false],
  ['subway-lines', '北京市轨道交通线路', '北京轨道交通线路_OSM_bj2000', false, ['line_name', 'osm_name'], 'osm_id'],
  ['subway-stations', '北京市轨道交通站点', '北京轨道站点字典_bj2000', false, ['站点名称', '站点标准名称', '线路名称', '线路标准名称'], '站点主键'],
  ['livelihood-info', '民生民情信息', 'bj2000:民生民情信息_bj2000', true, ['地址'], '业务主键'],
]

function layerConfig(item: any[], geoServerUrl: string, workspace: string) {
  return {
    id: item[0], name: item[1], type: 'WMS',
    url: `${geoServerUrl.replace(/\/$/, '')}/${workspace}/wms`,
    params: { LAYERS: item[2].includes(':') ? item[2] : `${workspace}:${item[2]}`, VERSION: '1.1.1' },
    ...(item[4] ? { searchFields: item[4] } : {}),
    ...(item[5] ? { sortField: item[5] } : {}),
    visible: item[3],
  }
}

function normalizeConfig(input: DataVConfig = {}) {
  // DataV 可能按 group 保留 service/view/features 嵌套，也可能传平铺对象，两种格式都兼容。
  const service = { ...input, ...(input.service || {}) }
  const view = { ...input, ...(input.view || {}) }
  const features = { ...input, ...(input.features || {}) }
  const geoServerUrl = service.geoServerUrl || 'http://127.0.0.1:8080/geoserver'
  const workspace = service.geoServerWorkspace || 'bj2000'
  const projection = view.projection || mapProjection
  const vectorUrl = service.vectorBasemapUrl || ''
  const imageryUrl = service.imageryBasemapUrl || ''
  const configuredBasemap = input.basemap || service.basemap
  const basemapAnnotations = input.basemapAnnotations || service.basemapAnnotations
  const center = view.centerX !== undefined && view.centerY !== undefined
    ? [Number(view.centerX), Number(view.centerY)]
    : view.centerLon !== undefined && view.centerLat !== undefined
      ? proj4('EPSG:4326', projection, [Number(view.centerLon), Number(view.centerLat)])
      : defaultCenter
  return {
    center, zoom: Number(view.zoom ?? 13), projection,
    placeSearchEnabled: features.placeSearchEnabled !== false,
    analysisEnabled: features.analysisEnabled !== false,
    amapKey: service.amapKey || '',
    toolbar: features.toolbar || input.toolbar || {},
    points: Array.isArray(input.points) ? input.points : [],
    ...(configuredBasemap ? { basemap: configuredBasemap } : {}),
    ...(basemapAnnotations ? { basemapAnnotations } : {}),
    ...(vectorUrl || imageryUrl ? { basemap: {
      vector: {
        id: 'vector-basemap', name: '矢量底图',
        type: service.vectorBasemapType || 'XYZ', url: vectorUrl,
        sourceProjection: service.vectorBasemapProjection || 'EPSG:3857',
        params: service.vectorBasemapParams || {}, visible: Boolean(vectorUrl),
      },
      imagery: {
        id: 'imagery-basemap', name: '影像底图',
        type: service.imageryBasemapType || 'XYZ', url: imageryUrl,
        sourceProjection: service.imageryBasemapProjection || 'EPSG:3857',
        params: service.imageryBasemapParams || {}, visible: Boolean(imageryUrl),
      },
    } } : {}),
    layers: Array.isArray(input.layers) && input.layers.length
      ? input.layers : defaultLayers.map((item) => layerConfig(item, geoServerUrl, workspace)),
  }
}

export function mountDataVMap(container: HTMLElement, config: DataVConfig = {}) {
  container.innerHTML = ''
  const host = document.createElement('div')
  host.style.width = '100%'
  host.style.height = '100%'
  container.appendChild(host)
  const app: VueApp = createApp(MapWidget, {
    data: normalizeConfig(config),
    onMapClick: config.onMapClick,
  })
  const widget = app.mount(host)
  return { app, host, widget }
}

export { normalizeConfig }
