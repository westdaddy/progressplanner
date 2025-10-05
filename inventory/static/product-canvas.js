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
      return { objects: {}, groups: [] };
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
        return { objects: {}, groups: [] };
      }
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') {
        return { objects: {}, groups: [] };
      }

      var storedObjects;
      var storedGroups = [];
      if (parsed.objects && typeof parsed.objects === 'object') {
        storedObjects = parsed.objects;
        if (Array.isArray(parsed.groups)) {
          storedGroups = parsed.groups;
        }
      } else {
        storedObjects = parsed;
      }

      var filteredObjects = {};
      var objectsChanged = false;
      Object.keys(storedObjects).forEach(function (key) {
        if (allowed[key]) {
          filteredObjects[key] = storedObjects[key];
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

      if (objectsChanged || groupsChanged) {
        scheduleLayoutWrite({ objects: filteredObjects, groups: filteredGroups });
      }

      return { objects: filteredObjects, groups: filteredGroups };
    } catch (err) {
      console.warn('Unable to read stored product canvas layout', err);
      return { objects: {}, groups: [] };
    }
  }

  var pendingLayout;

  function collectPersistableObjects(canvas) {
    var layout = { objects: {}, groups: [] };
    if (!canvas) {
      return layout;
    }

    var vpt = canvas.viewportTransform ? canvas.viewportTransform.slice() : null;
    var invertedVpt = vpt ? fabric.util.invertTransform(vpt) : null;
    var zoom = canvas.getZoom ? canvas.getZoom() : 1;

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

        var objectScaling = typeof obj.getObjectScaling === 'function' ? obj.getObjectScaling() : null;
        var scaleX = objectScaling ? objectScaling.scaleX : obj.scaleX;
        var scaleY = objectScaling ? objectScaling.scaleY : obj.scaleY;
        if (typeof scaleX === 'number' && zoom) {
          scaleX = scaleX / zoom;
        }
        if (typeof scaleY === 'number' && zoom) {
          scaleY = scaleY / zoom;
        }

        layout.objects[key] = {
          left: point.x,
          top: point.y,
          scaleX: typeof scaleX === 'number' ? scaleX : 1,
          scaleY: typeof scaleY === 'number' ? scaleY : 1,
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

  function scheduleLayoutWrite(layout) {
    if (!storageAvailable) {
      return;
    }

    try {
      var payload = layout && typeof layout === 'object' ? layout : {};
      if (!payload.objects || typeof payload.objects !== 'object') {
        payload.objects = {};
      }
      if (!Array.isArray(payload.groups)) {
        payload.groups = [];
      }
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
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
      var layout = collectPersistableObjects(canvas);
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
      selection: true,
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
    var storedObjects = storedLayout.objects || {};
    var storedGroups = storedLayout.groups || [];
    var productNodes = {};
    var pendingGroupRestore;

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

          var stored = storedObjects[key];
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
          productNodes[key] = img;
          schedulePersist(canvas);
          queueGroupRestore();
        },
        { crossOrigin: 'anonymous' }
      );
    });

    canvas.on('object:modified', function () {
      schedulePersist(canvas);
    });

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
    });

    canvas.on('mouse:up', function () {
      if (isPanning) {
        isPanning = false;
        canvas.selection = true;
        canvas.setCursor('default');
        canvas.requestRenderAll();
      }
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
      schedulePersist(canvas);
    }

    function groupActiveSelection() {
      var activeObject = canvas.getActiveObject();
      if (!activeObject || activeObject.type !== 'activeSelection') {
        return;
      }

      activeObject.toGroup();
      canvas.requestRenderAll();
      schedulePersist(canvas);
    }

    function ungroupActiveGroup() {
      var activeObject = canvas.getActiveObject();
      if (!activeObject || activeObject.type !== 'group') {
        return;
      }

      activeObject.toActiveSelection();
      canvas.requestRenderAll();
      schedulePersist(canvas);
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
