<script setup lang="ts">
import MapWidget from './MapWidget.vue'

const geoServerUrl = 'http://8.146.208.20/geoserver/bj2000/wms'
const tiandituKey = import.meta.env.VITE_TIANDITU_KEY as string | undefined
const tiandituTileUrl = (layer: 'vec' | 'img' | 'cva' | 'cia') =>
  `https://t{0-7}.tianditu.gov.cn/${layer}_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${encodeURIComponent(tiandituKey ?? '')}`
const tiandituBaseLayers = tiandituKey ? {
  vector: {
    id: 'vector-basemap', name: '矢量底图', type: 'XYZ' as const,
    url: tiandituTileUrl('vec'),
    sourceProjection: 'EPSG:3857', visible: true,
  },
  imagery: {
    id: 'imagery-basemap', name: '影像底图', type: 'XYZ' as const,
    url: tiandituTileUrl('img'),
    sourceProjection: 'EPSG:3857', visible: true,
  },
} : undefined
const tiandituAnnotations = tiandituKey ? {
  vector: {
    id: 'vector-annotations', name: '矢量注记', type: 'XYZ' as const,
    url: tiandituTileUrl('cva'),
    sourceProjection: 'EPSG:3857', visible: true,
  },
  imagery: {
    id: 'imagery-annotations', name: '影像注记', type: 'XYZ' as const,
    url: tiandituTileUrl('cia'),
    sourceProjection: 'EPSG:3857', visible: true,
  },
} : undefined

const mapData = {
  center: [799587, 602562],
  zoom: 13,
  projection: 'EPSG:100007',
  baseLayers: [],
  ...(tiandituBaseLayers ? { basemap: tiandituBaseLayers } : {}),
  ...(tiandituAnnotations ? { basemapAnnotations: tiandituAnnotations } : {}),
  layers: [
    {
      id: 'city-boundary', name: '北京市市级行政区划边界', type: 'WMS' as const,
      url: geoServerUrl, params: { LAYERS: 'bj2000:beijing_city_boundary_bj2000' }, visible: true,
    },
    {
      id: 'district-boundary', name: '北京市区级行政区划边界', type: 'WMS' as const,
      url: geoServerUrl, params: { LAYERS: 'bj2000:beijing_district_boundary_bj2000' }, visible: true,
    },
    {
      id: 'township-boundary', name: '北京市乡镇级行政边界', type: 'WMS' as const,
      url: geoServerUrl, params: { LAYERS: 'bj2000:beijing_township_boundary_bj2000' }, visible: false,
    },
    {
      id: 'subway-lines', name: '北京市轨道交通线路', type: 'WMS' as const,
      url: geoServerUrl, params: { LAYERS: 'bj2000:北京轨道交通线路_OSM_bj2000' },
      searchFields: ['line_name', 'osm_name'], sortField: 'osm_id', visible: false,
    },
    {
      id: 'subway-stations', name: '北京市轨道交通站点', type: 'WMS' as const,
      url: geoServerUrl, params: { LAYERS: 'bj2000:北京轨道站点字典_bj2000' },
      searchFields: ['站点名称', '站点标准名称', '线路名称', '线路标准名称'], sortField: '站点主键', visible: false,
    },
    {
      id: 'livelihood-info', name: '民生民情信息', type: 'WMS' as const,
      url: geoServerUrl, params: { LAYERS: 'bj2000:民生民情信息_bj2000' },
      searchFields: ['地址'], sortField: '业务主键', visible: true,
    },
  ],
  toolbar: { screenshot: false, distance: false, area: false, draw: false },
}
</script>

<template>
  <MapWidget :data="mapData" />
</template>
