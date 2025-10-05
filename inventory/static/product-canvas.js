(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') {
      fn();
    } else {
      document.addEventListener('DOMContentLoaded', fn);
    }
  }

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

    products.forEach(function (product, index) {
      fabric.Image.fromURL(
        product.photoUrl,
        function (img) {
          if (!img) {
            return;
          }

          var scale = Math.min(maxItemSize / img.width, maxItemSize / img.height, 1);
          img.scale(scale);

          var position = gridPosition(index, canvas.getWidth(), maxItemSize, gap);
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

          canvas.add(img);
          canvas.requestRenderAll();
        },
        { crossOrigin: 'anonymous' }
      );
    });
  });
})();
