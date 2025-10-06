(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') {
      fn();
    } else {
      document.addEventListener('DOMContentLoaded', fn);
    }
  }

  var STORAGE_KEY = 'inventory.product_canvas.layout';

  function parseProducts(wrapper) {
    if (!wrapper) return [];
    var raw = wrapper.getAttribute('data-products');
    if (!raw) return [];
    try {
      return JSON.parse(raw);
    } catch (err) {
      console.error('Unable to parse product canvas payload', err);
      return [];
    }
  }

  function supportsLocalStorage() {
    try {
      var testKey = '__product_canvas_storage_test__';
      window.localStorage.setItem(testKey, testKey);
      window.localStorage.removeItem(testKey);
      return true;
    } catch (err) {
      return false;
    }
  }

  var storageAvailable = supportsLocalStorage();

  function readStoredLayout(productIds) {
    if (!storageAvailable) return {};

    var allowed = {};
    productIds.forEach(function (product) {
      if (product && typeof product.id !== 'undefined' && product.id !== null) {
        allowed[String(product.id)] = true;
      }
    });

    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return {};

      var filtered = {};
      Object.keys(parsed).forEach(function (key) {
        if (allowed[key]) filtered[key] = parsed[key];
      });

      if (Object.keys(filtered).length !== Object.keys(parsed).length) {
        scheduleLayoutWrite(filtered);
      }

      return filtered;
    } catch (err) {
      console.warn('Unable to read stored product canvas layout', err);
      return {};
    }
  }

  var pendingLayout;

  // Persist RAW object transforms only (no viewport math)
  function collectPersistableObjects(canvas) {
    var layout = {};
    if (!canvas) return layout;

    canvas.getObjects().forEach(function (obj) {
      if (obj && obj.productId !== undefined && obj.productId !== null) {
        var key = String(obj.productId);

        var left   = Number(obj.left);
        var top    = Number(obj.top);
        var scaleX = Number(obj.scaleX);
        var scaleY = Number(obj.scaleY);

        if (!isFinite(left))   left = 0;
        if (!isFinite(top))    top = 0;
        if (!isFinite(scaleX) || scaleX <= 0) scaleX = 1;
        if (!isFinite(scaleY) || scaleY <= 0) scaleY = scaleX;

        layout[key] = { left: left, top: top, scaleX: scaleX, scaleY: scaleY };
      }
    });

    return layout;
  }

  function scheduleLayoutWrite(layout) {
    if (!storageAvailable) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout || {}));
    } catch (err) {
      console.warn('Unable to persist product canvas layout', err);
    }
  }

  function schedulePersist(canvas) {
    if (!storageAvailable) return;
    if (pendingLayout) return;

    pendingLayout = window.requestAnimationFrame(function () {
      pendingLayout = null;
      var layout = collectPersistableObjects(canvas);
      scheduleLayoutWrite(layout);
    });
  }

  function applyCanvasSize(canvas, wrapper) {
    if (!canvas || !wrapper) return;

    var width = window.innerWidth || wrapper.clientWidth || 0;
    var header = document.querySelector('header');
    var headerHeight = header ? header.offsetHeight : 0;
    var height = window.innerHeight ? window.innerHeight - headerHeight : wrapper.clientHeight;

    if (!width) width = wrapper.clientWidth || 960;
    if (!height || height < 320) height = Math.max(window.innerHeight - headerHeight, 480);

    wrapper.style.height = height + 'px';
    canvas.setWidth(width);
    canvas.setHeight(height);
    canvas.renderAll();
  }

  function pointerFromEvent(canvas, evt) {
    if (!canvas || !evt) return new fabric.Point(0, 0);
    var rect = canvas.getElement().getBoundingClientRect();
    var x = evt.clientX - rect.left;
    var y = evt.clientY - rect.top;
    return new fabric.Point(x, y);
  }

  function gridPosition(index, canvasWidth, itemSize, gap) {
    var columns = Math.max(Math.floor((canvasWidth - gap) / (itemSize + gap)), 1);
    var column = index % columns;
    var row = Math.floor(index / columns);
    var left = gap + column * (itemSize + gap);
    var top = gap + row * (itemSize + gap);
    return { left: left, top: top };
  }

  ready(function () {
    if (typeof fabric === 'undefined' || !fabric.Canvas) {
      console.warn('Fabric.js is required for the product canvas');
      return;
    }

    var wrapper = document.getElementById('product-canvas-wrapper');
    var canvasElement = document.getElementById('product-canvas');
    if (!wrapper || !canvasElement) return;

    var products = parseProducts(wrapper).filter(function (product) {
      return product && product.photoUrl;
    });

    // Fabric canvas with lasso selection by default (pan with Space/middle/right)
    var canvas = new fabric.Canvas(canvasElement, {
      selection: true
    });
    canvas.backgroundColor = '#ffffff';

    applyCanvasSize(canvas, wrapper);
    window.addEventListener('resize', function () {
      applyCanvasSize(canvas, wrapper);
    });

    // Zoom (Cmd/Ctrl + wheel) – do NOT persist on zoom
    var MIN_ZOOM = 0.01;
    var MAX_ZOOM = 4;
    var ZOOM_STEP = 0.1;

    wrapper.addEventListener(
      'wheel',
      function (event) {
        if (!(event.metaKey || event.ctrlKey)) return;
        event.preventDefault();

        var delta = event.deltaY;
        var zoom = canvas.getZoom();
        var zoomChange = 1 + (delta > 0 ? -ZOOM_STEP : ZOOM_STEP);
        var nextZoom = zoom * zoomChange;
        if (nextZoom < MIN_ZOOM) nextZoom = MIN_ZOOM;
        else if (nextZoom > MAX_ZOOM) nextZoom = MAX_ZOOM;

        var pointer = pointerFromEvent(canvas, event);
        canvas.zoomToPoint(pointer, nextZoom);
        canvas.requestRenderAll();
      },
      { passive: false }
    );

    var maxItemSize = 220;
    var gap = 40;

    var storedLayout = readStoredLayout(products);

    products.forEach(function (product, index) {
      fabric.Image.fromURL(
        product.photoUrl,
        function (img) {
          if (!img) return;

          var key = String(product.id);
          img.productId = key;

          var stored = storedLayout[key];

          // Position: stored or grid
          var position =
            stored && typeof stored.left === 'number' && typeof stored.top === 'number'
              ? { left: stored.left, top: stored.top }
              : gridPosition(index, canvas.getWidth(), maxItemSize, gap);

          // Choose ONE scale: prefer stored (clamped), else fallback based on natural size
          var fallbackScale = Math.min(maxItemSize / (img.width || 1), maxItemSize / (img.height || 1), 1) || 1;
          var useScale = fallbackScale;
          if (stored && typeof stored.scaleX === 'number' && stored.scaleX > 0) {
            var s = stored.scaleX;
            if (!isFinite(s) || s <= 0) s = fallbackScale;
            if (s < 0.05) s = 0.05;   // clamp tiny
            if (s > 5)    s = 5;      // clamp huge
            useScale = s;
          }

          img.set({
            left: position.left,
            top: position.top,
            originX: 'left',
            originY: 'top',
            hasBorders: false,
            hasControls: false,
            hoverCursor: 'move',
            moveCursor: 'move',
            selectable: true,
            lockScalingFlip: true
          });

          img.scaleX = useScale;
          img.scaleY = useScale;
          img.setCoords();

          canvas.add(img);
          canvas.requestRenderAll();
          // Do not persist here; wait for user interaction
        },
        { crossOrigin: 'anonymous' }
      );
    });

    // Persist ONLY on object changes (not on zoom)
    canvas.on('object:moving',   function () { schedulePersist(canvas); });
    canvas.on('object:scaling',  function () { schedulePersist(canvas); });
    canvas.on('object:modified', function () { schedulePersist(canvas); });

    // Pan with Space / middle / right mouse; otherwise lasso select
    var isPanning = false;
    var lastPos;
    var isSpacePressed = false;

    document.addEventListener('keydown', function (e) {
      if (e.code === 'Space') {
        isSpacePressed = true;
        canvas.defaultCursor = 'grab';
      }
    });

    document.addEventListener('keyup', function (e) {
      if (e.code === 'Space') {
        isSpacePressed = false;
        canvas.defaultCursor = 'default';
      }
    });

    canvas.on('mouse:down', function (event) {
      var e = event && event.e;
      if (e && (isSpacePressed || e.button === 1 || e.button === 2)) {
        isPanning = true;
        canvas.selection = false;
        lastPos = new fabric.Point(e.clientX, e.clientY);
        canvas.setCursor('grabbing');
        canvas.requestRenderAll();
      } else {
        canvas.selection = true; // allow lasso
      }
    });

    canvas.on('mouse:move', function (event) {
      if (!isPanning || !event || !event.e) return;
      var e = event.e;
      var currentPos = new fabric.Point(e.clientX, e.clientY);
      var delta = currentPos.subtract(lastPos);
      lastPos = currentPos;
      canvas.relativePan(delta);
      canvas.setCursor('grabbing');
      canvas.requestRenderAll();
    });

    canvas.on('mouse:up', function () {
      if (!isPanning) return;
      isPanning = false;
      canvas.selection = true;
      canvas.setCursor('default');
      canvas.requestRenderAll();
    });

    function groupActiveSelection() {
      var activeObject = canvas.getActiveObject();
      if (!activeObject || activeObject.type !== 'activeSelection') return;
      activeObject.toGroup();
      canvas.requestRenderAll();
      schedulePersist(canvas);
    }

    function ungroupActiveGroup() {
      var activeObject = canvas.getActiveObject();
      if (!activeObject || activeObject.type !== 'group') return;
      activeObject.toActiveSelection();
      canvas.requestRenderAll();
      schedulePersist(canvas);
    }

    document.addEventListener('keydown', function (event) {
      if (!event) return;

      var key = event.key || event.code;
      var isMeta = event.metaKey || event.ctrlKey;
      if (!isMeta) return;

      if ((key === 'g' || key === 'G' || key === 'KeyG') && event.shiftKey) {
        event.preventDefault();
        ungroupActiveGroup();
      } else if (key === 'g' || key === 'G' || key === 'KeyG') {
        event.preventDefault();
        groupActiveSelection();
      }
    });

  });
})();
