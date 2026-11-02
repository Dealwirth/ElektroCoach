/**
 * Canvas engine for the schematic editor.
 *
 * Design notes:
 *
 * * **Separation of graphics and electrical model.** A *component* has a
 *   position, rotation, mirror flag and label. An *electrical connection* links
 *   two terminals by id. A *wire* is only a visual polyline; it carries no
 *   electrical meaning by itself. The backend validates the electrical model and
 *   ignores wire geometry, exactly as required.
 * * **Grid snapping.** All coordinates are stored in grid units (default 20 px),
 *   so a drawing is resolution independent and an exported PDF or SVG matches
 *   what the editor shows.
 * * **Undo/redo** keeps full document snapshots. Documents are small, so this is
 *   cheap and cannot corrupt state.
 * * **Pointer events** with `pointerdown/move/up` support mouse, finger and
 *   stylus in one code path. `touch-action: none` on the canvas stops the browser
 *   from scrolling while drawing.
 */

const GRID = 20;
const HANDLE_RADIUS = 6;

export class DrawingEditor {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.grid = options.grid || GRID;
    this.symbols = new Map();
    this.document = {
      version: 1,
      grid: this.grid,
      components: [],
      connections: [],
      wires: [],
      texts: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    };
    this.selection = new Set();
    this.tool = 'select';
    this.pendingSymbol = null;
    this.wireStart = null;
    this.drag = null;
    this.undoStack = [];
    this.redoStack = [];
    this.dirty = false;
    this.listeners = {};
    this._idCounter = 0;
    this._bindEvents();
    this.resize();
  }

  // -- events ---------------------------------------------------------------

  on(name, handler) {
    (this.listeners[name] = this.listeners[name] || []).push(handler);
    return this;
  }

  emit(name, payload) {
    (this.listeners[name] || []).forEach((handler) => handler(payload));
  }

  setSymbols(list) {
    this.symbols = new Map(list.map((symbol) => [symbol.id, symbol]));
    this.draw();
  }

  // -- geometry -------------------------------------------------------------

  get zoom() {
    return this.document.viewport.zoom || 1;
  }

  /** Screen (client) point to grid units. */
  toGrid(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const scale = this.zoom * (this.canvas.width / rect.width) / window.devicePixelRatio;
    const x = (clientX - rect.left) / scale + this.document.viewport.x;
    const y = (clientY - rect.top) / scale + this.document.viewport.y;
    return { x, y };
  }

  snap(value) {
    return Math.round(value / this.grid) * this.grid;
  }

  snapPoint(point) {
    return { x: this.snap(point.x), y: this.snap(point.y) };
  }

  /** Grid-unit point to canvas pixel coordinates. */
  toCanvas(point) {
    const scale = this.zoom * window.devicePixelRatio;
    return {
      x: (point.x - this.document.viewport.x) * scale,
      y: (point.y - this.document.viewport.y) * scale,
    };
  }

  terminalPoint(component, terminalId) {
    const symbol = this.symbols.get(component.symbol);
    if (!symbol) return { x: component.x, y: component.y };
    const terminal = (symbol.terminals || []).find((t) => t.id === terminalId);
    if (!terminal) return { x: component.x, y: component.y };
    let x = terminal.x;
    let y = terminal.y;
    if (component.mirrored) x = symbol.width - x;
    const rotation = ((component.rotation || 0) % 360 + 360) % 360;
    if (rotation === 90) [x, y] = [symbol.height - y, x];
    else if (rotation === 180) [x, y] = [symbol.width - x, symbol.height - y];
    else if (rotation === 270) [x, y] = [y, symbol.width - x];
    return { x: (component.x + x) * this.grid, y: (component.y + y) * this.grid };
  }

  componentAt(point) {
    // Iterate backwards so the topmost component wins.
    for (let index = this.document.components.length - 1; index >= 0; index -= 1) {
      const component = this.document.components[index];
      const symbol = this.symbols.get(component.symbol);
      if (!symbol) continue;
      let width = symbol.width * this.grid;
      let height = symbol.height * this.grid;
      const rotation = ((component.rotation || 0) % 360 + 360) % 360;
      if (rotation === 90 || rotation === 270) [width, height] = [height, width];
      const left = component.x * this.grid;
      const top = component.y * this.grid;
      if (point.x >= left && point.x <= left + width
          && point.y >= top && point.y <= top + height) {
        return component;
      }
    }
    return null;
  }

  terminalAt(point) {
    const tolerance = HANDLE_RADIUS * 2;
    for (let index = this.document.components.length - 1; index >= 0; index -= 1) {
      const component = this.document.components[index];
      const symbol = this.symbols.get(component.symbol);
      if (!symbol) continue;
      for (const terminal of symbol.terminals || []) {
        const position = this.terminalPoint(component, terminal.id);
        if (Math.hypot(position.x - point.x, position.y - point.y) <= tolerance) {
          return { component, terminal };
        }
      }
    }
    return null;
  }

  // -- document -------------------------------------------------------------

  load(document) {
    const incoming = document || {};
    this.document = {
      version: incoming.version || 1,
      grid: incoming.grid || this.grid,
      components: (incoming.components || []).map((component) => ({ ...component })),
      connections: (incoming.connections || []).map((connection) => ({ ...connection })),
      wires: (incoming.wires || []).map((wire) => ({
        ...wire,
        points: (wire.points || []).map((point) => [...point]),
      })),
      texts: (incoming.texts || []).map((text) => ({ ...text })),
      viewport: incoming.viewport || { x: 0, y: 0, zoom: 1 },
    };
    this.selection.clear();
    this.undoStack = [];
    this.redoStack = [];
    this.dirty = false;
    this._idCounter = this.document.components.length;
    this.draw();
    this.emit('change', this.serialize());
  }

  serialize() {
    return JSON.parse(JSON.stringify({
      version: 1,
      grid: this.grid,
      components: this.document.components,
      connections: this.document.connections,
      wires: this.document.wires,
      texts: this.document.texts,
      viewport: this.document.viewport,
    }));
  }

  pushUndo() {
    this.undoStack.push(this.serialize());
    if (this.undoStack.length > 80) this.undoStack.shift();
    this.redoStack = [];
    this.dirty = true;
  }

  undo() {
    if (!this.undoStack.length) return false;
    this.redoStack.push(this.serialize());
    this.document = this.undoStack.pop();
    this.selection.clear();
    this.draw();
    this.emit('change', this.serialize());
    return true;
  }

  redo() {
    if (!this.redoStack.length) return false;
    this.undoStack.push(this.serialize());
    this.document = this.redoStack.pop();
    this.selection.clear();
    this.draw();
    this.emit('change', this.serialize());
    return true;
  }

  nextId(prefix) {
    this._idCounter += 1;
    return `${prefix}${this._idCounter}`;
  }

  addComponent(symbolId, gridPoint) {
    const symbol = this.symbols.get(symbolId);
    if (!symbol) return null;
    this.pushUndo();
    const component = {
      id: this.nextId('C'),
      symbol: symbolId,
      x: gridPoint.x,
      y: gridPoint.y,
      rotation: 0,
      mirrored: false,
      label: '',
      notes: '',
    };
    this.document.components.push(component);
    this.selection = new Set([component.id]);
    this.draw();
    this.emit('change', this.serialize());
    return component;
  }

  removeSelection() {
    if (!this.selection.size) return;
    this.pushUndo();
    this.document.components = this.document.components.filter(
      (component) => !this.selection.has(component.id),
    );
    this.document.connections = this.document.connections.filter(
      (connection) =>
        !this.selection.has(connection.from.component)
        && !this.selection.has(connection.to.component),
    );
    this.document.texts = this.document.texts.filter((text) => !this.selection.has(text.id));
    this.selection.clear();
    this.draw();
    this.emit('change', this.serialize());
  }

  duplicateSelection() {
    if (!this.selection.size) return;
    this.pushUndo();
    const copies = [];
    this.document.components
      .filter((component) => this.selection.has(component.id))
      .forEach((component) => {
        const copy = {
          ...component,
          id: this.nextId('C'),
          x: component.x + this.grid * 2,
          y: component.y + this.grid * 2,
        };
        this.document.components.push(copy);
        copies.push(copy.id);
      });
    this.selection = new Set(copies);
    this.draw();
    this.emit('change', this.serialize());
  }

  rotateSelection() {
    if (!this.selection.size) return;
    this.pushUndo();
    this.document.components
      .filter((component) => this.selection.has(component.id))
      .forEach((component) => {
        component.rotation = (((component.rotation || 0) + 90) % 360);
      });
    this.draw();
    this.emit('change', this.serialize());
  }

  mirrorSelection() {
    if (!this.selection.size) return;
    this.pushUndo();
    this.document.components
      .filter((component) => this.selection.has(component.id))
      .forEach((component) => {
        component.mirrored = !component.mirrored;
      });
    this.draw();
    this.emit('change', this.serialize());
  }

  setLabel(componentId, label) {
    const component = this.document.components.find((c) => c.id === componentId);
    if (!component) return;
    this.pushUndo();
    component.label = label;
    this.draw();
    this.emit('change', this.serialize());
  }

  addText(gridPoint, text) {
    this.pushUndo();
    this.document.texts.push({
      id: this.nextId('T'),
      x: gridPoint.x,
      y: gridPoint.y,
      text,
    });
    this.draw();
    this.emit('change', this.serialize());
  }

  addConnection(from, to) {
    if (!from || !to) return null;
    if (from.component.id === to.component.id && from.terminal.id === to.terminal.id) return null;
    const exists = this.document.connections.some((connection) =>
      (connection.from.component === from.component.id
        && connection.from.terminal === from.terminal.id
        && connection.to.component === to.component.id
        && connection.to.terminal === to.terminal.id)
      || (connection.from.component === to.component.id
        && connection.from.terminal === to.terminal.id
        && connection.to.component === from.component.id
        && connection.to.terminal === from.terminal.id));
    if (exists) {
      this.emit('notice', 'Diese Verbindung existiert bereits.');
      return null;
    }
    this.pushUndo();
    const connection = {
      id: this.nextId('K'),
      from: { component: from.component.id, terminal: from.terminal.id },
      to: { component: to.component.id, terminal: to.terminal.id },
    };
    this.document.connections.push(connection);
    this.draw();
    this.emit('change', this.serialize());
    return connection;
  }

  zoomBy(factor, center) {
    const viewport = this.document.viewport;
    const previous = viewport.zoom || 1;
    const next = Math.max(0.25, Math.min(4, previous * factor));
    if (center) {
      const before = this.toGrid(center.x, center.y);
      viewport.zoom = next;
      const after = this.toGrid(center.x, center.y);
      viewport.x += before.x - after.x;
      viewport.y += before.y - after.y;
    } else {
      viewport.zoom = next;
    }
    this.draw();
  }

  resetView() {
    this.document.viewport = { x: -this.grid * 2, y: -this.grid * 2, zoom: 1 };
    this.draw();
  }

  fitView() {
    const components = this.document.components;
    if (!components.length) {
      this.resetView();
      return;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    components.forEach((component) => {
      const symbol = this.symbols.get(component.symbol);
      if (!symbol) return;
      const width = symbol.width * this.grid;
      const height = symbol.height * this.grid;
      minX = Math.min(minX, component.x * this.grid);
      minY = Math.min(minY, component.y * this.grid);
      maxX = Math.max(maxX, component.x * this.grid + width);
      maxY = Math.max(maxY, component.y * this.grid + height);
    });
    const padding = this.grid * 3;
    const rect = this.canvas.getBoundingClientRect();
    const availableWidth = rect.width - padding * 2;
    const availableHeight = rect.height - padding * 2;
    const contentWidth = Math.max(this.grid, maxX - minX);
    const contentHeight = Math.max(this.grid, maxY - minY);
    const zoom = Math.max(0.25, Math.min(2, Math.min(availableWidth / contentWidth, availableHeight / contentHeight)));
    this.document.viewport = {
      zoom,
      x: minX - padding / zoom,
      y: minY - padding / zoom,
    };
    this.draw();
  }

  // -- rendering ------------------------------------------------------------

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    this.canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    this.draw();
  }

  draw() {
    const context = this.ctx;
    const scale = this.zoom * (window.devicePixelRatio || 1);
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, this.canvas.width, this.canvas.height);

    context.save();
    context.scale(scale, scale);
    context.translate(-this.document.viewport.x, -this.document.viewport.y);

    this._drawGrid(context);

    // Wires.
    context.strokeStyle = '#2563eb';
    context.lineWidth = 2 / this.zoom;
    context.lineJoin = 'round';
    this.document.wires.forEach((wire) => {
      if (!wire.points || wire.points.length < 2) return;
      context.beginPath();
      wire.points.forEach((point, index) => {
        if (index === 0) context.moveTo(point[0], point[1]);
        else context.lineTo(point[0], point[1]);
      });
      context.stroke();
    });

    // Components.
    this.document.components.forEach((component) => this._drawComponent(context, component));

    // Electrical connections (dashed so they are visibly distinct from wires).
    context.strokeStyle = '#94a3b8';
    context.lineWidth = 1.2 / this.zoom;
    context.setLineDash([5 / this.zoom, 4 / this.zoom]);
    this.document.connections.forEach((connection) => {
      const from = this._connectionPoint(connection.from);
      const to = this._connectionPoint(connection.to);
      if (!from || !to) return;
      context.beginPath();
      context.moveTo(from.x, from.y);
      context.lineTo(to.x, to.y);
      context.stroke();
    });
    context.setLineDash([]);

    // Free texts.
    context.fillStyle = '#0f172a';
    context.font = `${13 / this.zoom}px sans-serif`;
    this.document.texts.forEach((text) => {
      context.fillText(text.text, text.x, text.y);
      if (this.selection.has(text.id)) {
        context.strokeStyle = '#1d5fd0';
        context.lineWidth = 1.5 / this.zoom;
        context.strokeRect(text.x - 4, text.y - 14, text.text.length * 7 + 8, 20);
      }
    });

    // Pending wire preview.
    if (this.wireStart && this.drag && this.drag.preview) {
      context.strokeStyle = '#2563eb';
      context.lineWidth = 2 / this.zoom;
      context.setLineDash([6 / this.zoom, 4 / this.zoom]);
      context.beginPath();
      context.moveTo(this.wireStart.x, this.wireStart.y);
      context.lineTo(this.drag.preview.x, this.drag.preview.y);
      context.stroke();
      context.setLineDash([]);
    }

    // Selection handles and terminal markers.
    this.document.components.forEach((component) => {
      const symbol = this.symbols.get(component.symbol);
      if (!symbol) return;
      const selected = this.selection.has(component.id);
      let width = symbol.width * this.grid;
      let height = symbol.height * this.grid;
      const rotation = ((component.rotation || 0) % 360 + 360) % 360;
      if (rotation === 90 || rotation === 270) [width, height] = [height, width];
      if (selected) {
        context.strokeStyle = '#1d5fd0';
        context.lineWidth = 1.6 / this.zoom;
        context.setLineDash([4 / this.zoom, 3 / this.zoom]);
        context.strokeRect(component.x * this.grid, component.y * this.grid, width, height);
        context.setLineDash([]);
      }
      (symbol.terminals || []).forEach((terminal) => {
        const point = this.terminalPoint(component, terminal.id);
        context.fillStyle = selected ? '#1d5fd0' : '#94a3b8';
        context.beginPath();
        context.arc(point.x, point.y, 3.2 / this.zoom, 0, Math.PI * 2);
        context.fill();
      });
    });

    context.restore();
  }

  _drawGrid(context) {
    const grid = this.grid;
    const viewport = this.document.viewport;
    const scale = this.zoom;
    const width = this.canvas.width / scale;
    const height = this.canvas.height / scale;
    const startX = Math.floor(viewport.x / grid) * grid;
    const startY = Math.floor(viewport.y / grid) * grid;
    const endX = viewport.x + width;
    const endY = viewport.y + height;

    context.lineWidth = 0.5 / scale;
    for (let x = startX; x <= endX; x += grid) {
      const major = Math.round(x / grid) % 5 === 0;
      context.strokeStyle = major ? '#dfe5ee' : '#eef2f7';
      context.beginPath();
      context.moveTo(x, viewport.y);
      context.lineTo(x, endY);
      context.stroke();
    }
    for (let y = startY; y <= endY; y += grid) {
      const major = Math.round(y / grid) % 5 === 0;
      context.strokeStyle = major ? '#dfe5ee' : '#eef2f7';
      context.beginPath();
      context.moveTo(viewport.x, y);
      context.lineTo(endX, y);
      context.stroke();
    }
    // Origin marker.
    context.strokeStyle = '#cbd5e1';
    context.lineWidth = 1 / scale;
    context.beginPath();
    context.moveTo(0, viewport.y);
    context.lineTo(0, endY);
    context.moveTo(viewport.x, 0);
    context.lineTo(endX, 0);
    context.stroke();
  }

  _drawComponent(context, component) {
    const symbol = this.symbols.get(component.symbol);
    if (!symbol) return;
    context.save();
    context.translate(component.x * this.grid, component.y * this.grid);

    const rotation = ((component.rotation || 0) % 360 + 360) % 360;
    const width = symbol.width * this.grid;
    const height = symbol.height * this.grid;
    if (component.mirrored) {
      context.translate(width, 0);
      context.scale(-1, 1);
    }
    if (rotation === 90) {
      context.translate(height, 0);
      context.rotate(Math.PI / 2);
    } else if (rotation === 180) {
      context.translate(width, height);
      context.rotate(Math.PI);
    } else if (rotation === 270) {
      context.translate(0, width);
      context.rotate(-Math.PI / 2);
    }

    context.strokeStyle = '#1f2937';
    context.lineWidth = 1.6 / this.zoom;
    context.lineCap = 'round';
    context.lineJoin = 'round';

    (symbol.shapes || []).forEach((shape) => {
      context.beginPath();
      if (shape.type === 'line') {
        context.moveTo(shape.x1 * this.grid, shape.y1 * this.grid);
        context.lineTo(shape.x2 * this.grid, shape.y2 * this.grid);
        context.stroke();
      } else if (shape.type === 'rect') {
        const x = shape.x * this.grid;
        const y = shape.y * this.grid;
        const w = shape.w * this.grid;
        const h = shape.h * this.grid;
        if (shape.filled) {
          context.fillStyle = '#1f2937';
          context.fillRect(x, y, w, h);
        } else {
          context.rect(x, y, w, h);
          context.stroke();
        }
      } else if (shape.type === 'circle') {
        context.arc(shape.cx * this.grid, shape.cy * this.grid, shape.r * this.grid, 0, Math.PI * 2);
        if (shape.filled) {
          context.fillStyle = '#1f2937';
          context.fill();
        } else {
          context.stroke();
        }
      } else if (shape.type === 'polyline') {
        const points = shape.points || [];
        if (points.length < 2) return;
        context.moveTo(points[0][0] * this.grid, points[0][1] * this.grid);
        points.slice(1).forEach((point) => {
          context.lineTo(point[0] * this.grid, point[1] * this.grid);
        });
        if (shape.filled) {
          context.fillStyle = '#1f2937';
          context.fill();
        } else {
          context.stroke();
        }
      } else if (shape.type === 'text') {
        context.fillStyle = '#0f172a';
        const size = (shape.size || 0.5) * this.grid;
        context.font = `${size}px sans-serif`;
        context.textAlign = shape.anchor === 'start' ? 'left' : 'center';
        context.fillText(shape.text || '', shape.x * this.grid, shape.y * this.grid);
        context.textAlign = 'left';
      }
    });
    context.restore();

    if (component.label) {
      context.fillStyle = '#0f172a';
      context.font = `${12 / this.zoom}px sans-serif`;
      context.textAlign = 'center';
      context.fillText(component.label,
        component.x * this.grid + (symbol.width * this.grid) / 2,
        component.y * this.grid - 5 / this.zoom);
      context.textAlign = 'left';
    }
  }

  _connectionPoint(endpoint) {
    const component = this.document.components.find((c) => c.id === endpoint.component);
    if (!component) return null;
    return this.terminalPoint(component, endpoint.terminal);
  }

  // -- interaction ----------------------------------------------------------

  _bindEvents() {
    this.canvas.addEventListener('pointerdown', (event) => this._onPointerDown(event));
    this.canvas.addEventListener('pointermove', (event) => this._onPointerMove(event));
    this.canvas.addEventListener('pointerup', (event) => this._onPointerUp(event));
    this.canvas.addEventListener('pointercancel', (event) => this._onPointerUp(event));
    this.canvas.addEventListener('pointerleave', (event) => this._onPointerUp(event));
    this.canvas.addEventListener('wheel', (event) => this._onWheel(event), { passive: false });
    this.canvas.addEventListener('contextmenu', (event) => event.preventDefault());
    window.addEventListener('resize', () => this.resize());
  }

  _onWheel(event) {
    event.preventDefault();
    if (event.ctrlKey || event.metaKey || Math.abs(event.deltaY) > 40) {
      this.zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12, { x: event.clientX, y: event.clientY });
      return;
    }
    // Plain wheel pans, matching the expectation on a drawing surface.
    this.document.viewport.x += event.deltaX / this.zoom;
    this.document.viewport.y += event.deltaY / this.zoom;
    this.draw();
  }

  _onPointerDown(event) {
    this.canvas.setPointerCapture(event.pointerId);
    const point = this.toGrid(event.clientX, event.clientY);

    if (event.button === 1 || (event.button === 0 && this.tool === 'pan')) {
      this.drag = { mode: 'pan', startClient: { x: event.clientX, y: event.clientY },
        startViewport: { ...this.document.viewport } };
      return;
    }
    if (event.button === 2) {
      // Right click: pan as well (common on tablets without a middle button).
      this.drag = { mode: 'pan', startClient: { x: event.clientX, y: event.clientY },
        startViewport: { ...this.document.viewport } };
      return;
    }

    if (this.tool === 'wire') {
      const terminal = this.terminalAt(point);
      if (terminal) {
        if (!this.wireStart) {
          this.wireStart = this.terminalPoint(terminal.component, terminal.terminal.id);
          this.wireStartTerminal = terminal;
          this.emit('notice', `Startpunkt gesetzt: ${terminal.component.id}.${terminal.terminal.id}. Jetzt den zweiten Anschluss anklicken.`);
        } else {
          this.addConnection(this.wireStartTerminal, terminal);
          this.wireStart = null;
          this.wireStartTerminal = null;
        }
        this.draw();
        return;
      }
      // No terminal under the cursor: start a free wire (graphics only).
      this.drag = {
        mode: 'freewire',
        points: [this.snapPoint(point)],
        preview: this.snapPoint(point),
      };
      this.draw();
      return;
    }

    if (this.tool === 'text') {
      const value = window.prompt('Text eingeben:');
      if (value) this.addText(this.snapPoint(point), value);
      return;
    }

    if (this.pendingSymbol) {
      const symbol = this.symbols.get(this.pendingSymbol);
      const snapped = this.snapPoint(point);
      const offsetX = Math.floor((symbol ? symbol.width : 1) / 2) * this.grid;
      const offsetY = Math.floor((symbol ? symbol.height : 1) / 2) * this.grid;
      this.addComponent(this.pendingSymbol, {
        x: snapped.x - offsetX,
        y: snapped.y - offsetY,
      });
      this.emit('notice', 'Bauteil eingefügt. Mit „Verbinden“ die Anschlüsse verdrahten.');
      return;
    }

    // Select or drag.
    const component = this.componentAt(point);
    if (component) {
      if (!event.shiftKey && !this.selection.has(component.id)) {
        this.selection = new Set([component.id]);
      } else if (event.shiftKey) {
        if (this.selection.has(component.id)) this.selection.delete(component.id);
        else this.selection.add(component.id);
      }
      this.drag = {
        mode: 'move',
        start: this.snapPoint(point),
        originals: this.document.components
          .filter((c) => this.selection.has(c.id))
          .map((c) => ({ id: c.id, x: c.x, y: c.y })),
      };
      this.emit('selection', this.selectedComponents());
      this.draw();
      return;
    }

    // Marquee selection.
    this.selection.clear();
    this.drag = { mode: 'marquee', start: this.snapPoint(point), preview: this.snapPoint(point) };
    this.emit('selection', []);
    this.draw();
  }

  _onPointerMove(event) {
    const point = this.toGrid(event.clientX, event.clientY);
    if (!this.drag) {
      this.emit('cursor', this.snapPoint(point));
      return;
    }
    if (this.drag.mode === 'pan') {
      const scale = this.zoom;
      this.document.viewport.x = this.drag.startViewport.x
        - (event.clientX - this.drag.startClient.x) / scale;
      this.document.viewport.y = this.drag.startViewport.y
        - (event.clientY - this.drag.startClient.y) / scale;
      this.draw();
      return;
    }
    if (this.drag.mode === 'move') {
      const snapped = this.snapPoint(point);
      const dx = snapped.x - this.drag.start.x;
      const dy = snapped.y - this.drag.start.y;
      this.drag.originals.forEach((original) => {
        const component = this.document.components.find((c) => c.id === original.id);
        if (component) {
          component.x = original.x + dx;
          component.y = original.y + dy;
        }
      });
      this.draw();
      return;
    }
    if (this.drag.mode === 'freewire') {
      this.drag.preview = this.snapPoint(point);
      this.draw();
      return;
    }
    if (this.drag.mode === 'marquee') {
      this.drag.preview = this.snapPoint(point);
      this.draw();
    }
  }

  _onPointerUp(event) {
    if (!this.drag) return;
    const mode = this.drag.mode;
    const drag = this.drag;
    this.drag = null;

    if (mode === 'move' || mode === 'marquee') {
      if (mode === 'move') {
        const moved = drag.originals.some((original) => {
          const component = this.document.components.find((c) => c.id === original.id);
          return component && (component.x !== original.x || component.y !== original.y);
        });
        if (moved) {
          // Undo snapshot: restore the pre-drag positions.
          this.undoStack.push(this._snapshotWith(drag.originals));
          this.redoStack = [];
          this.dirty = true;
          this.emit('change', this.serialize());
        }
      } else {
        const minX = Math.min(drag.start.x, drag.preview.x);
        const maxX = Math.max(drag.start.x, drag.preview.x);
        const minY = Math.min(drag.start.y, drag.preview.y);
        const maxY = Math.max(drag.start.y, drag.preview.y);
        this.document.components.forEach((component) => {
          const symbol = this.symbols.get(component.symbol);
          if (!symbol) return;
          const left = component.x * this.grid;
          const top = component.y * this.grid;
          const right = left + symbol.width * this.grid;
          const bottom = top + symbol.height * this.grid;
          if (right >= minX && left <= maxX && bottom >= minY && top <= maxY) {
            this.selection.add(component.id);
          }
        });
        this.emit('selection', this.selectedComponents());
      }
    }

    if (mode === 'freewire') {
      if (drag.points.length >= 2) {
        this.pushUndo();
        this.document.wires.push({ id: this.nextId('W'), points: drag.points });
        this.emit('change', this.serialize());
      }
    }
    this.draw();
  }

  _snapshotWith(originals) {
    const snapshot = this.serialize();
    originals.forEach((original) => {
      const component = snapshot.components.find((c) => c.id === original.id);
      if (component) {
        component.x = original.x;
        component.y = original.y;
      }
    });
    return snapshot;
  }

  selectedComponents() {
    return this.document.components.filter((component) => this.selection.has(component.id));
  }
}
