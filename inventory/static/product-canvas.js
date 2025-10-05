(function () {
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

  function stageSize(container) {
    var width = container.offsetWidth || window.innerWidth * 0.9;
    var height = Math.max(window.innerHeight * 0.6, 480);
    return { width: width, height: height };
  }

  function createStage(container) {
    var size = stageSize(container);
    return new Konva.Stage({
      container: 'konva-stage',
      width: size.width,
      height: size.height,
    });
  }

  function createPlaceholder(group, text) {
    var placeholder = new Konva.Text({
      text: text,
      fontSize: 14,
      fill: '#757575',
      width: 140,
      height: 80,
      align: 'center',
      verticalAlign: 'middle',
      x: 0,
      y: 30,
    });
    group.add(placeholder);
  }

  function createProductNode(product, layer) {
    var startX = 30 + (product.index % 5) * 160;
    var startY = 30 + Math.floor(product.index / 5) * 160;

    var group = new Konva.Group({
      x: startX,
      y: startY,
      draggable: true,
      id: 'product-' + product.id,
    });

    group.setAttrs({ startX: startX, startY: startY });

    var frame = new Konva.Rect({
      width: 150,
      height: 150,
      fill: '#ffffff',
      stroke: '#26a69a',
      strokeWidth: 2,
      cornerRadius: 12,
      shadowBlur: 6,
      shadowOpacity: 0.1,
    });
    group.add(frame);

    var title = product.name || 'Product';
    var text = new Konva.Text({
      text: title,
      fontSize: 14,
      fontStyle: 'bold',
      fill: '#004d40',
      width: 140,
      x: 5,
      y: 110,
      align: 'center',
      listening: false,
    });

    var meta = new Konva.Text({
      text:
        'SKU: ' + (product.productId || '—') +
        '\nQty: ' + (product.totalInventory || 0),
      fontSize: 12,
      fill: '#546e7a',
      width: 140,
      x: 5,
      y: 130,
      align: 'center',
      listening: false,
    });

    group.add(text);
    group.add(meta);

    if (product.photoUrl) {
      var imageObj = new window.Image();
      imageObj.onload = function () {
        var ratio = Math.min(120 / imageObj.width, 80 / imageObj.height);
        var imageWidth = imageObj.width * ratio;
        var imageHeight = imageObj.height * ratio;
        var image = new Konva.Image({
          image: imageObj,
          width: imageWidth,
          height: imageHeight,
          x: (150 - imageWidth) / 2,
          y: 10 + (90 - imageHeight) / 2,
        });
        group.add(image);
        layer.draw();
      };
      imageObj.crossOrigin = 'anonymous';
      imageObj.src = product.photoUrl;
    } else {
      createPlaceholder(group, 'No photo');
    }

    layer.add(group);
    return group;
  }

  function attachTransformer(stage, layer) {
    var transformer = new Konva.Transformer({
      rotateEnabled: false,
      boundBoxFunc: function (oldBox, newBox) {
        if (newBox.width < 80 || newBox.height < 80) {
          return oldBox;
        }
        return newBox;
      },
    });
    layer.add(transformer);

    stage.on('click tap', function (e) {
      if (e.target === stage) {
        transformer.nodes([]);
        layer.draw();
        return;
      }
      var group = e.target.getParent();
      if (group) {
        transformer.nodes([group]);
        layer.draw();
      }
    });

    return transformer;
  }

  function serializeLayout(stage) {
    return stage.find('Group').map(function (group) {
      return {
        id: group.id(),
        x: group.x(),
        y: group.y(),
        scaleX: group.scaleX(),
        scaleY: group.scaleY(),
      };
    });
  }

  function restoreLayout(stage, layout) {
    var layoutMap = {};
    layout.forEach(function (item) {
      layoutMap[item.id] = item;
    });
    stage.find('Group').forEach(function (group) {
      var config = layoutMap[group.id()];
      if (!config) {
        return;
      }
      group.position({ x: config.x, y: config.y });
      if (config.scaleX && config.scaleY) {
        group.scale({ x: config.scaleX, y: config.scaleY });
      }
    });
    stage.batchDraw();
  }

  function exportAsImage(stage) {
    var dataURL = stage.toDataURL({ pixelRatio: 2 });
    var link = document.createElement('a');
    link.download = 'product-canvas.png';
    link.href = dataURL;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
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
    if (typeof Konva === 'undefined') {
      console.warn('Konva.js is required for the product canvas');
      return;
    }

    var container = getContainer();
    var products = parseProducts(container);
    if (!container || !products.length) {
      return;
    }

    var stage = createStage(container);
    var layer = new Konva.Layer();
    stage.add(layer);
    attachTransformer(stage, layer);

    products.forEach(function (product) {
      createProductNode(product, layer);
    });

    layer.draw();

    window.addEventListener('resize', function () {
      var size = stageSize(container);
      stage.size(size);
      stage.batchDraw();
    });

    var STORAGE_KEY = 'inventory-product-canvas';

    var saveBtn = document.getElementById('save-layout');
    var loadBtn = document.getElementById('load-layout');
    var clearBtn = document.getElementById('clear-layout');
    var exportBtn = document.getElementById('export-layout');

    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        var layout = serializeLayout(stage);
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
          restoreLayout(stage, layout);
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
        stage.find('Group').forEach(function (group) {
          var originalX = group.getAttr('startX') || 30;
          var originalY = group.getAttr('startY') || 30;
          group.position({ x: originalX, y: originalY });
          group.scale({ x: 1, y: 1 });
        });
        stage.batchDraw();
        toast('Layout cleared', 'grey darken-1');
      });
    }

    if (exportBtn) {
      exportBtn.addEventListener('click', function () {
        exportAsImage(stage);
      });
    }
  });
})();
