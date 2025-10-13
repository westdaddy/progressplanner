(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') {
      fn();
    } else {
      document.addEventListener('DOMContentLoaded', fn);
    }
  }

  var STORAGE_PREFIX = 'inventory.product_canvas.layout';
  var STORAGE_KEY = STORAGE_PREFIX;
  var layoutEndpoint = null;
  var SERVER_SAVE_DELAY = 2000;
  var serverSaveTimer = null;
  var pendingServerLayout = null;
  var csrfToken = null;
  var customStorageKey = null;
  var pendingCustomPersist = null;
  var isRestoringCustomObjects = false;
  var activeDrawingTool = null;
  var lineInProgress = null;
  var toolbarElement = null;
  var toolbarButtons = {};
  var isSpacePressed = false;

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

  function getCsrfToken() {
    if (csrfToken) return csrfToken;
    var cookie = document.cookie || '';
    var match = cookie.match(/csrftoken=([^;]+)/);
    if (match) {
      csrfToken = decodeURIComponent(match[1]);
    }
    return csrfToken;
  }

  function parseConfig(wrapper) {
    if (!wrapper) return {};
    var raw = wrapper.getAttribute('data-config');
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch (err) {
      console.warn('Unable to parse product canvas config', err);
      return {};
    }
  }

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

  function fetchStoredLayout(productIds) {
    var localLayout = readStoredLayout(productIds);
    if (!layoutEndpoint) {
      return Promise.resolve(localLayout);
    }

    return fetch(layoutEndpoint, { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Unexpected response');
        }
        return response.json();
      })
      .then(function (payload) {
        if (payload && typeof payload.layout === 'object') {
          scheduleLayoutWrite(payload.layout);
          return Object.assign({}, localLayout, payload.layout);
        }
        return localLayout;
      })
      .catch(function (error) {
        console.warn('Unable to fetch stored product canvas layout', error);
        return localLayout;
      });
  }

  var pendingLayout;

  // Persist RAW object transforms only (no viewport math)
  function collectPersistableObjects(canvas) {
    var layout = {};
    if (!canvas) return layout;

    function normalisePosition(obj) {
      if (!obj) return { left: 0, top: 0 };

      if (typeof obj.getPointByOrigin === 'function') {
        try {
          var point = obj.getPointByOrigin('left', 'top');
          if (point && typeof point.x === 'number' && typeof point.y === 'number') {
            return { left: point.x, top: point.y };
          }
        } catch (err) {
          // Fallback to raw properties below.
        }
      }

      var fallbackLeft = Number(obj.left);
      var fallbackTop = Number(obj.top);

      if (!isFinite(fallbackLeft)) fallbackLeft = 0;
      if (!isFinite(fallbackTop)) fallbackTop = 0;

      return { left: fallbackLeft, top: fallbackTop };
    }

    function normaliseScale(obj) {
      if (!obj) return { scaleX: 1, scaleY: 1 };

      if (typeof obj.getObjectScaling === 'function') {
        var scaling = obj.getObjectScaling();
        if (scaling && typeof scaling.scaleX === 'number' && typeof scaling.scaleY === 'number') {
          var scaleX = scaling.scaleX;
          var scaleY = scaling.scaleY;
          if (isFinite(scaleX) && scaleX > 0 && isFinite(scaleY) && scaleY > 0) {
            return { scaleX: scaleX, scaleY: scaleY };
          }
        }
      }

      var fallbackScaleX = Number(obj.scaleX);
      var fallbackScaleY = Number(obj.scaleY);

      if (!isFinite(fallbackScaleX) || fallbackScaleX <= 0) fallbackScaleX = 1;
      if (!isFinite(fallbackScaleY) || fallbackScaleY <= 0) fallbackScaleY = fallbackScaleX;

      return { scaleX: fallbackScaleX, scaleY: fallbackScaleY };
    }

    function collectFromObject(obj) {
      if (!obj) return;

      if (obj.type === 'group' && typeof obj.forEachObject === 'function') {
        obj.forEachObject(collectFromObject);
        return;
      }

      if (obj.productId === undefined || obj.productId === null) return;

      var key = String(obj.productId);
      var position = normalisePosition(obj);
      var scale = normaliseScale(obj);

      var left = Number(position.left);
      var top = Number(position.top);
      var scaleX = Number(scale.scaleX);
      var scaleY = Number(scale.scaleY);

      if (!isFinite(left)) left = 0;
      if (!isFinite(top)) top = 0;
      if (!isFinite(scaleX) || scaleX <= 0) scaleX = 1;
      if (!isFinite(scaleY) || scaleY <= 0) scaleY = scaleX;

      layout[key] = { left: left, top: top, scaleX: scaleX, scaleY: scaleY };
    }

    canvas.getObjects().forEach(collectFromObject);

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

  function sendLayoutToServer(layout) {
    if (!layoutEndpoint) return;

    var headers = { 'Content-Type': 'application/json' };
    var token = getCsrfToken();
    if (token) headers['X-CSRFToken'] = token;

    fetch(layoutEndpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: headers,
      body: JSON.stringify({ layout: layout || {} })
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Unexpected response');
        }
      })
      .catch(function (error) {
        console.warn('Unable to persist product canvas layout to server', error);
      });
  }

  function scheduleServerLayoutSave(layout) {
    if (!layoutEndpoint) return;

    pendingServerLayout = layout;
    if (serverSaveTimer) return;

    serverSaveTimer = window.setTimeout(function () {
      serverSaveTimer = null;
      var payload = pendingServerLayout;
      pendingServerLayout = null;
      if (!payload) return;
      sendLayoutToServer(payload);
    }, SERVER_SAVE_DELAY);
  }

  function schedulePersist(canvas) {
    if (pendingLayout) return;

    pendingLayout = window.requestAnimationFrame(function () {
      pendingLayout = null;
      var layout = collectPersistableObjects(canvas);
      scheduleLayoutWrite(layout);
      scheduleServerLayoutSave(layout);
    });
  }

  function generateCustomId() {
    return (
      'custom-' +
      Date.now().toString(36) +
      '-' +
      Math.random().toString(36).slice(2, 8)
    );
  }

  function readStoredCustomObjects() {
    if (!storageAvailable || !customStorageKey) return [];

    try {
      var raw = window.localStorage.getItem(customStorageKey);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      console.warn('Unable to read product canvas custom objects', err);
      return [];
    }
  }

  function writeStoredCustomObjects(objects) {
    if (!storageAvailable || !customStorageKey) return;

    try {
      window.localStorage.setItem(
        customStorageKey,
        JSON.stringify(Array.isArray(objects) ? objects : [])
      );
    } catch (err) {
      console.warn('Unable to persist product canvas custom objects', err);
    }
  }

  function collectCustomObjects(canvas) {
    if (!canvas) return [];

    return canvas
      .getObjects()
      .filter(function (obj) {
        return obj && obj.isCustom;
      })
      .map(function (obj) {
        return obj.toObject(['customId', 'isCustom', 'customType']);
      });
  }

  function scheduleCustomPersist(canvas) {
    if (!storageAvailable || !customStorageKey) return;
    if (pendingCustomPersist) return;

    pendingCustomPersist = window.requestAnimationFrame(function () {
      pendingCustomPersist = null;
      var objects = collectCustomObjects(canvas);
      writeStoredCustomObjects(objects);
    });
  }

  function registerCustomObject(obj) {
    if (!obj) return obj;

    if (!obj.customId) {
      obj.customId = generateCustomId();
    }

    obj.isCustom = true;
    obj.set({
      lockScalingFlip: true,
      hasBorders: true,
      hasControls: true,
      perPixelTargetFind: true,
      selectable: true,
      evented: true
    });

    if (typeof obj.setCoords === 'function') {
      obj.setCoords();
    }

    return obj;
  }

  function restoreCustomObjects(canvas) {
    if (!canvas) return;

    var stored = readStoredCustomObjects();
    if (!stored.length) return;

    isRestoringCustomObjects = true;
    fabric.util.enlivenObjects(stored, function (objects) {
      objects.forEach(function (obj) {
        registerCustomObject(obj);
        canvas.add(obj);
      });
      isRestoringCustomObjects = false;
      canvas.requestRenderAll();
    });
  }

  function refreshToolbarState() {
    if (!toolbarElement) return;
    Object.keys(toolbarButtons).forEach(function (key) {
      var button = toolbarButtons[key];
      if (!button) return;
      if (key === activeDrawingTool) {
        button.classList.add('is-active');
      } else {
        button.classList.remove('is-active');
      }
    });
  }

  function refreshCanvasCursor(canvas) {
    if (!canvas) return;
    if (isSpacePressed) {
      canvas.defaultCursor = 'grab';
    } else if (activeDrawingTool === 'line') {
      canvas.defaultCursor = 'crosshair';
    } else {
      canvas.defaultCursor = 'default';
    }
  }

  function setDrawingTool(canvas, tool) {
    var nextTool = activeDrawingTool === tool ? null : tool;
    activeDrawingTool = nextTool;

    if (canvas) {
      if (nextTool !== 'line' && lineInProgress) {
        canvas.remove(lineInProgress);
        lineInProgress = null;
      }

      canvas.discardActiveObject();
      canvas.selection = !activeDrawingTool;
      refreshCanvasCursor(canvas);
      canvas.requestRenderAll();
    }

    refreshToolbarState();
  }

  function addCustomTextbox(canvas) {
    if (!canvas) return;

    var center = canvas.getCenter();
    var textbox = new fabric.Textbox('Add notes…', {
      left: center.left - 100,
      top: center.top - 30,
      width: 220,
      fontSize: 24,
      fontWeight: 500,
      fill: '#1f1f1f',
      backgroundColor: 'rgba(255, 255, 255, 0.85)',
      editingBorderColor: '#4285f4',
      cornerStyle: 'circle',
      cornerColor: '#4285f4',
      borderColor: '#4285f4',
      padding: 6
    });

    textbox.customType = 'textbox';
    registerCustomObject(textbox);
    canvas.add(textbox);
    canvas.setActiveObject(textbox);
    canvas.requestRenderAll();
    textbox.enterEditing();
    textbox.selectAll();
    scheduleCustomPersist(canvas);
  }

  function addHighlight(canvas) {
    if (!canvas) return;

    var padding = 20;
    var activeObject = canvas.getActiveObject();
    var left = canvas.getWidth() / 2 - 120;
    var top = canvas.getHeight() / 2 - 80;
    var width = 240;
    var height = 160;

    if (activeObject) {
      var bounds = activeObject.getBoundingRect(true, true);
      left = bounds.left - padding;
      top = bounds.top - padding;
      width = bounds.width + padding * 2;
      height = bounds.height + padding * 2;
    }

    var highlight = new fabric.Rect({
      left: left,
      top: top,
      width: width,
      height: height,
      rx: 12,
      ry: 12,
      fill: 'rgba(66, 133, 244, 0.14)',
      stroke: '#4285f4',
      strokeWidth: 2,
      strokeUniform: true,
      customType: 'highlight'
    });

    registerCustomObject(highlight);
    canvas.add(highlight);
    canvas.setActiveObject(highlight);
    highlight.bringToFront();
    canvas.requestRenderAll();
    scheduleCustomPersist(canvas);
  }

  function beginLineDrawing(canvas, pointer) {
    if (!canvas || !pointer) return;

    var line = new fabric.Line([pointer.x, pointer.y, pointer.x, pointer.y], {
      stroke: '#212121',
      strokeWidth: 4,
      strokeLineCap: 'round',
      strokeLineJoin: 'round',
      selectable: true,
      hasControls: true,
      customType: 'line'
    });

    registerCustomObject(line);
    lineInProgress = line;
    line._isDraft = true;
    canvas.add(line);
    canvas.setActiveObject(line);
    canvas.requestRenderAll();
  }

  function updateDraftLine(canvas, pointer) {
    if (!canvas || !lineInProgress || !pointer) return;

    lineInProgress.set({ x2: pointer.x, y2: pointer.y });
    lineInProgress.setCoords();
    canvas.requestRenderAll();
  }

  function finaliseLineDrawing(canvas, pointer) {
    if (!canvas || !lineInProgress) return;

    if (pointer) {
      lineInProgress.set({ x2: pointer.x, y2: pointer.y });
    }

    var x1 = lineInProgress.x1 || 0;
    var y1 = lineInProgress.y1 || 0;
    var x2 = lineInProgress.x2 || 0;
    var y2 = lineInProgress.y2 || 0;
    var length = Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2));

    if (!length || length < 6) {
      canvas.remove(lineInProgress);
    } else {
      delete lineInProgress._isDraft;
      scheduleCustomPersist(canvas);
    }

    lineInProgress = null;
    canvas.requestRenderAll();
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

    layoutEndpoint = wrapper.getAttribute('data-layout-url') || null;
    if (layoutEndpoint) {
      layoutEndpoint = layoutEndpoint.trim();
      if (!layoutEndpoint) layoutEndpoint = null;
    }

    var config = parseConfig(wrapper);
    var maxDimension = Number(config.maxDimension);
    if (!isFinite(maxDimension) || maxDimension <= 0) {
      maxDimension = 1000;
    }
    var storageVersion = config.storageVersion ? String(config.storageVersion) : 'v2';
    STORAGE_KEY = STORAGE_PREFIX + '.' + storageVersion;
    if (storageAvailable && STORAGE_KEY !== STORAGE_PREFIX) {
      try {
        window.localStorage.removeItem(STORAGE_PREFIX);
      } catch (err) {
        console.warn('Unable to clear legacy product canvas layout', err);
      }
    }

    customStorageKey = STORAGE_KEY + '.custom_objects';

    var products = parseProducts(wrapper).filter(function (product) {
      return product && product.photoUrl;
    });

    // Fabric canvas with lasso selection by default (pan with Space/middle/right)
    var canvas = new fabric.Canvas(canvasElement, {
      selection: true
    });
    canvas.backgroundColor = '#ffffff';
    refreshCanvasCursor(canvas);

    toolbarElement = document.getElementById('product-canvas-toolbar');
    if (toolbarElement) {
      toolbarButtons = {
        line: toolbarElement.querySelector('button[data-tool="line"]')
      };

      toolbarElement.addEventListener('click', function (event) {
        var button = event && event.target ? event.target.closest('button[data-tool]') : null;
        if (!button) return;

        var tool = button.getAttribute('data-tool');
        if (tool === 'text') {
          event.preventDefault();
          addCustomTextbox(canvas);
        } else if (tool === 'highlight') {
          event.preventDefault();
          addHighlight(canvas);
        } else if (tool === 'line') {
          event.preventDefault();
          setDrawingTool(canvas, 'line');
        }
      });

      refreshToolbarState();
    }

    var highlightedGroup = null;
    var GROUP_HIGHLIGHT_STYLE = {
      backgroundColor: 'rgba(66, 133, 244, 0.12)',
      borderColor: '#4285f4',
      borderDashArray: [6, 4]
    };
    var GROUP_HIGHLIGHT_PROPS = Object.keys(GROUP_HIGHLIGHT_STYLE).concat(['hasBorders']);

    function applyGroupHighlight(group) {
      if (!group) return;

      var original = {};
      GROUP_HIGHLIGHT_PROPS.forEach(function (prop) {
        original[prop] = group[prop];
      });
      group._originalHighlightStyles = original;

      var highlightValues = Object.assign({ hasBorders: true }, GROUP_HIGHLIGHT_STYLE);
      group.set(highlightValues);
    }

    function clearGroupHighlight(group) {
      if (!group) return;

      var original = group._originalHighlightStyles;
      if (!original) return;

      group.set(original);
      delete group._originalHighlightStyles;
    }

    function setHighlightedGroup(group) {
      if (highlightedGroup === group) return;

      if (highlightedGroup) {
        clearGroupHighlight(highlightedGroup);
      }

      highlightedGroup = group || null;

      if (highlightedGroup) {
        applyGroupHighlight(highlightedGroup);
      }

      canvas.requestRenderAll();
    }

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

    var baseScale = maxItemSize / maxDimension;
    if (!isFinite(baseScale) || baseScale <= 0) {
      baseScale = 0.22;
    }

    var pendingProducts = products.length;
    var customObjectsRestored = false;

    function maybeRestoreCustomObjects() {
      if (customObjectsRestored || pendingProducts > 0) return;
      customObjectsRestored = true;
      restoreCustomObjects(canvas);
    }

    if (!pendingProducts) {
      maybeRestoreCustomObjects();
    }

    fetchStoredLayout(products).then(function (storedLayout) {
      if (!products.length) {
        maybeRestoreCustomObjects();
        return;
      }

      products.forEach(function (product, index) {
        fabric.Image.fromURL(
          product.photoUrl,
          function (img) {
            pendingProducts -= 1;

            if (!img) {
              maybeRestoreCustomObjects();
              return;
            }

            var key = String(product.id);
            img.productId = key;

            var stored = storedLayout[key];

            // Position: stored or grid
            var position =
              stored && typeof stored.left === 'number' && typeof stored.top === 'number'
                ? { left: stored.left, top: stored.top }
                : gridPosition(index, canvas.getWidth(), maxItemSize, gap);

            // Force a consistent base scale per item
            var fallbackScale = baseScale;
            var useScale = fallbackScale;
            var shouldPersist = false;
            if (stored && typeof stored.scaleX === 'number') {
              var s = stored.scaleX;
              if (!isFinite(s) || s <= 0) {
                shouldPersist = true;
              } else {
                var deviation = Math.abs(s - fallbackScale);
                if (fallbackScale && deviation / fallbackScale <= 0.05) {
                  useScale = s;
                } else {
                  shouldPersist = true;
                }
              }
            } else if (stored && stored.scaleX !== undefined) {
              shouldPersist = true;
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
            if (shouldPersist) {
              schedulePersist(canvas);
            }

            maybeRestoreCustomObjects();
            // Normal persistence happens on user interaction events
          },
          { crossOrigin: 'anonymous' }
        );
      });
    });

    function handleObjectChange(event) {
      if (event && event.target && event.target.isCustom) {
        scheduleCustomPersist(canvas);
      }
      schedulePersist(canvas);
    }

    // Persist ONLY on object changes (not on zoom)
    canvas.on('object:moving', handleObjectChange);
    canvas.on('object:scaling', handleObjectChange);
    canvas.on('object:modified', handleObjectChange);
    canvas.on('object:added', function (event) {
      var target = event && event.target;
      if (target && target.isCustom && !target._isDraft && !isRestoringCustomObjects) {
        scheduleCustomPersist(canvas);
      }
    });
    canvas.on('object:removed', function (event) {
      var target = event && event.target;
      if (target && target.isCustom) {
        scheduleCustomPersist(canvas);
      }
    });
    canvas.on('text:changed', function (event) {
      var target = event && event.target;
      if (target && target.isCustom) {
        scheduleCustomPersist(canvas);
      }
    });

    // Pan with Space / middle / right mouse; otherwise lasso select
    var isPanning = false;
    var lastPos;

    function isInputLike(element) {
      if (!element) return false;
      var tagName = element.tagName ? element.tagName.toLowerCase() : '';
      return (
        tagName === 'input' ||
        tagName === 'textarea' ||
        tagName === 'select' ||
        element.isContentEditable === true
      );
    }

    document.addEventListener('keydown', function (e) {
      if (!e) return;
      if (e.code === 'Space') {
        if (isInputLike(e.target)) return;
        var activeObject = canvas.getActiveObject();
        if (activeObject && activeObject.isEditing) return;
        isSpacePressed = true;
        refreshCanvasCursor(canvas);
      }
    });

    document.addEventListener('keyup', function (e) {
      if (e && e.code === 'Space') {
        isSpacePressed = false;
        refreshCanvasCursor(canvas);
      }
    });

    canvas.on('mouse:down', function (event) {
      var e = event && event.e;

      if (activeDrawingTool === 'line' && e && e.button === 0 && !isSpacePressed) {
        var pointer = canvas.getPointer(e);
        beginLineDrawing(canvas, pointer);
        return;
      }

      if (e && (isSpacePressed || e.button === 1 || e.button === 2)) {
        isPanning = true;
        canvas.selection = false;
        lastPos = new fabric.Point(e.clientX, e.clientY);
        canvas.setCursor('grabbing');
        canvas.requestRenderAll();
      } else {
        canvas.selection = !activeDrawingTool;
      }
    });

    canvas.on('mouse:move', function (event) {
      if (lineInProgress && activeDrawingTool === 'line') {
        if (event && event.e) {
          var pointer = canvas.getPointer(event.e);
          updateDraftLine(canvas, pointer);
        }
        return;
      }

      if (!isPanning || !event || !event.e) return;
      var e = event.e;
      var currentPos = new fabric.Point(e.clientX, e.clientY);
      var delta = currentPos.subtract(lastPos);
      lastPos = currentPos;
      canvas.relativePan(delta);
      canvas.setCursor('grabbing');
      canvas.requestRenderAll();
    });

    canvas.on('mouse:up', function (event) {
      if (lineInProgress && activeDrawingTool === 'line') {
        var pointer = event && event.e ? canvas.getPointer(event.e) : null;
        finaliseLineDrawing(canvas, pointer);
      }

      if (!isPanning) {
        refreshCanvasCursor(canvas);
        return;
      }

      isPanning = false;
      canvas.selection = !activeDrawingTool;
      refreshCanvasCursor(canvas);
      canvas.requestRenderAll();
    });

    function updateGroupHighlightFromSelection() {
      var activeObject = canvas.getActiveObject();
      if (activeObject && activeObject.type === 'group') {
        setHighlightedGroup(activeObject);
      } else {
        setHighlightedGroup(null);
      }
    }

    canvas.on('selection:created', updateGroupHighlightFromSelection);
    canvas.on('selection:updated', updateGroupHighlightFromSelection);
    canvas.on('selection:cleared', function () {
      setHighlightedGroup(null);
    });

    function groupActiveSelection() {
      var activeObject = canvas.getActiveObject();
      if (!activeObject || activeObject.type !== 'activeSelection') return;
      var group = activeObject.toGroup();
      if (group) {
        canvas.setActiveObject(group);
        setHighlightedGroup(group);
      }
      canvas.requestRenderAll();
      schedulePersist(canvas);
    }

    function ungroupActiveGroup() {
      var activeObject = canvas.getActiveObject();
      if (!activeObject || activeObject.type !== 'group') return;
      setHighlightedGroup(null);
      activeObject.toActiveSelection();
      canvas.requestRenderAll();
      schedulePersist(canvas);
    }

    document.addEventListener('keydown', function (event) {
      if (!event) return;

      if (isInputLike(event.target)) return;

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

    document.addEventListener('keydown', function (event) {
      if (!event) return;

      if (isInputLike(event.target)) return;

      var key = event.key || event.code;

      if (key === 'Escape') {
        if (lineInProgress && canvas) {
          canvas.remove(lineInProgress);
          lineInProgress = null;
          canvas.requestRenderAll();
        }
        if (activeDrawingTool) {
          setDrawingTool(canvas, null);
        }
        return;
      }

      if (
        (key === 'Delete' || key === 'Backspace' || key === 'Del') &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey
      ) {
        var activeObject = canvas.getActiveObject();
        if (activeObject && activeObject.isCustom && !activeObject.isEditing) {
          event.preventDefault();
          canvas.remove(activeObject);
          canvas.discardActiveObject();
          canvas.requestRenderAll();
          scheduleCustomPersist(canvas);
        }
      }
    });

  });
})();
