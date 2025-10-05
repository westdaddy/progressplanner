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
    if (!wrapper) {
      return [];
    }
    var raw = wrapper.getAttribute('data-products');
    if (!raw) {
      return [];
    }
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
    if (!storageAvailable) {
      return {};
    }

    var allowed = {};
    productIds.forEach(function (product) {
      if (product && typeof product.id !== 'undefined' && product.id !== null) {
        allowed[String(product.id)] = true;
      }
    });

    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return {};
      }
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') {
        return {};
      }

      var filtered = {};
      Object.keys(parsed).forEach(function (key) {
        if (allowed[key]) {
          filtered[key] = parsed[key];
        }
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

  function scheduleLayoutWrite(layout) {
    if (!storageAvailable) {
      return;
    }

    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout || {}));
    } catch (err) {
      console.warn('Unable to persist product canvas layout', err);
    }
  }

  function schedulePersist(canvas) {
    if (!storageAvailable) {
      return;
    }

    if (pendingLayout) {
      return;
    }

    pendingLayout = window.requestAnimationFrame(function () {
      pendingLayout = null;
      var layout = {};
      canvas.getObjects().forEach(function (obj) {
        if (!obj || typeof obj.productId === 'undefined' || obj.productId === null) {
          return;
        }

        var key = String(obj.productId);
        layout[key] = {
          left: typeof obj.left === 'number' ? obj.left : 0,
          top: typeof obj.top === 'number' ? obj.top : 0,
          scaleX: typeof obj.scaleX === 'number' ? obj.scaleX : 1,
          scaleY: typeof obj.scaleY === 'number' ? obj.scaleY : 1,
        };
      });

      scheduleLayoutWrite(layout);
    });
  }

  function applyCanvasSize(canvas, wrapper) {
    if (!canvas || !wrapper) {
      return;
    }

    var width = window.innerWidth || wrapper.clientWidth || 0;
    var header = document.querySelector('header');
    var headerHeight = header ? header.offsetHeight : 0;
    var height = window.innerHeight ? window.innerHeight - headerHeight : wrapper.clientHeight;

    if (!width) {
      width = wrapper.clientWidth || 960;
    }
    if (!height || height < 320) {
      height = Math.max(window.innerHeight - headerHeight, 480);
    }

    wrapper.style.height = height + 'px';
    canvas.setWidth(width);
    canvas.setHeight(height);
    canvas.renderAll();
  }

  function pointerFromEvent(canvas, evt) {
    if (!canvas || !evt) {
      return new fabric.Point(0, 0);
    }

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
    if (!wrapper || !canvasElement) {
      return;
    }

    var products = parseProducts(wrapper).filter(function (product) {
      return product && product.photoUrl;
    });

    var canvas = new fabric.Canvas(canvasElement, {
      selection: false,
    });
    canvas.backgroundColor = '#ffffff';

    applyCanvasSize(canvas, wrapper);
    window.addEventListener('resize', function () {
      applyCanvasSize(canvas, wrapper);
    });

    var MIN_ZOOM = 0.25;
    var MAX_ZOOM = 4;
    var ZOOM_STEP = 0.1;

    wrapper.addEventListener(
      'wheel',
      function (event) {
        if (!event.metaKey) {
          return;
        }

        event.preventDefault();

        var delta = event.deltaY;
        var zoom = canvas.getZoom();
        var zoomChange = 1 + (delta > 0 ? -ZOOM_STEP : ZOOM_STEP);
        var nextZoom = zoom * zoomChange;
        if (nextZoom < MIN_ZOOM) {
          nextZoom = MIN_ZOOM;
        } else if (nextZoom > MAX_ZOOM) {
          nextZoom = MAX_ZOOM;
        }

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
          if (!img) {
            return;
          }

          var scale = Math.min(maxItemSize / img.width, maxItemSize / img.height, 1);
          img.scale(scale);

          var key = String(product.id);
          img.productId = key;

          var stored = storedLayout[key];
          var position = stored && typeof stored.left === 'number' && typeof stored.top === 'number'
            ? { left: stored.left, top: stored.top }
            : gridPosition(index, canvas.getWidth(), maxItemSize, gap);

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
            lockScalingFlip: true,
          });

          if (stored) {
            if (typeof stored.scaleX === 'number' && stored.scaleX > 0) {
              img.scaleX = stored.scaleX;
            }
            if (typeof stored.scaleY === 'number' && stored.scaleY > 0) {
              img.scaleY = stored.scaleY;
            }
          }

          img.setCoords();

          canvas.add(img);
          canvas.requestRenderAll();
          schedulePersist(canvas);
        },
        { crossOrigin: 'anonymous' }
      );
    });

    canvas.on('object:modified', function () {
      schedulePersist(canvas);
    });
  });
})();
