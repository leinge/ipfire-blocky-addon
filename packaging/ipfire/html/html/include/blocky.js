/* Schema-driven native management UI for the IPFire Blocky add-on. */
(function () {
  "use strict";

  const app = document.getElementById("blocky-app");
  if (!app) return;

  const endpoint = app.dataset.endpoint;
  const state = {
    tab: "service",
    section: "upstreams",
    data: null,
    schema: null,
    descriptor: null,
    translations: {},
    config: null,
    settings: null,
    busy: false,
    message: "",
    error: "",
  };

  const h = (tag, attrs, ...children) => {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) node.setAttribute(key, key);
      else if (value !== false && value !== null && value !== undefined) node.setAttribute(key, value);
    });
    children.flat().forEach((child) => {
      if (child === null || child === undefined) return;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    });
    return node;
  };

  const clone = (value) => JSON.parse(JSON.stringify(value));
  const t = (key, fallback) => state.translations[key] || fallback;
  const setBusy = (value) => { state.busy = value; render(); };

  async function request(action, values) {
    const body = new URLSearchParams({ ACTION: action, ...(values || {}) });
    const response = await fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body,
    });
    const result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.error || `Request failed (${response.status})`);
    return result;
  }

  async function load() {
    try {
      const [dataResult, schemaResult] = await Promise.all([request("DATA"), request("SCHEMA")]);
      state.data = dataResult;
      state.config = clone(dataResult.config);
      state.settings = clone(dataResult.settings);
      state.schema = schemaResult.schema;
      state.descriptor = schemaResult.descriptor;
      state.translations = schemaResult.translations || {};
    } catch (error) {
      state.error = error.message;
    }
    render();
  }

  function defaultFor(schema) {
    if (Object.prototype.hasOwnProperty.call(schema || {}, "default")) return clone(schema.default);
    const type = schema && schema.type;
    if (type === "object" || (schema && schema.properties)) return {};
    if (type === "array") return [];
    if (type === "boolean") return false;
    if (type === "integer" || type === "number") return 0;
    return "";
  }

  function effectiveSchema(schema, value) {
    if (!schema || !schema.anyOf) return schema || {};
    const kind = Array.isArray(value) ? "array" : (Number.isInteger(value) ? "integer" : typeof value);
    return schema.anyOf.find((item) => item.type === kind) || schema.anyOf[0];
  }

  function help(schema) {
    if (!schema || !schema.description) return null;
    return h("p", { class: "blocky-help", text: schema.description });
  }

  function primitiveEditor(schema, value, setValue, path) {
    if (schema.enum) {
      const select = h("select", { "aria-label": path, onchange: () => setValue(select.value) });
      schema.enum.forEach((option) => select.append(h("option", {
        value: option,
        selected: option === value,
        text: String(option),
      })));
      return select;
    }
    if (schema.type === "boolean") {
      const input = h("input", { type: "checkbox", checked: Boolean(value), "aria-label": path });
      input.addEventListener("change", () => setValue(input.checked));
      return input;
    }
    if (schema.type === "integer" || schema.type === "number") {
      const input = h("input", {
        type: "number",
        value: value === undefined ? "" : value,
        min: schema.minimum,
        max: schema.maximum,
        "aria-label": path,
      });
      input.addEventListener("change", () => {
        const parsed = schema.type === "integer" ? Number.parseInt(input.value, 10) : Number(input.value);
        setValue(Number.isNaN(parsed) ? 0 : parsed);
      });
      return input;
    }
    const stringValue = value === undefined || value === null ? "" : String(value);
    const sensitive = (state.descriptor.sensitive || []).includes(path);
    const multiline = stringValue.includes("\n") || schema.format === "textarea" || path.endsWith(".zone");
    const input = multiline
      ? h("textarea", { rows: "5", "aria-label": path }, stringValue)
      : h("input", { type: sensitive ? "password" : "text", value: stringValue, "aria-label": path });
    input.addEventListener("change", () => setValue(input.value));
    if (!sensitive) return input;
    return h("span", { class: "blocky-secret" }, input, h("button", {
      type: "button",
      class: "blocky-secondary",
      onclick: () => {
        if (window.confirm(`Clear the stored secret value for ${path}?`)) {
          setValue("__IPFIRE_BLOCKY_CLEAR_SECRET__");
        }
      },
      text: "Clear stored value",
    }), h("small", { text: " Leave blank to preserve the stored value." }));
  }

  function editor(schemaInput, value, setValue, path, label) {
    const schema = effectiveSchema(schemaInput, value);
    if (schemaInput && schemaInput.anyOf) {
      const wrapper = h("div", { class: "blocky-anyof" });
      const selector = h("select", { "aria-label": `${path} type` });
      schemaInput.anyOf.forEach((option, index) => selector.append(h("option", {
        value: index,
        selected: option === schema,
        text: option.type || `variant ${index + 1}`,
      })));
      selector.addEventListener("change", () => setValue(defaultFor(schemaInput.anyOf[Number(selector.value)])));
      wrapper.append(h("label", { class: "blocky-inline-label", text: `${label} type ` }, selector));
      wrapper.append(editor(schema, value, setValue, path, label));
      return wrapper;
    }

    if (schema.type === "array") {
      const values = Array.isArray(value) ? value : [];
      const box = h("div", { class: "blocky-collection" });
      values.forEach((item, index) => {
        const update = (next) => { const copy = clone(values); copy[index] = next; setValue(copy); };
        const remove = () => { const copy = clone(values); copy.splice(index, 1); setValue(copy); };
        const move = (offset) => {
          const target = index + offset;
          if (target < 0 || target >= values.length) return;
          const copy = clone(values);
          [copy[index], copy[target]] = [copy[target], copy[index]];
          setValue(copy);
        };
        box.append(h("div", { class: "blocky-array-item" },
          editor(schema.items || {}, item, update, `${path}[${index}]`, `${label} ${index + 1}`),
          h("div", { class: "blocky-row-actions" },
            h("button", { type: "button", onclick: () => move(-1), disabled: index === 0, text: "↑" }),
            h("button", { type: "button", onclick: () => move(1), disabled: index === values.length - 1, text: "↓" }),
            h("button", { type: "button", onclick: remove, text: "Remove" })
          )
        ));
      });
      box.append(h("button", {
        type: "button",
        class: "blocky-secondary",
        onclick: () => setValue([...values, defaultFor(schema.items || {})]),
        text: `Add ${label}`,
      }));
      return box;
    }

    if (schema.type === "object" || schema.properties || schema.additionalProperties) {
      const object = value && typeof value === "object" && !Array.isArray(value) ? value : {};
      const box = h("div", { class: "blocky-object" });
      Object.entries(schema.properties || {}).forEach(([key, childSchema]) => {
        const childPath = path ? `${path}.${key}` : key;
        const managed = (state.descriptor.managed || []).includes(childPath);
        const present = Object.prototype.hasOwnProperty.call(object, key);
        const row = h("div", { class: "blocky-field" });
        const enabled = h("input", {
          type: "checkbox",
          checked: present,
          disabled: managed,
          "aria-label": `Enable ${childPath}`,
        });
        enabled.addEventListener("change", () => {
          const next = clone(object);
          if (enabled.checked) next[key] = defaultFor(childSchema);
          else delete next[key];
          setValue(next);
        });
        row.append(h("div", { class: "blocky-field-title" }, enabled,
          h("label", { text: key }), managed ? h("span", { class: "blocky-managed", text: "managed by IPFire" }) : null));
        if (present) {
          if (managed) {
            row.append(h("pre", { class: "blocky-managed-value", text: JSON.stringify(object[key], null, 2) }));
          } else {
            row.append(editor(childSchema, object[key], (nextValue) => {
              const next = clone(object); next[key] = nextValue; setValue(next);
            }, childPath, key));
          }
        }
        row.append(help(childSchema));
        box.append(row);
      });

      if (schema.additionalProperties) {
        const fixed = new Set(Object.keys(schema.properties || {}));
        Object.keys(object).filter((key) => !fixed.has(key)).forEach((key) => {
          const row = h("div", { class: "blocky-map-item" });
          const keyInput = h("input", { type: "text", value: key, "aria-label": `${path} key` });
          keyInput.addEventListener("change", () => {
            const nextKey = keyInput.value.trim();
            if (!nextKey || (nextKey !== key && Object.prototype.hasOwnProperty.call(object, nextKey))) {
              keyInput.value = key; return;
            }
            const next = clone(object); next[nextKey] = next[key]; delete next[key]; setValue(next);
          });
          row.append(keyInput);
          row.append(editor(schema.additionalProperties, object[key], (nextValue) => {
            const next = clone(object); next[key] = nextValue; setValue(next);
          }, `${path}.${key}`, key));
          row.append(h("button", { type: "button", onclick: () => {
            const next = clone(object); delete next[key]; setValue(next);
          }, text: "Remove" }));
          box.append(row);
        });
        box.append(h("button", { type: "button", class: "blocky-secondary", onclick: () => {
          let index = 1; let key = `entry-${index}`;
          while (Object.prototype.hasOwnProperty.call(object, key)) key = `entry-${++index}`;
          const next = clone(object); next[key] = defaultFor(schema.additionalProperties); setValue(next);
        }, text: `Add ${label} entry` }));
      }
      return box;
    }

    return primitiveEditor(schema, value, setValue, path);
  }

  function tabButton(id, text) {
    return h("button", {
      type: "button",
      class: state.tab === id ? "blocky-tab active" : "blocky-tab",
      onclick: () => { state.tab = id; state.error = ""; state.message = ""; render(); },
      text,
    });
  }

  function statusBadge(status) {
    const kind = status.enforcedDown ? "critical" : (status.healthy ? "good" : "neutral");
    const text = status.enforcedDown ? "ENFORCED — BLOCKY DOWN" : (status.healthy ? "Healthy" : "Stopped / unhealthy");
    return h("span", { class: `blocky-badge ${kind}`, text });
  }

  async function serviceAction(action) {
    state.error = ""; state.message = ""; setBusy(true);
    try {
      const result = await request("SERVICE", { SERVICE_ACTION: action });
      state.data = result.data; state.message = `Service action '${action}' completed.`;
    } catch (error) { state.error = error.message; }
    state.busy = false; render();
  }

  function servicePanel() {
    const status = state.data.status;
    return h("div", { class: "blocky-panel" },
      h("h2", { text: t("service and status", "Service and status") }),
      status.enforcementActive ? h("div", { class: "blocky-warning critical", text: t("enforcement active", "ENFORCEMENT ACTIVE — DNS FAILS CLOSED if Blocky is unavailable.") }) : null,
      statusBadge(status),
      h("dl", { class: "blocky-status" },
        h("dt", { text: "Version" }), h("dd", { text: `${status.blockyVersion || "unknown"} (package ${status.packageVersion || "unknown"})` }),
        h("dt", { text: "Process" }), h("dd", { text: status.running ? `running (PID ${status.pid || "unknown"}) as ${status.user}` : "stopped" }),
        h("dt", { text: "Boot" }), h("dd", { text: status.bootEnabled ? "enabled" : "disabled" }),
        h("dt", { text: "Configuration" }), h("dd", { text: status.configurationValid ? "valid" : "invalid" }),
        h("dt", { text: "Health" }), h("dd", { text: status.healthy ? "healthcheck.blocky answered on 127.0.0.1:1053" : "not healthy" }),
        h("dt", { text: "Selected zones" }), h("dd", { text: status.selectedZones.join(", ").toUpperCase() || "none" }),
        h("dt", { text: "Routed zones" }), h("dd", { text: status.routedZones.join(", ").toUpperCase() || "none" }),
        h("dt", { text: "Bypass prevention" }), h("dd", { text: status.bypassZones.join(", ").toUpperCase() || "none" }),
        h("dt", { text: "Last successful apply" }), h("dd", { text: status.lastSuccessfulApply || "never" }),
        h("dt", { text: "Last result" }), h("dd", { text: status.message || "none" })
      ),
      h("div", { class: "blocky-actions" },
        ...["validate", "start", "restart", "stop", "enable", "disable"].map((action) => h("button", {
          type: "button", disabled: state.busy, onclick: () => serviceAction(action), text: t(`action ${action}`, action),
        }))
      ),
      h("p", { class: "blocky-help", text: "The Web UI refuses normal stop/disable while enforcement is active. For emergency recovery, use /usr/sbin/blocky-recovery from a local root console." })
    );
  }

  function configPanel() {
    const section = state.descriptor.sections.find((item) => item.id === state.section) || state.descriptor.sections[0];
    const sectionSelect = h("select", { onchange: () => { state.section = sectionSelect.value; render(); } });
    state.descriptor.sections.forEach((item) => sectionSelect.append(h("option", {
      value: item.id, selected: item.id === section.id, text: item.title,
    })));
    const body = h("div", { class: "blocky-schema" });
    section.properties.forEach((property) => {
      const schema = state.schema.properties[property];
      if (!schema) return;
      const present = Object.prototype.hasOwnProperty.call(state.config, property);
      const field = h("section", { class: "blocky-top-field" }, h("h3", { text: property }));
      const toggle = h("input", { type: "checkbox", checked: present, "aria-label": `Enable ${property}` });
      toggle.addEventListener("change", () => {
        if (toggle.checked) state.config[property] = defaultFor(schema); else delete state.config[property];
        render();
      });
      field.prepend(h("label", { class: "blocky-enable" }, toggle, ` Configure ${property}`));
      if (present) field.append(editor(schema, state.config[property], (value) => { state.config[property] = value; render(); }, property, property));
      field.append(help(schema)); body.append(field);
    });

    const advanced = h("textarea", { class: "blocky-json", rows: "28", spellcheck: "false" }, JSON.stringify(state.config, null, 2));
    const applyAdvanced = h("button", { type: "button", onclick: () => {
      try { state.config = JSON.parse(advanced.value); state.error = ""; state.message = "Advanced JSON accepted locally; save to validate with Blocky."; render(); }
      catch (error) { state.error = `Invalid JSON: ${error.message}`; render(); }
    }, text: "Use advanced JSON" });

    const details = h("details", { class: "blocky-advanced" },
      h("summary", { text: "Advanced canonical JSON" }),
      h("p", { class: "blocky-help", text: "JSON is emitted as valid YAML. The generated ports.dns value remains integration-managed." }),
      advanced, applyAdvanced
    );
    return h("div", { class: "blocky-panel" },
      h("h2", { text: t("full configuration", "Full Blocky configuration") }),
      h("label", { text: "Configuration section " }, sectionSelect), body, details,
      importExportControls()
    );
  }

  function importExportControls() {
    const input = h("input", { type: "file", accept: ".json,.yaml,.yml,application/json,text/yaml" });
    const importButton = h("button", { type: "button", onclick: async () => {
      if (!input.files || !input.files[0]) { state.error = "Choose a YAML or JSON file first."; render(); return; }
      const imported = await input.files[0].text();
      if (!window.confirm("Import and apply this configuration? Comments and formatting will not be preserved.")) return;
      await apply({ import: imported, settings: state.settings });
    }, text: "Import and apply" });
    const downloadExport = async (includeSecrets) => {
      const body = new URLSearchParams({ ACTION: "EXPORT" });
      if (includeSecrets) body.set("INCLUDE_SECRETS", "on");
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body,
      });
      if (!response.ok) throw new Error(`Export failed (${response.status})`);
      const blob = await response.blob();
      const link = h("a", {
        href: URL.createObjectURL(blob),
        download: includeSecrets ? "blocky-private-export.json" : "blocky-export.json",
      });
      document.body.append(link); link.click(); link.remove();
      URL.revokeObjectURL(link.href);
    };
    const redacted = h("button", { type: "button", onclick: async () => {
      try { await downloadExport(false); } catch (error) { state.error = error.message; render(); }
    }, text: "Export (redacted)" });
    const secret = h("button", { type: "button", onclick: async () => {
      if (window.confirm("This export contains passwords and credentials. Store it securely. Continue?")) {
        try { await downloadExport(true); } catch (error) { state.error = error.message; render(); }
      }
    }, text: "Export with secrets" });
    return h("div", { class: "blocky-import-export" }, input, importButton, redacted, secret);
  }

  function zonePanel() {
    const cards = ["green", "blue"].map((name) => {
      const info = state.data.zones[name];
      if (!info && name === "blue") return null;
      const desired = state.settings.zones[name];
      const checkbox = h("input", { type: "checkbox", checked: desired.selected, disabled: !info });
      checkbox.addEventListener("change", () => {
        if (!checkbox.checked && (desired.route || desired.bypass)) {
          state.error = `Disable ${name.toUpperCase()} routing and bypass prevention first.`; render(); return;
        }
        desired.selected = checkbox.checked; render();
      });
      return h("div", { class: `blocky-zone ${name}` },
        h("h3", { text: name.toUpperCase() }),
        info ? h("p", { text: `${info.interface} — ${info.address} — ${info.cidr}` }) : h("p", { text: "Not configured in IPFire" }),
        h("label", {}, checkbox, ` Serve ${name.toUpperCase()} on ${info ? `${info.address}:1053` : "unavailable"}`)
      );
    });
    return h("div", { class: "blocky-panel" }, h("h2", { text: t("zones", "GREEN / BLUE zones") }),
      h("p", { text: "Selecting a zone adds its current IPFire address to Blocky's port 1053 listeners. It does not redirect client DNS until Routing is enabled." }),
      h("div", { class: "blocky-zones" }, ...cards));
  }

  function routingPanel() {
    const rows = ["green", "blue"].map((name) => {
      const info = state.data.zones[name];
      if (!info && name === "blue") return null;
      const zone = state.settings.zones[name];
      const checkbox = h("input", { type: "checkbox", checked: zone.route, disabled: !zone.selected });
      checkbox.addEventListener("change", () => {
        if (!checkbox.checked && zone.bypass) { state.error = `Disable ${name.toUpperCase()} bypass prevention first.`; render(); return; }
        zone.route = checkbox.checked; render();
      });
      return h("label", { class: "blocky-policy-row" }, checkbox,
        ` Force all TCP/UDP port 53 from ${name.toUpperCase()} through Blocky`);
    });
    return h("div", { class: "blocky-panel" }, h("h2", { text: t("routing", "Transparent DNS routing") }),
      h("div", { class: "blocky-warning", text: "After activation, the selected zone fails closed: if Blocky stops, DNS does not fall back to Knot." }),
      ...rows,
      h("p", { class: "blocky-help", text: "Rules match the trusted ingress interface. RED and ORANGE are never selectable. Blocky's own locally generated upstream queries are not intercepted." }));
  }

  function linesControl(field, label, placeholder) {
    const input = h("textarea", { rows: "4", placeholder }, state.settings.doh[field].join("\n"));
    input.addEventListener("change", () => {
      state.settings.doh[field] = input.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    });
    return h("label", { class: "blocky-lines" }, h("strong", { text: label }), input);
  }

  function bypassPanel() {
    const toggles = ["green", "blue"].map((name) => {
      const info = state.data.zones[name];
      if (!info && name === "blue") return null;
      const zone = state.settings.zones[name];
      const checkbox = h("input", { type: "checkbox", checked: zone.bypass, disabled: !zone.route });
      checkbox.addEventListener("change", () => {
        zone.bypass = checkbox.checked;
        if (checkbox.checked && state.settings.doh.providers.length === 0) {
          state.settings.doh.providers = state.data.catalog.providers.filter((provider) => provider.default).map((provider) => provider.id);
        }
        render();
      });
      return h("label", { class: "blocky-policy-row" }, checkbox,
        ` Prevent known DNS bypass from ${name.toUpperCase()}`);
    });
    const providerRows = state.data.catalog.providers.map((provider) => {
      const checked = state.settings.doh.providers.includes(provider.id);
      const checkbox = h("input", { type: "checkbox", checked });
      checkbox.addEventListener("change", () => {
        const selected = new Set(state.settings.doh.providers);
        if (checkbox.checked) selected.add(provider.id); else selected.delete(provider.id);
        state.settings.doh.providers = [...selected].sort(); render();
      });
      return h("label", { class: "blocky-provider" }, checkbox,
        h("span", {}, h("strong", { text: provider.name }),
          ` — ${provider.domains.join(", ")} — ${provider.ipv4.join(", ") || "domain rules only"}`,
          provider.sharedHostingRisk ? h("em", { text: " shared-hosting risk" }) : null));
    });
    return h("div", { class: "blocky-panel" }, h("h2", { text: t("bypass prevention", "DNS-bypass prevention") }),
      h("div", { class: "blocky-warning critical", text: t("best effort warning", "Best effort only: unknown DoH, shared HTTPS endpoints, VPNs, proxies, and tunnels can bypass these controls. Provider IP blocking can affect unrelated traffic.") }),
      ...toggles,
      h("h3", { text: "Known DoH providers" }), ...providerRows,
      h("div", { class: "blocky-grid" },
        linesControl("customDomains", "Custom endpoint domains", "doh.example.net"),
        linesControl("customIPv4", "Custom dedicated IPv4 CIDRs", "192.0.2.53/32"),
        linesControl("exceptDomains", "Domain exceptions", "allowed.example.net"),
        linesControl("exceptIPv4", "IPv4 destination exceptions", "192.0.2.54/32")
      ),
      h("p", { class: "blocky-help", text: "Enabled zones intercept TCP/UDP 53, reject TCP/UDP 853, block selected provider domains in Blocky, and reject TCP/UDP 443 only to reviewed provider/custom destination networks." }));
  }

  async function apply(envelope) {
    state.error = ""; state.message = "";
    if (!window.confirm("Apply this configuration? Active routing and bypass enforcement fail closed if Blocky becomes unavailable.")) return;
    setBusy(true);
    try {
      const result = await request("APPLY", { PAYLOAD: JSON.stringify(envelope || { config: state.config, settings: state.settings }) });
      state.data = result.data; state.config = clone(result.data.config); state.settings = clone(result.data.settings);
      state.message = "Configuration validated and applied.";
    } catch (error) { state.error = error.message; }
    state.busy = false; render();
  }

  function previewPanel() {
    const providers = new Map(state.data.catalog.providers.map((item) => [item.id, item]));
    const selected = state.settings.doh.providers.map((id) => providers.get(id)).filter(Boolean);
    const policy = {
      domains: [...new Set(selected.flatMap((item) => item.domains).concat(state.settings.doh.customDomains))].sort(),
      ipv4: [...new Set(selected.flatMap((item) => item.ipv4).concat(state.settings.doh.customIPv4))].sort(),
      domainExceptions: state.settings.doh.exceptDomains,
      ipv4Exceptions: state.settings.doh.exceptIPv4,
    };
    const configChanged = JSON.stringify(state.config) !== JSON.stringify(state.data.config);
    const settingsChanged = JSON.stringify(state.settings) !== JSON.stringify(state.data.settings);
    return h("details", { class: "blocky-preview" },
      h("summary", { text: "Review candidate and exact provider policy" }),
      h("p", { text: `Canonical configuration changed: ${configChanged ? "yes" : "no"}; IPFire integration settings changed: ${settingsChanged ? "yes" : "no"}.` }),
      h("h3", { text: "Provider rules" }), h("pre", { text: JSON.stringify(policy, null, 2) }),
      h("h3", { text: "Candidate documents" }), h("pre", { text: JSON.stringify({ config: state.config, settings: state.settings }, null, 2) })
    );
  }

  function render() {
    app.replaceChildren();
    app.append(h("style", {}, `
      .blocky-tabs,.blocky-actions,.blocky-import-export{display:flex;gap:.5rem;flex-wrap:wrap;margin:1rem 0}
      .blocky-tab,.blocky-button,button{padding:.45rem .75rem}.blocky-tab.active{font-weight:bold;border-bottom:3px solid #2b74b8}
      .blocky-panel{padding:.5rem}.blocky-warning{padding:.8rem;margin:.8rem 0;background:#fff3cd;border-left:5px solid #d39e00}
      .blocky-warning.critical,.blocky-badge.critical{background:#f8d7da;color:#721c24}.blocky-badge{display:inline-block;padding:.35rem .6rem;border-radius:3px;background:#eee}
      .blocky-badge.good{background:#d4edda;color:#155724}.blocky-status{display:grid;grid-template-columns:max-content 1fr;gap:.3rem 1rem}.blocky-status dt{font-weight:bold}
      .blocky-field,.blocky-top-field,.blocky-array-item,.blocky-map-item,.blocky-zone{border:1px solid #bbb;padding:.7rem;margin:.5rem 0}.blocky-field-title{display:flex;gap:.5rem;align-items:center;font-weight:bold}
      .blocky-managed{font-size:.8em;background:#e2e3e5;padding:.1rem .35rem}.blocky-object{margin-left:1rem}.blocky-map-item,.blocky-array-item{display:grid;gap:.5rem}
      .blocky-row-actions{display:flex;gap:.3rem}.blocky-help{font-size:.9em;color:#555;white-space:pre-line}.blocky-json,.blocky-lines textarea{width:100%;box-sizing:border-box;font-family:monospace}
      .blocky-zones,.blocky-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}.blocky-policy-row,.blocky-provider,.blocky-lines{display:block;padding:.5rem}
      .blocky-provider span{margin-left:.4rem}.blocky-enable{font-weight:bold}.blocky-error{background:#f8d7da;color:#721c24;padding:.8rem}.blocky-message{background:#d4edda;color:#155724;padding:.8rem}
      input[type=text],input[type=password],input[type=number],select{max-width:100%;padding:.3rem}.blocky-anyof>.blocky-inline-label{display:block;margin-bottom:.4rem}
      .blocky-preview pre,.blocky-managed-value{overflow:auto;max-height:24rem;background:#f6f6f6;padding:.6rem}
    `));
    if (state.error) app.append(h("div", { class: "blocky-error", text: state.error }));
    if (state.message) app.append(h("div", { class: "blocky-message", text: state.message }));
    if (!state.data || !state.schema) {
      app.append(h("p", { text: state.error ? "Blocky data could not be loaded." : "Loading Blocky configuration..." }));
      return;
    }
    app.append(h("nav", { class: "blocky-tabs", "aria-label": "Blocky settings" },
      tabButton("service", `1. ${t("service and status", "Service and status")}`),
      tabButton("config", `2. ${t("full configuration", "Full Blocky configuration")}`),
      tabButton("zones", `3. ${t("zones", "GREEN / BLUE zones")}`),
      tabButton("routing", `4. ${t("routing", "Transparent DNS routing")}`),
      tabButton("bypass", `5. ${t("bypass prevention", "DNS-bypass prevention")}`)
    ));
    const panels = { service: servicePanel, config: configPanel, zones: zonePanel, routing: routingPanel, bypass: bypassPanel };
    app.append(panels[state.tab]());
    if (state.tab !== "service") {
      app.append(previewPanel());
      app.append(h("div", { class: "blocky-actions" }, h("button", {
        type: "button", disabled: state.busy, onclick: () => apply(), text: state.busy ? "Applying..." : t("save apply", "Save, validate, and apply"),
      })));
    }
  }

  load();
}());
