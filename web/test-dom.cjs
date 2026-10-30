/* Minimal DOM double for application smoke checks; not a browser implementation. */
class NodeDouble {
  constructor(tagName, document) {
    this.tagName = tagName.toLowerCase(); this.document = document; this.children = []; this.listeners = {};
    this.attributes = {}; this.dataset = {}; this.style = {}; this.hidden = false; this.disabled = false;
    this.clientWidth = 650; this._value = ""; this._text = "";
    const classes = new Set(); this.classList = { add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value) };
  }
  set value(value) { this._value = String(value); }
  get value() { return this._value; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(""); }
  append(...children) { this.children.push(...children); if (this.tagName === "select" && !this.value && children[0]) this.value = children[0].value; }
  replaceChildren(...children) { this.children = []; this._text = ""; if (this.tagName === "select") this.value = ""; this.append(...children); }
  setAttribute(key, value) { this.attributes[key] = String(value); if (key.startsWith("data-")) this.dataset[key.slice(5)] = String(value); }
  getAttribute(key) { return this.attributes[key] ?? null; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  emit(type, extra = {}) { for (const handler of this.listeners[type] || []) handler({ target: this, preventDefault() {}, ...extra }); }
  click() { this.emit("click"); }
  focus() { this.document.activeElement = this; this.emit("focus"); }
  querySelectorAll(selector) {
    const nodes = this.children.flatMap(child => [child, ...child.querySelectorAll(selector)]);
    return nodes.filter(node => selector === "[data-record]" ? node.dataset.record : false);
  }
  querySelector(selector) { const match = selector.match(/^\[data-record="([^"]+)"\]$/); return match ? this.querySelectorAll("[data-record]").find(node => node.dataset.record === match[1]) : null; }
  showModal() { this.setAttribute("open", ""); }
  close() { this.removeAttribute("open"); }
}

function createDocument(html) {
  const document = { nodes: new Map(), activeElement: null };
  for (const match of html.matchAll(/<([a-z][a-z0-9-]*)\b[^>]*\bid="([^"]+)"[^>]*>/gi)) {
    const node = new NodeDouble(match[1], document); node.id = match[2]; node.hidden = /\bhidden\b/.test(match[0]); document.nodes.set(node.id, node);
  }
  document.getElementById = id => document.nodes.get(id);
  document.createElement = tag => new NodeDouble(tag, document);
  document.createElementNS = (_, tag) => new NodeDouble(tag, document);
  document.querySelectorAll = selector => selector === "[data-outcome]" ? [document.nodes.get("tab-contact"), document.nodes.get("tab-peak")] : [];
  document.nodes.get("tab-contact").dataset.outcome = "contact_ms";
  document.nodes.get("tab-peak").dataset.outcome = "pressure_peak_N";
  return document;
}
module.exports = { createDocument };
