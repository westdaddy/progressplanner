(function () {
  var CARD_WIDTH = 180;
  var CARD_HEIGHT = 200;
  var GRID_GAP = 20;
  var GRID_COLUMNS = 5;
  var STORAGE_KEY = 'inventory-product-canvas';
  var IMAGE_MAX_HEIGHT = 100;
  var IMAGE_MAX_WIDTH = CARD_WIDTH - 40;

  function getContainer() {
    return document.getElementById('product-canvas-container');
  }

  function parseProducts(container) {
    if (!container) {
      return [];
    }
    var payload = container.getAttribute('data-products');
    if (!payload) {
      return [];
    }
    try {
      return JSON.parse(payload);
    } catch (err) {
      console.error('Unable to parse product canvas payload', err);
      return [];
    }
  }

  function canvasSize(container) {
    var width = 960;
    var height = 600;

    if (container) {
      width = container.clientWidth || window.innerWidth * 0.9;
      height = container.clientHeight || 0;
    }

    if (!width) {
      width = window.innerWidth * 0.9;
    }
    if (!height) {
      height = Math.max(window.innerHeight * 0.6, 480);
    }

    return { width: width, height: height };
  }

  function createFabricCanvas(container) {
    var canvasElement = document.getElementById('product-canvas');
    if (!canvasElement) {
      return null;
    }

    var size = canvasSize(container);
    var canvas = new fabric.Canvas('product-canvas', {
      preserveObjectStacking: true,
      selection: true,
    });
    canvas.setWidth(size.width);
    canvas.setHeight(size.height);
    canvas.backgroundColor = '#fafafa';
    canvas.renderAll();

    return canvas;
  }

  function computeStartPosition(index) {
    var column = index % GRID_COLUMNS;
    var row = Math.floor(index / GRID_COLUMNS);
    var left = GRID_GAP + column * (CARD_WIDTH + GRID_GAP);
    var top = GRID_GAP + row * (CARD_HEIGHT + GRID_GAP);
    return { left: left, top: top };
  }

  function buildMetaLines(product) {
    var lines = [
      'SKU: ' + (product.productId || '—'),
      'Qty: ' + (product.totalInventory || 0),
    ];

    if (product.retailPrice) {
      lines.push('Retail: $' + product.retailPrice.toFixed(2));
    }
    if (product.lastOrderLabel) {
      lines.push(product.lastOrderLabel);
    }

    return lines;
  }

  function createTextBox(text, options) {
    var config = Object.assign(
      {
        width: CARD_WIDTH - 20,
        textAlign: 'center',
        originX: 'center',
        originY: 'center',
        editable: false,
        selectable: false,
        evented: false,
      },
      options || {}
    );
    return new fabric.Textbox(text, config);
  }

  function createProductCard(product, canvas) {
    var position = computeStartPosition(product.index || 0);
    var centerLeft = position.left + CARD_WIDTH / 2;
    var centerTop = position.top + CARD_HEIGHT / 2;

    var frame = new fabric.Rect({
      width: CARD_WIDTH,
      height: CARD_HEIGHT,
      fill: '#ffffff',
      stroke: '#26a69a',
      strokeWidth: 2,
      rx: 16,
      ry: 16,
      originX: 'center',
      originY: 'center',
      selectable: false,
      evented: false,
    });

    var group = new fabric.Group([frame], {
      left: centerLeft,
      top: centerTop,
      originX: 'center',
      originY: 'center',
      lockRotation: true,
      hasRotatingPoint: false,
      hoverCursor: 'move',
      cornerColor: '#26a69a',
      cornerStyle: 'circle',
      padding: 8,
    });

    group.productKey = 'product-' + product.id;
    group.set('startLeft', centerLeft);
    group.set('startTop', centerTop);
    group.set('startScaleX', 1);
    group.set('startScaleY', 1);
    group.set('data', { type: 'product-card', productId: product.id });

    if (group.controls && group.controls.mtr) {
      group.setControlsVisibility({ mtr: false });
    }

    var imageOrPlaceholder = createTextBox(
      product.photoUrl ? 'Loading image…' : 'No photo available',
      {
        fontSize: 14,
        fill: '#757575',
        top: -CARD_HEIGHT / 2 + 60,
        width: CARD_WIDTH - 30,
      }
    );
    group.addWithUpdate(imageOrPlaceholder);

    var title = createTextBox(product.name || 'Product', {
      fontSize: 16,
      fontWeight: 'bold',
      fill: '#004d40',
      top: CARD_HEIGHT / 2 - 60,
    });
    group.addWithUpdate(title);

    var meta = createTextBox(buildMetaLines(product).join('\n'), {
      fontSize: 12,
      fill: '#546e7a',
      lineHeight: 1.2,
      top: CARD_HEIGHT / 2 - 25,
    });
    group.addWithUpdate(meta);

    canvas.add(group);
    canvas.requestRenderAll();

    if (product.photoUrl) {
      fabric.Image.fromURL(
        product.photoUrl,
        function (img) {
          if (!img) {
            return;
          }

          var scale = Math.min(
            IMAGE_MAX_WIDTH / img.width,
            IMAGE_MAX_HEIGHT / img.height,
            1
          );

          img.set({
            originX: 'center',
            originY: 'center',
            top: -CARD_HEIGHT / 2 + 60,
            selectable: false,
            evented: false,
          });
          img.scale(scale);

          group.remove(imageOrPlaceholder);
          group.insertAt(img, 1, true);
          canvas.requestRenderAll();
        },
        { crossOrigin: 'anonymous' }
      );
    }

    return group;
  }

  function serializeLayout(canvas) {
    return canvas
      .getObjects()
      .filter(function (obj) {
        return obj.data && obj.data.type === 'product-card';
      })
      .map(function (obj) {
        return {
          id: obj.productKey,
          left: obj.left,
          top: obj.top,
          scaleX: obj.scaleX,
          scaleY: obj.scaleY,
        };
      });
  }

  function restoreLayout(canvas, layout) {
    var layoutMap = {};
    layout.forEach(function (item) {
      layoutMap[item.id] = item;
    });

    canvas.getObjects().forEach(function (obj) {
      if (!obj.data || obj.data.type !== 'product-card') {
        return;
      }
      var config = layoutMap[obj.productKey];
      if (!config) {
        return;
      }
      obj.set({
        left: config.left,
        top: config.top,
        scaleX: config.scaleX || 1,
        scaleY: config.scaleY || 1,
      });
      obj.setCoords();
    });
    canvas.requestRenderAll();
  }

  function clearLayout(canvas) {
    canvas.getObjects().forEach(function (obj) {
      if (!obj.data || obj.data.type !== 'product-card') {
        return;
      }
      obj.set({
        left: obj.startLeft || obj.left,
        top: obj.startTop || obj.top,
        scaleX: obj.startScaleX || 1,
        scaleY: obj.startScaleY || 1,
      });
      obj.setCoords();
    });
    canvas.requestRenderAll();
  }

  function exportAsImage(canvas) {
    var dataURL = canvas.toDataURL({ format: 'png', multiplier: 2 });
    var link = document.createElement('a');
    link.download = 'product-canvas.png';
    link.href = dataURL;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function resizeCanvas(canvas, container) {
    if (!canvas || !container) {
      return;
    }
    var size = canvasSize(container);
    canvas.setWidth(size.width);
    canvas.setHeight(size.height);
    canvas.renderAll();
  }

  function toast(message, classes) {
    if (window.M && M.toast) {
      M.toast({ html: message, classes: classes });
    } else {
      console.log(message);
    }
  }

  function ready(fn) {
    if (document.readyState !== 'loading') {
      fn();
    } else {
      document.addEventListener('DOMContentLoaded', fn);
    }
  }

  ready(function () {
    if (typeof fabric === 'undefined' || !fabric.Canvas) {
      console.warn('Fabric.js is required for the product canvas');
      return;
    }

    var container = getContainer();
    var products = parseProducts(container);
    if (!container || !products.length) {
      return;
    }

    var canvas = createFabricCanvas(container);
    if (!canvas) {
      return;
    }

    products.forEach(function (product) {
      createProductCard(product, canvas);
    });

    canvas.on('object:scaling', function (event) {
      var target = event.target;
      if (!target || !target.data || target.data.type !== 'product-card') {
        return;
      }
      var minScale = 0.5;
      if (target.scaleX < minScale) {
        target.scaleX = minScale;
      }
      if (target.scaleY < minScale) {
        target.scaleY = minScale;
      }
    });

    window.addEventListener('resize', function () {
      resizeCanvas(canvas, container);
    });

    var saveBtn = document.getElementById('save-layout');
    var loadBtn = document.getElementById('load-layout');
    var clearBtn = document.getElementById('clear-layout');
    var exportBtn = document.getElementById('export-layout');

    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        var layout = serializeLayout(canvas);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
        toast('Layout saved locally', 'teal');
      });
    }

    if (loadBtn) {
      loadBtn.addEventListener('click', function () {
        var payload = localStorage.getItem(STORAGE_KEY);
        if (!payload) {
          toast('No saved layout found', 'orange');
          return;
        }
        try {
          var layout = JSON.parse(payload);
          restoreLayout(canvas, layout);
          toast('Layout restored', 'teal');
        } catch (err) {
          console.error('Unable to restore layout', err);
          toast('Failed to load layout', 'red');
        }
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        localStorage.removeItem(STORAGE_KEY);
        clearLayout(canvas);
        toast('Layout cleared', 'grey darken-1');
      });
    }

    if (exportBtn) {
      exportBtn.addEventListener('click', function () {
        exportAsImage(canvas);
      });
    }
  });
})();
