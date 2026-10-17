/* DataV protocol-2 adapter. The compiled map engine is loaded from widget.js. */
var loaded = null;
var instances = new WeakMap();
var entryScript = typeof document !== 'undefined' ? document.currentScript : null;
var entryBase = entryScript && entryScript.src ? entryScript.src.slice(0, entryScript.src.lastIndexOf('/') + 1) : './';
function containerOf(value) { return value && value.nodeType === 1 ? value : (value && value[0]); }
function loadWidget() {
  if (window.BjghDataVMap) return Promise.resolve(window.BjghDataVMap);
  if (loaded) return loaded;
  loaded = new Promise(function (resolve, reject) {
    var script = document.createElement('script'); script.src = entryBase + 'widget.js';
    script.onload = function () { resolve(window.BjghDataVMap); }; script.onerror = reject; document.head.appendChild(script);
  });
  return loaded;
}
function renderWidget(ctx, data) {
  var container = containerOf(ctx.container); if (!container) return;
  loadWidget().then(function (engine) {
    var old = instances.get(container); if (old && old.app) old.app.unmount();
    instances.set(container, engine.mountDataVMap(container, data || {}));
  }).catch(function (error) { container.textContent = '地图组件加载失败：' + error.message; });
}
module.exports = {
  Init: function () {},
  render: function (data) { renderWidget(this, data); },
  updateOptions: function (data) { renderWidget(this, data); },
  resize: function () {
    var container = containerOf(this.container);
    var old = container && instances.get(container);
    if (old && old.app && old.app._instance && old.app._instance.subTree) window.dispatchEvent(new Event('resize'));
  },
  clear: function () {
    var container = containerOf(this.container); var old = container && instances.get(container);
    if (old && old.app) old.app.unmount();
    if (container) container.innerHTML = '';
    if (container) instances.delete(container);
  },
  destroy: function () {
    var container = containerOf(this.container); var old = container && instances.get(container);
    if (old && old.app) old.app.unmount();
    if (container) { container.innerHTML = ''; instances.delete(container); }
  }
};
