/* DataV protocol 2 native iframe widget. No Vue, React or third-party runtime. */
'use strict'

function elementOf(container) {
  if (!container) return null
  if (container.nodeType === 1) return container
  if (container[0] && container[0].nodeType === 1) return container[0]
  return null
}

function valueOf(data, key) {
  if (Array.isArray(data)) data = data[0] || {}
  return data && data[key]
}

function bool(value, fallback) {
  if (value === undefined || value === null || value === '') return fallback
  return value === true || value === 'true' || value === 1 || value === '1'
}

function IframeWidget(container, config) {
  this.container = elementOf(container)
  this.config = config || {}
  this.root = null
  this.frame = null
  this.loading = null
  this.error = null
  this.reloadTimer = null
  this.render(null, this.config)
}

IframeWidget.prototype.render = function (data, config) {
  if (!this.container) return
  this.config = Object.assign({}, this.config || {}, config || {})
  var url = valueOf(data, 'url') || this.config.url || this.config.src || ''
  this.url = String(url || '').trim()
  if (!this.root) this.createView()
  this.root.style.background = this.config.background || '#f5f8fb'
  this.frame.title = this.config.title || '嵌套业务系统'
  this.frame.allow = this.config.allow || 'fullscreen'
  this.frame.referrerPolicy = this.config.referrerPolicy || 'strict-origin-when-cross-origin'
  this.toolbar.style.display = bool(this.config.showToolbar, true) ? 'flex' : 'none'
  this.fullscreenButton.style.display = bool(this.config.allowFullscreen, true) ? 'inline-block' : 'none'
  this.load()
  this.clearTimer()
  if (bool(this.config.autoReload, false) && this.url) {
    var self = this
    this.reloadTimer = setInterval(function () { self.load() }, Math.max(5, Number(self.config.reloadInterval) || 60) * 1000)
  }
}

IframeWidget.prototype.createView = function () {
  var self = this
  this.container.innerHTML = ''
  this.root = document.createElement('div')
  this.root.style.cssText = 'position:relative;width:100%;height:100%;overflow:hidden;background:#f5f8fb;font-family:Arial,"Microsoft YaHei",sans-serif'
  this.frame = document.createElement('iframe')
  this.frame.style.cssText = 'display:block;width:100%;height:100%;border:0;background:#fff'
  this.loading = document.createElement('div')
  this.loading.textContent = this.config.loadingText || '系统加载中…'
  this.loading.style.cssText = 'position:absolute;z-index:2;inset:0;display:flex;align-items:center;justify-content:center;color:#587086;font-size:13px;background:rgba(245,248,251,.92)'
  this.error = document.createElement('div')
  this.error.style.cssText = 'position:absolute;z-index:3;inset:0;display:none;align-items:center;justify-content:center;padding:24px;color:#b54b4b;font-size:13px;text-align:center;background:#fff'
  this.toolbar = document.createElement('div')
  this.toolbar.style.cssText = 'position:absolute;z-index:4;top:10px;right:10px;display:flex;gap:6px;padding:4px;border:1px solid #d9e6ef;border-radius:8px;background:rgba(255,255,255,.94);box-shadow:0 2px 8px rgba(31,72,104,.12)'
  this.reloadButton = this.button('刷新')
  this.fullscreenButton = this.button('全屏')
  this.toolbar.appendChild(this.reloadButton)
  this.toolbar.appendChild(this.fullscreenButton)
  this.root.appendChild(this.frame)
  this.root.appendChild(this.loading)
  this.root.appendChild(this.error)
  this.root.appendChild(this.toolbar)
  this.container.appendChild(this.root)
  this.frame.addEventListener('load', function () { self.loading.style.display = 'none'; self.error.style.display = 'none' })
  this.frame.addEventListener('error', function () { self.showError('嵌套系统加载失败，请检查地址和 iframe 安全策略') })
  this.reloadButton.addEventListener('click', function () { self.load() })
  this.fullscreenButton.addEventListener('click', function () {
    if (self.root.requestFullscreen) self.root.requestFullscreen()
    else if (self.root.webkitRequestFullscreen) self.root.webkitRequestFullscreen()
  })
}

IframeWidget.prototype.button = function (text) {
  var button = document.createElement('button')
  button.type = 'button'
  button.textContent = text
  button.style.cssText = 'border:0;border-radius:5px;padding:5px 8px;background:transparent;color:#287cca;font-size:12px;cursor:pointer'
  return button
}

IframeWidget.prototype.load = function () {
  if (!this.url) {
    this.showError('请在 DataV 配置中填写要嵌套的系统地址')
    return
  }
  this.error.style.display = 'none'
  this.loading.style.display = 'flex'
  if (this.config.sandbox) this.frame.setAttribute('sandbox', this.config.sandbox)
  else this.frame.removeAttribute('sandbox')
  this.frame.src = this.url
}

IframeWidget.prototype.showError = function (message) { this.error.textContent = message; this.error.style.display = 'flex'; this.loading.style.display = 'none' }
IframeWidget.prototype.updateOptions = function (config) { this.render(null, config) }
IframeWidget.prototype.resize = function () {}
IframeWidget.prototype.clear = function () { this.clearTimer(); if (this.container) this.container.innerHTML = '' }
IframeWidget.prototype.destroy = function () { this.clear() }
IframeWidget.prototype.postMessage = function (message, targetOrigin) { if (this.frame && this.frame.contentWindow) this.frame.contentWindow.postMessage(message, targetOrigin || '*') }
IframeWidget.prototype.clearTimer = function () { if (this.reloadTimer) clearInterval(this.reloadTimer); this.reloadTimer = null }

module.exports = IframeWidget
