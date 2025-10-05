(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') {
      fn();
    } else {
      document.addEventListener('DOMContentLoaded', fn);
    }
  }

  var STORAGE_KEY = 'inventory.product_canvas.layout';
  var MIN_ZOOM = 0.25;
  var MAX_ZOOM = 4;
  var ZOOM_STEP = 0.1;

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

  function isFiniteNumber(value) {
    return typeof value === 'number' && !isNaN(value) && isFinite(value);
  }

  function clampZoom(value) {
    var zoom = parseFloat(value);
    if (!isFinite(zoom) || zoom <= 0) {
      return null;
    }
    if (zoom < MIN_ZOOM) {
      return MIN_ZOOM;
    }
    if (zoom > MAX_ZOOM) {
      return MAX_ZOOM;
    }
    return zoom;
  }

  function sanitizeViewport(viewport) {
    var zoom = clampZoom(viewport && viewport.zoom);
    if (zoom === null) {
      zoom = 1;
    }
    var x = viewport && isFiniteNumber(Number(viewport.x)) ? Number(viewport.x) : 0;
    var y = viewport && isFiniteNumber(Number(viewport.y)) ? Number(viewport.y) : 0;
    return { zoom: zoom, x: x, y: y };
  }

  function viewportEquals(source, target) {
    if (!source && !target) {
      return true;
    }
    if (!source || !target) {
      return false;
    }
    var left = sanitizeViewport(source);
    var right = sanitizeViewport(target);
    return (
      Math.abs(left.zoom - right.zoom) < 1e-6 &&
      Math.abs(left.x - right.x) < 1e-3 &&
      Math.abs(left.y - right.y) < 1e-3
    );
  }

  function sanitizeObjectEntry(entry) {
    if (!entry || typeof entry !== 'object') {
      return null;
    }

    var left = Number(entry.left);
    var top = Number(entry.top);
    if (!isFinite(left) || !isFinite(top)) {
      return null;
    }

    var scaleX = Number(entry.scaleX);
    var scaleY = Number(entry.scaleY);
    if (!isFinite(scaleX) || scaleX <= 0) {
      scaleX = 1;
    }
    if (!isFinite(scaleY) || scaleY <= 0) {
      scaleY = scaleX;
    }

    return {
      left: left,
      top: top,
      scaleX: scaleX,
      scaleY: scaleY,
    };
  }

  function scheduleLayoutWrite(layout) {
    if (!storageAvailable) {
      return;
    }

    try {
      var payload = layout && typeof layout === 'object' ? layout : {};
      var objects = payload.objects && typeof payload.objects === 'object' ? payload.objects : {};
      var groups = Array.isArray(payload.groups) ? payload.groups : [];
      var viewport = payload.viewport ? sanitizeViewport(payload.viewport) : null;

      var serialized = { objects: objects, groups: groups };
      if (viewport) {
        serialized.viewport = viewport;
      }

      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(serialized));
    } catch (err) {
      console.warn('Unable to persist product canvas layout', err);
    }
  }

  function readStoredLayout(productIds) {
    if (!storageAvailable) {
      return { objects: {}, groups: [], viewport: null };
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
        return { objects: {}, groups: [], viewport: null };
      }
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') {
        return { objects: {}, groups: [], viewport: null };
      }

      var storedObjects;
      var storedGroups = [];
      var storedViewport = null;
      if (parsed.objects && typeof parsed.objects === 'object') {
        storedObjects = parsed.objects;
        if (Array.isArray(parsed.groups)) {
          storedGroups = parsed.groups;
        }
        if (parsed.viewport && typeof parsed.viewport === 'object') {
          storedViewport = parsed.viewport;
        }
      } else {
        storedObjects = parsed;
      }

      var filteredObjects = {};
      var objectsChanged = false;
      Object.keys(storedObjects).forEach(function (key) {
        if (!allowed[key]) {
          objectsChanged = true;
          return;
        }
        var sanitized = sanitizeObjectEntry(storedObjects[key]);
        if (sanitized) {
          filteredObjects[key] = sanitized;
          if (sanitized !== storedObjects[key]) {
            objectsChanged = true;
          }
        } else {
          objectsChanged = true;
        }
      });

      var filteredGroups = [];
      var groupsChanged = false;
      storedGroups.forEach(function (group) {
        if (!group || !Array.isArray(group.members)) {
          groupsChanged = true;
          return;
        }

        var filteredMembers = group.members
          .map(function (member) {
            return String(member);
          })
          .filter(function (member) {
            return allowed[member];
          });

        if (filteredMembers.length >= 2) {
          var canonicalMembers = filteredMembers.slice().sort();
          filteredGroups.push({ members: canonicalMembers });

          var sameSize = canonicalMembers.length === group.members.length;
          var sameOrder =
            sameSize &&
            canonicalMembers.every(function (member, index) {
              return String(group.members[index]) === member;
            });

          if (!sameSize || !sameOrder) {
            groupsChanged = true;
          }
        } else {
          groupsChanged = true;
        }
      });

      var viewport = null;
      var viewportChanged = false;
      if (storedViewport) {
        viewport = sanitizeViewport(storedViewport);
        viewportChanged = !viewportEquals(storedViewport, viewport);
      }

      if (objectsChanged || groupsChanged || viewportChanged) {
        scheduleLayoutWrite({
          objects: filteredObjects,
          groups: filteredGroups,
          viewport: viewport,
        });
      }

      return { objects: filteredObjects, groups: filteredGroups, viewport: viewport };
    } catch (err) {
      console.warn('Unable to read stored product canvas layout', err);
      return { objects: {}, groups: [], viewport: null };
    }
  }

  function collectPersistableObjects(canvas) {
    var layout = { objects: {}, groups: [] };
    if (!canvas) {
      return layout;
    }

    var vpt = canvas.viewportTransform ? canvas.viewportTransform.slice() : null;
    var invertedVpt = vpt && fabric.util && fabric.util.invertTransform ? fabric.util.invertTransform(vpt) : null;
    var zoom = canvas.getZoom ? canvas.getZoom() : 1;

    layout.viewport = sanitizeViewport({
      zoom: zoom || 1,
      x: vpt && vpt.length > 4 ? vpt[4] : 0,
      y: vpt && vpt.length > 5 ? vpt[5] : 0,
    });

    function recordObject(obj) {
      if (!obj) {
        return;
      }

      if (obj.productId !== undefined && obj.productId !== null) {
        var key = String(obj.productId);

        var bounds = typeof obj.getBoundingRect === 'function' ? obj.getBoundingRect(true, true) : null;
        var point;
        if (bounds) {
          point = new fabric.Point(bounds.left, bounds.top);
          if (invertedVpt) {
            point = fabric.util.transformPoint(point, invertedVpt);
          }
        } else {
          point = new fabric.Point(obj.left || 0, obj.top || 0);
        }

        if (!isFinite(point.x) || !isFinite(point.y)) {
          return;
        }

        var scaleX = typeof obj.scaleX === 'number' && isFinite(obj.scaleX) && obj.scaleX > 0 ? obj.scaleX : 1;
        var scaleY = typeof obj.scaleY === 'number' && isFinite(obj.scaleY) && obj.scaleY > 0 ? obj.scaleY : scaleX;

        layout.objects[key] = {
          left: point.x,
          top: point.y,
          scaleX: scaleX,
          scaleY: scaleY,
        };
      }

      if (obj._objects && obj._objects.length) {
        obj._objects.forEach(function (child) {
          recordObject(child);
        });
      }
    }

    var seenGroups = {};

    canvas.getObjects().forEach(function (obj) {
      if (obj && obj.type === 'group' && obj._objects && obj._objects.length) {
        var members = obj._objects
          .map(function (child) {
            if (child && child.productId !== undefined && child.productId !== null) {
              return String(child.productId);
            }
            return null;
          })
          .filter(function (value) {
            return value !== null;
          });

        if (members.length >= 2) {
          var canonical = members.slice().sort();
          var key = canonical.join('::');
          if (!seenGroups[key]) {
            seenGroups[key] = true;
            layout.groups.push({ members: canonical });
          }
        }
      }

      recordObject(obj);
    });

    return layout;
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
      height = Math.max((window.innerHeight || 0) - headerHeight, 480);
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

    var element = canvas.getElement ? canvas.getElement() : canvas.upperCanvasEl;
    var rect = element ? element.getBoundingClientRect() : { left: 0, top: 0 };
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

    var storedLayout = readStoredLayout(products);
    var storedObjects = storedLayout.objects || {};
    var storedGroups = storedLayout.groups || [];
    var storedViewport = storedLayout.viewport || null;

    var canvas = new fabric.Canvas(canvasElement, {
      selection: true,
      preserveObjectStacking: true,
    });
    canvas.backgroundColor = '#ffffff';

    var pendingLayout = null;

    function schedulePersist() {
      if (!storageAvailable) {
        return;
      }
      if (pendingLayout) {
        return;
      }

      pendingLayout = window.requestAnimationFrame(function () {
        pendingLayout = null;
        var layout = collectPersistableObjects(canvas);
        scheduleLayoutWrite(layout);
        if (layout.viewport) {
          storedViewport = layout.viewport;
        }
      });
    }

    applyCanvasSize(canvas, wrapper);
    restoreViewportFromStorage();

    window.addEventListener('resize', function () {
      applyCanvasSize(canvas, wrapper);
      restoreViewportFromStorage();
      schedulePersist();
    });

    wrapper.addEventListener(
      'wheel',
      function (event) {
        if (!(event.metaKey || event.ctrlKey)) {
          return;
        }

        event.preventDefault();

        var zoom = canvas.getZoom();
        var zoomChange = event.deltaY > 0 ? 1 - ZOOM_STEP : 1 + ZOOM_STEP;
        var nextZoom = clampZoom(zoom * zoomChange) || zoom;

        var pointer = pointerFromEvent(canvas, event);
        canvas.zoomToPoint(pointer, nextZoom);
        canvas.requestRenderAll();
        schedulePersist();
      },
      { passive: false }
    );

    var maxItemSize = 220;
    var gap = 40;
    var productNodes = {};
    var pendingGroupRestore = null;

    products.forEach(function (product, index) {
      fabric.Image.fromURL(
        product.photoUrl,
        function (img) {
          if (!img) {
            return;
          }

          var fallbackScale = 1;
          if (img.width && img.height) {
            fallbackScale = Math.min(maxItemSize / img.width, maxItemSize / img.height, 1);
            if (!isFinite(fallbackScale) || fallbackScale <= 0) {
              fallbackScale = 1;
            }
          }

          img.scale(fallbackScale);

          var key = String(product.id);
          img.productId = key;

          var stored = storedObjects[key];
          var initialPosition = stored
            ? { left: stored.left, top: stored.top }
            : gridPosition(index, canvas.getWidth(), maxItemSize, gap);

          img.set({
            left: initialPosition.left,
            top: initialPosition.top,
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
            img.scaleX = stored.scaleX;
            img.scaleY = stored.scaleY;
          }

          img.setCoords();

          canvas.add(img);
          canvas.requestRenderAll();
          productNodes[key] = img;
          schedulePersist();
          queueGroupRestore();
        },
        { crossOrigin: 'anonymous' }
      );
    });

    canvas.on('object:modified', schedulePersist);
    canvas.on('object:moving', schedulePersist);
    canvas.on('object:scaling', schedulePersist);
    canvas.on('object:rotating', schedulePersist);

    var isPanning = false;
    var lastPos;
    var isSpacePressed = false;

    document.addEventListener('keydown', function (event) {
      if (event.code === 'Space') {
        event.preventDefault();
        isSpacePressed = true;
        canvas.defaultCursor = 'grab';
      }
    });

    document.addEventListener('keyup', function (event) {
      if (event.code === 'Space') {
        event.preventDefault();
        isSpacePressed = false;
        canvas.defaultCursor = 'default';
      }
    });

    canvas.on('mouse:down', function (event) {
      if (event && event.e && !event.target && (isSpacePressed || event.e.button === 1 || event.e.button === 2)) {
        isPanning = true;
        canvas.selection = false;
        lastPos = new fabric.Point(event.e.clientX, event.e.clientY);
        canvas.setCursor('grabbing');
        canvas.requestRenderAll();
      }
    });

    canvas.on('mouse:move', function (event) {
      if (!isPanning || !event || !event.e) {
        return;
      }

      var e = event.e;
      var currentPos = new fabric.Point(e.clientX, e.clientY);
      var delta = currentPos.subtract(lastPos);
      lastPos = currentPos;
      canvas.relativePan(delta);
      canvas.setCursor('grabbing');
      canvas.requestRenderAll();
      schedulePersist();
    });

    canvas.on('mouse:up', function () {
      if (!isPanning) {
        return;
      }

      isPanning = false;
      canvas.selection = true;
      canvas.setCursor('default');
      canvas.requestRenderAll();
      schedulePersist();
    });

    function queueGroupRestore() {
      if (!storedGroups.length) {
        return;
      }
      if (pendingGroupRestore) {
        return;
      }

      pendingGroupRestore = window.requestAnimationFrame(function () {
        pendingGroupRestore = null;
        restoreStoredGroups();
      });
    }

    function restoreStoredGroups() {
      if (!storedGroups.length) {
        return;
      }

      storedGroups.forEach(function (group) {
        if (!group || !Array.isArray(group.members) || group.members.length < 2) {
          return;
        }

        var members = group.members
          .map(function (memberId) {
            return productNodes[String(memberId)];
          })
          .filter(function (node) {
            return !!node;
          });

        if (members.length < 2) {
          return;
        }

        var existingGroup = members[0].group;
        var alreadyGrouped =
          existingGroup &&
          existingGroup.type === 'group' &&
          members.every(function (member) {
            return member.group === existingGroup;
          });

        if (alreadyGrouped) {
          return;
        }

        members.forEach(function (member) {
          if (member.group && member.group.type === 'group') {
            member.group.remove(member);
            canvas.add(member);
          }
        });

        var selection = new fabric.ActiveSelection(members, { canvas: canvas });
        var newGroup = selection.toGroup();
        if (newGroup) {
          newGroup.hasBorders = true;
          newGroup.hasControls = true;
          newGroup.setCoords();
        }
      });

      storedGroups = [];
      canvas.discardActiveObject();
      canvas.requestRenderAll();
      schedulePersist();
    }

    function groupActiveSelection() {
      var activeObject = canvas.getActiveObject();
      if (!activeObject || activeObject.type !== 'activeSelection') {
        return;
      }

      activeObject.toGroup();
      canvas.requestRenderAll();
      schedulePersist();
    }

    function ungroupActiveGroup() {
      var activeObject = canvas.getActiveObject();
      if (!activeObject || activeObject.type !== 'group') {
        return;
      }

      activeObject.toActiveSelection();
      canvas.requestRenderAll();
      schedulePersist();
    }

    function restoreViewportFromStorage() {
      if (!storedViewport) {
        return;
      }

      var viewport = sanitizeViewport(storedViewport);
      storedViewport = viewport;

      var center = new fabric.Point(canvas.getWidth() / 2, canvas.getHeight() / 2);
      if (viewport.zoom) {
        canvas.zoomToPoint(center, viewport.zoom);
      }

      var current = canvas.viewportTransform ? canvas.viewportTransform.slice() : null;
      if (current) {
        current[4] = viewport.x;
        current[5] = viewport.y;
        canvas.setViewportTransform(current);
      }

      canvas.requestRenderAll();
    }

    function resetViewport() {
      canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
      storedViewport = { zoom: 1, x: 0, y: 0 };
      canvas.requestRenderAll();
      schedulePersist();
    }

    document.addEventListener('keydown', function (event) {
      if (!event) {
        return;
      }

      var key = event.key || event.code;
      var isMeta = event.metaKey || event.ctrlKey;

      if (!isMeta) {
        return;
      }

      if (key === '0' || key === 'Digit0' || key === 'Numpad0') {
        event.preventDefault();
        resetViewport();
        return;
      }

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
