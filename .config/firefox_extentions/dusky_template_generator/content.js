/*
 * Dusky Template Generator — content.js (Production Audited Edition)
 *
 * Injected on demand (activeTab) by background.js.
 *   scan    Maps site CSS variables via perceptual luminance clustering and
 *           framework signatures; generates structural themes for static sites.
 *   picker  Interactive visual picker that can target BOTH element selectors
 *           AND underlying CSS variables directly from clicked elements, with
 *           SVG fill support, Tailwind/Radix filtering, and automatic contrast pairing.
 *
 * Designed for Firefox 155+ and modern Arch Linux environments.
 */
"use strict";
(() => {
  if (globalThis.__duskyTemplateGenerator) return;
  globalThis.__duskyTemplateGenerator = true;

  // ─── Material Design 3 Palette Contract ──────────────────────────────────
  const TOKENS = [
    ["surface", "Surface (Base canvas)"],
    ["surface_container_lowest", "Surface container lowest"],
    ["surface_container_low", "Surface container low"],
    ["surface_container", "Surface container (Cards/panels)"],
    ["surface_container_high", "Surface container high (Modals/dialogs)"],
    ["surface_container_highest", "Surface container highest"],
    ["surface_bright", "Surface bright"],
    ["surface_variant", "Surface variant"],
    ["on_surface", "On surface (Main text)"],
    ["on_surface_variant", "On surface variant (Muted text)"],
    ["inverse_on_surface", "Inverse on surface"],
    ["primary", "Primary (Brand accent)"],
    ["on_primary", "On primary (Text on primary)"],
    ["primary_container", "Primary container"],
    ["on_primary_container", "On primary container"],
    ["primary_fixed", "Primary fixed (Hover accent)"],
    ["primary_fixed_dim", "Primary fixed dim (Active accent)"],
    ["secondary", "Secondary"],
    ["on_secondary", "On secondary"],
    ["secondary_container", "Secondary container"],
    ["on_secondary_container", "On secondary container"],
    ["tertiary", "Tertiary"],
    ["on_tertiary", "On tertiary"],
    ["tertiary_container", "Tertiary container"],
    ["on_tertiary_container", "On tertiary container"],
    ["outline", "Outline (Borders/inputs)"],
    ["outline_variant", "Outline variant (Subtle dividers)"],
    ["error", "Error"],
    ["on_error", "On error"],
    ["error_container", "Error container"]
  ];

  const paletteLoaded = () => !!getComputedStyle(document.documentElement).getPropertyValue("--surface").trim();

  // ─── 🎨 Perceptual Color Extraction Engine ────────────────────────────────
  let colorProbe = null;
  function getProbe() {
    if (!colorProbe || !colorProbe.isConnected) {
      colorProbe = document.createElement("span");
      colorProbe.style.cssText = "display:none !important; position:fixed !important; visibility:hidden !important;";
      (document.head || document.documentElement).appendChild(colorProbe);
    }
    return colorProbe;
  }

  function parseCssColor(rawVal) {
    if (!rawVal || typeof rawVal !== "string") return null;
    const v = rawVal.trim();
    if (/^(inherit|initial|unset|revert|revert-layer|transparent|currentcolor)$/i.test(v)) return null;

    const tripletMatch = v.match(/^(\d{1,3})[,\s]+(\d{1,3})[,\s]+(\d{1,3})$/);
    if (tripletMatch) {
      const [, rStr, gStr, bStr] = tripletMatch;
      return {
        r: parseInt(rStr, 10),
        g: parseInt(gStr, 10),
        b: parseInt(bStr, 10),
        a: 1,
        isTriplet: true
      };
    }

    const hslMatch = v.match(/^([\d.]+)(?:deg)?\s+([\d.]+)%\s+([\d.]+)%$/);
    const colorStr = hslMatch ? `hsl(${v})` : v;

    try {
      const probe = getProbe();
      probe.style.color = "";
      probe.style.color = colorStr;
      const comp = getComputedStyle(probe).color;
      if (!comp) return null;
      const m = comp.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/);
      if (m) {
        const [, rStr, gStr, bStr, aStr] = m;
        return {
          r: parseInt(rStr, 10),
          g: parseInt(gStr, 10),
          b: parseInt(bStr, 10),
          a: aStr !== undefined ? parseFloat(aStr) : 1,
          isTriplet: false
        };
      }
    } catch (_) {
      return null;
    }
    return null;
  }

  function getLuminance(r, g, b) {
    const [lr, lg, lb] = [r, g, b].map((val) => {
      val /= 255;
      return val <= 0.03928 ? val / 12.92 : Math.pow((val + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
  }

  function getChromaAndHue(r, g, b) {
    const rf = r / 255, gf = g / 255, bf = b / 255;
    const max = Math.max(rf, gf, bf), min = Math.min(rf, gf, bf);
    const delta = max - min;
    let hue = 0;
    if (delta !== 0) {
      if (max === rf) hue = ((gf - bf) / delta) % 6;
      else if (max === gf) hue = (bf - rf) / delta + 2;
      else hue = (rf - gf) / delta + 4;
      hue = Math.round(hue * 60);
      if (hue < 0) hue += 360;
    }
    return { chroma: delta, hue };
  }

  // ─── Framework Signatures & Perceptual Classifier ─────────────────────────
  const SKIP_VAR_PREFIXES = /^--(tw|fa|darkreader|dusky)-|^--(surface|primary|secondary|tertiary|error|outline)(_[a-z0-9_]+)?$|^--on_/;

  function matchKnownFramework(name) {
    const n = name.toLowerCase();

    // ChatGPT Specific Tokens
    if (n === "--gray-750") return "surface_container_highest";
    if (n === "--gray-900") return "surface_container";
    if (n === "--black") return "surface";
    if (n === "--blue-400") return "primary_container";
    if (n === "--default-theme-user-msg-text") return "surface";
    if (n === "--message-surface") return "primary";
    if (n === "--bg-primary") return "surface";
    if (n === "--bg-secondary") return "surface_bright";
    if (n === "--bg-tertiary") return "surface_container_high";
    if (n === "--bg-elevated-secondary") return "surface_container_low";
    if (n === "--text-primary") return "on_surface";
    if (n === "--bg-secondary-surface") return "surface";
    if (n.includes("sidebar-surface-primary")) return "surface_container";
    if (n.includes("composer-surface-primary")) return "surface";

    // YouTube Spec Tokens
    if (n.startsWith("--yt-spec-")) {
      if (n.includes("base-background") || n.includes("general-background-a")) return "background";
      if (n.includes("raised-background") || n.includes("menu-background")) return "surface_container";
      if (n.includes("general-background-b")) return "surface_container_low";
      if (n.includes("general-background-c")) return "surface_container_lowest";
      if (n.includes("text-primary")) return "on_surface";
      if (n.includes("text-secondary") || n.includes("icon-color")) return "on_surface_variant";
      if (n.includes("brand-background-solid") || n.includes("call-to-action") || n.includes("static-brand-red")) return "primary";
      if (n.includes("badge-chip-background")) return "surface_container_high";
      if (n.includes("button-chip-background-hover")) return "surface_bright";
      if (n.includes("icon-inactive")) return "outline";
      if (n.includes("10-percent-layer")) return "surface_variant";
    }

    // Google / Gemini / Material Design
    if (n.startsWith("--gem-sys-color--") || n.startsWith("--mat-") || n.startsWith("--bard-color-")) {
      if (n.endsWith("--primary")) return "primary";
      if (n.endsWith("--on-primary")) return "on_primary";
      if (n.endsWith("--primary-container")) return "primary_container";
      if (n.endsWith("--on-primary-container")) return "on_primary_container";
      if (n.endsWith("--secondary")) return "secondary";
      if (n.endsWith("--on-secondary")) return "on_secondary";
      if (n.endsWith("--secondary-container")) return "secondary_container";
      if (n.endsWith("--tertiary")) return "tertiary";
      if (n.endsWith("--on-tertiary")) return "on_tertiary";
      if (n.endsWith("--surface")) return "surface";
      if (n.endsWith("--surface-bright")) return "surface_bright";
      if (n.endsWith("--surface-container")) return "surface_container";
      if (n.endsWith("--surface-container-high")) return "surface_container_high";
      if (n.endsWith("--surface-container-highest")) return "surface_container_highest";
      if (n.endsWith("--surface-container-low")) return "surface_container_low";
      if (n.endsWith("--surface-container-lowest")) return "surface_container_lowest";
      if (n.endsWith("--on-surface") || n.includes("app-text-color")) return "on_surface";
      if (n.endsWith("--on-surface-variant")) return "on_surface_variant";
      if (n.endsWith("--outline")) return "outline";
      if (n.endsWith("--outline-variant")) return "outline_variant";
      if (n.includes("background-color")) return "surface";
    }

    // Tailwind / Shadcn / Radix UI tokens
    if (/^--(background|foreground|card|popover|primary|secondary|muted|accent|destructive|border|input|ring)(-foreground)?$/.test(n)) {
      if (n === "--background") return "surface";
      if (n === "--foreground") return "on_surface";
      if (n === "--card") return "surface_container";
      if (n === "--card-foreground") return "on_surface";
      if (n === "--popover") return "surface_container_high";
      if (n === "--popover-foreground") return "on_surface";
      if (n === "--primary") return "primary";
      if (n === "--primary-foreground") return "on_primary";
      if (n === "--secondary") return "secondary_container";
      if (n === "--secondary-foreground") return "on_secondary_container";
      if (n === "--muted") return "surface_container_low";
      if (n === "--muted-foreground") return "on_surface_variant";
      if (n === "--accent") return "surface_container_high";
      if (n === "--accent-foreground") return "on_surface";
      if (n === "--destructive") return "error";
      if (n === "--destructive-foreground") return "on_error";
      if (n === "--border") return "outline_variant";
      if (n === "--input") return "outline";
      if (n === "--ring") return "primary";
    }

    // Discord tokens
    if (n.startsWith("--neutral-")) {
      const num = parseInt(n.replace("--neutral-", ""), 10);
      if (!isNaN(num)) {
        if (num >= 90) return "surface";
        if (num >= 84) return "surface_container_low";
        if (num >= 78) return "surface_container";
        if (num >= 70) return "surface_container_high";
        if (num <= 10) return "on_surface";
        if (num <= 30) return "on_surface_variant";
      }
    }
    if (n.startsWith("--blurple-") || n.startsWith("--brand-") || n === "--blue-new-37") {
      if (n === "--brand-560") return "on_primary_container";
      if (n === "--brand-10a" || n.includes("highlight")) return "inverse_on_surface";
      if (n.includes("60")) return "secondary_container";
      if (n.includes("50") || n.includes("65")) return "primary_container";
      return "primary";
    }

    // Instagram tokens
    if (n.startsWith("--ig-")) {
      if (n.includes("primary-background")) return "surface";
      if (n.includes("primary-text") || n.includes("primary-icon")) return "on_surface";
      if (n.includes("elevated-background")) return "surface_container_low";
    }

    // Chess.com tokens
    if (n.startsWith("--color-gray-") || n.startsWith("--color-green-")) {
      if (n.includes("gray-800")) return "surface";
      if (n.includes("gray-700")) return "surface_container";
      if (n.includes("gray-600")) return "surface_container_high";
      if (n.includes("gray-500")) return "surface_container_highest";
      if (n.includes("gray-400")) return "surface_bright";
      if (n.includes("green-300")) return "primary";
      if (n.includes("green-200")) return "primary_fixed";
      if (n.includes("green-400") || n.includes("green-500")) return "primary_container";
      if (n.includes("neutrals-white")) return "on_surface";
    }

    // Telegram tokens
    if (n.startsWith("--color-") || n.startsWith("--theme-")) {
      if (n.includes("chat-hover") || n.includes("background-selected") || n.includes("gray")) return "surface_container_high";
      if (n.includes("chat-active") || n.includes("primary") || n.includes("background-own")) return "primary_container";
      if (n.includes("background-secondary")) return "surface_container_lowest";
      if (n.includes("background-compact-menu") || n.includes("action-message-bg")) return "surface_container_low";
      if (n.includes("theme-background-color") || n.includes("color-background")) return "surface";
      if (n.includes("color-text")) return "on_surface_variant";
    }

    if (n === "--bg-color") return "surface";
    if (n === "--main-color" || n === "--text-color") return "primary";
    if (n === "--caret-color") return "primary_fixed";
    if (n === "--sub-color") return "primary_container";
    if (n === "--sub-alt-color") return "surface_container_low";

    return "";
  }

  function classifyByValueAndName(name, col) {
    const n = name.slice(2).toLowerCase().replace(/[_.]/g, "-");
    const lum = getLuminance(col.r, col.g, col.b);
    const { chroma, hue } = getChromaAndHue(col.r, col.g, col.b);

    if (/(error|danger|destructive|critical|invalid)/.test(n)) return "error";
    if (/(border|divider|separator|rule|stroke)/.test(n)) return lum > 0.3 ? "outline" : "outline_variant";
    if (/(outline)/.test(n)) return "outline";
    if (/(link|primary|brand|accent|cta)/.test(n) && chroma >= 0.1) return "primary";

    if (chroma >= 0.15) {
      if (hue >= 340 || hue <= 25) {
        return /(btn|action|brand)/.test(n) ? "primary" : "error";
      }
      if (hue > 25 && hue <= 65) return "tertiary";
      if (hue > 65 && hue <= 170) return "secondary";
      if (hue > 170 && hue <= 280) return "primary";
      return "tertiary";
    }

    if (lum <= 0.02) {
      if (/(body|canvas|canvas-bg|bg-base|root|background|black)/.test(n)) return "surface";
      return "surface_container_lowest";
    }
    if (lum <= 0.06) {
      if (/(input|field|inset|sunken|deep)/.test(n)) return "surface_container_low";
      return "surface";
    }
    if (lum <= 0.12) {
      if (/(card|panel|box|container|sidebar|nav)/.test(n)) return "surface_container";
      return "surface_container_low";
    }
    if (lum <= 0.22) {
      if (/(modal|dialog|popover|dropdown|menu|toast|elevated)/.test(n)) return "surface_container_high";
      return "surface_container";
    }
    if (lum <= 0.38) {
      if (/(hover|active|bright)/.test(n)) return "surface_bright";
      return "surface_container_highest";
    }

    if (lum >= 0.70) {
      if (/(muted|secondary|dim|subtle|caption|hint|disabled)/.test(n)) return "on_surface_variant";
      return "on_surface";
    }
    if (lum >= 0.38) {
      return "on_surface_variant";
    }

    return "";
  }

  function detectRootScopes() {
    const scopes = new Set([":root"]);
    const roots = [document.documentElement, document.body].filter(Boolean);

    for (const el of roots) {
      for (const cls of el.classList) {
        if (/^(dark|dark-theme|theme-dark|dark-mode|night)$/i.test(cls)) {
          scopes.add("." + CSS.escape(cls));
          scopes.add("html." + CSS.escape(cls));
        }
      }
      for (const attr of el.getAttributeNames()) {
        if (/^(data-theme|data-color-mode|data-bs-theme|theme|dark)$/i.test(attr)) {
          const val = el.getAttribute(attr);
          if (val) scopes.add(`[${CSS.escape(attr)}="${CSS.escape(val)}"]`);
          else scopes.add(`[${CSS.escape(attr)}]`);
        }
      }
    }
    scopes.add("[dark]");
    scopes.add(".dark");
    scopes.add('[data-theme="dark"]');
    return Array.from(scopes).join(", ");
  }

  function collectVariables() {
    const names = new Set();
    const rootCs = getComputedStyle(document.documentElement);
    const bodyCs = document.body ? getComputedStyle(document.body) : rootCs;

    for (const cs of [rootCs, bodyCs]) {
      for (const p of cs) {
        if (p.startsWith("--")) names.add(p);
      }
    }

    const rootish = /(^|,)\s*(:root|html|body|\[dark\]|\.dark)\b/i;
    const walk = (rules) => {
      for (const r of rules) {
        if (r.styleSheet) { try { walk(r.styleSheet.cssRules); } catch (_) {} }
        if (r.cssRules && r.cssRules.length) walk(r.cssRules);
        if (r.style && r.selectorText && rootish.test(r.selectorText)) {
          for (const p of r.style) {
            if (p.startsWith("--")) names.add(p);
          }
        }
      }
    };
    for (const sheet of document.styleSheets) {
      try { walk(sheet.cssRules); } catch (_) {}
    }

    const out = new Map();
    for (const n of names) {
      const v = (rootCs.getPropertyValue(n) || bodyCs.getPropertyValue(n)).trim();
      if (v) out.set(n, v);
    }
    return out;
  }

  function generateStructuralFallback() {
    return [
      "    /* Structural theme for static/variable-less pages */",
      "    html, body {",
      "        background-color: var(--surface) !important;",
      "        color: var(--on_surface) !important;",
      "        color-scheme: dark !important;",
      "        scrollbar-color: var(--surface_variant) transparent !important;",
      "    }",
      "",
      "    /* Pass-through wrappers while keeping icons, media, and form controls intact */",
      "    :not(a):not(button):not(input):not(select):not(textarea):not(code):not(pre):not(kbd):not(table):not(thead):not(tbody):not(tr):not(th):not(td):not(svg):not(svg *):not(img):not(video):not(canvas):not(i):not([class*=\"icon\" i]):not([class*=\"badge\" i]):not([class*=\"btn\" i]) {",
      "        background-color: transparent !important;",
      "        color: inherit !important;",
      "    }",
      "",
      "    /* Layout containers, headers and sidebars */",
      "    header, nav, aside, footer, [role=\"navigation\"], [role=\"banner\"], [role=\"complementary\"],",
      "    .card, .container, .sidebar, .navbar, .box, .panel, .dialog, .modal {",
      "        background-color: var(--surface_container) !important;",
      "        border-color: var(--outline_variant) !important;",
      "        color: var(--on_surface) !important;",
      "    }",
      "",
      "    /* Code blocks */",
      "    code, pre, kbd, samp {",
      "        background-color: var(--surface_container_high) !important;",
      "        color: var(--on_surface) !important;",
      "        border-color: var(--outline_variant) !important;",
      "    }",
      "",
      "    /* Links */",
      "    a:any-link { color: var(--primary) !important; }",
      "    a:any-link:hover { color: var(--primary_fixed) !important; }",
      "    a:visited { color: var(--tertiary) !important; }",
      "",
      "    /* Form inputs */",
      "    input:not([type=\"submit\"]):not([type=\"button\"]):not([type=\"reset\"]):not([type=\"checkbox\"]):not([type=\"radio\"]),",
      "    textarea, select {",
      "        background-color: var(--surface_container_low) !important;",
      "        color: var(--on_surface) !important;",
      "        border: 1px solid var(--outline) !important;",
      "        border-radius: 6px;",
      "        caret-color: var(--primary) !important;",
      "    }",
      "",
      "    /* Action buttons */",
      "    button, input[type=\"submit\"], input[type=\"button\"], .btn, .button {",
      "        background-color: var(--primary) !important;",
      "        color: var(--on_primary) !important;",
      "        border: none !important;",
      "        border-radius: 6px;",
      "    }",
      "    button:hover, input[type=\"submit\"]:hover {",
      "        background-color: var(--primary_fixed) !important;",
      "    }",
      "",
      "    /* Tables */",
      "    table, th, td { border-color: var(--outline_variant) !important; }",
      "    th { background-color: var(--surface_container_high) !important; color: var(--on_surface) !important; }",
      "    tr:nth-child(even) td { background-color: var(--surface_container_low) !important; }"
    ].join("\n");
  }

  function scan() {
    const rawVars = collectVariables();
    const groups = new Map();
    const unmapped = [];
    let found = 0;

    for (const [name, rawValue] of rawVars) {
      if (SKIP_VAR_PREFIXES.test(name)) continue;
      const parsedColor = parseCssColor(rawValue);
      if (!parsedColor) continue;
      found++;

      let token = matchKnownFramework(name);
      if (!token) {
        token = classifyByValueAndName(name, parsedColor);
      }

      if (!token) {
        unmapped.push(name);
        continue;
      }

      const key = parsedColor.isTriplet ? token + "_rgb" : token;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(name);
    }

    const host = window.location.hostname;

    // Direct ChatGPT Detection & Injection
    if (host.includes("chatgpt.com")) {
      const chatgptTokens = [
        ["--gray-750", "surface_container_highest"],
        ["--gray-900", "surface_container"],
        ["--black", "surface"],
        ["--blue-400", "primary_container"],
        ["--default-theme-user-msg-text", "surface"],
        ["--message-surface", "primary"],
        ["--bg-primary", "surface_container"],
        ["--bg-tertiary", "surface_container_high"],
        ["--bg-primary", "surface"],
        ["--bg-secondary", "surface_bright"],
        ["--bg-elevated-secondary", "surface_container_low"],
        ["--text-primary", "on_surface"],
        ["--bg-secondary-surface", "surface"]
      ];

      const lines = [
        "    :root, .dark {",
        "        color-scheme: dark !important;"
      ];
      for (const [v, t] of chatgptTokens) {
        lines.push(`        ${v}: var(--${t}) !important;`);
      }
      lines.push("    }");
      lines.push("");
      lines.push("    .dark\\:bg-\\[\\#353535\\]:where(.dark, .dark *):not(:where(.dark .light, .dark .light *)) {");
      lines.push("        background-color: var(--surface_container_high) !important;");
      lines.push("    }");
      lines.push("    .dark[data-oled] [data-composer-surface=\"true\"] {");
      lines.push("        background-color: var(--surface_container) !important;");
      lines.push("    }");
      lines.push("    .dark\\:bg-\\[\\#171717\\]:where(.dark, .dark *):not(:where(.dark .light, .dark .light *)) {");
      lines.push("        background-color: var(--surface_container_high) !important;");
      lines.push("    }");
      return { ok: true, found: chatgptTokens.length, mapped: chatgptTokens.length, body: lines.join("\n") };
    }

    if (groups.size === 0) {
      const fallbackBody = generateStructuralFallback();
      return { ok: true, found: 0, mapped: 1, body: fallbackBody };
    }

    const order = TOKENS.flatMap(([t]) => [t, t + "_rgb"]);
    const scopes = detectRootScopes();
    const lines = [`    ${scopes} {`, "        color-scheme: dark !important;"];
    let mapped = 0;

    for (const key of order) {
      const names = groups.get(key);
      if (!names || !names.length) continue;
      lines.push("        /* " + key.replace(/_rgb$/, " (rgb components)") + " */");
      for (const n of names.sort()) {
        lines.push(`        ${n}: var(--${key}) !important;`);
        mapped++;
      }
    }
    lines.push("    }");

    if (host.includes("youtube.com")) {
      lines.push("");
      lines.push("    /* YouTube Component Polish */");
      lines.push("    #guide-content.ytd-app, ytd-guide-renderer, ytd-feed-filter-chip-bar-renderer { background-color: var(--surface) !important; }");
      lines.push("    .ytp-play-progress { background-image: linear-gradient(to right, var(--primary) 80%, var(--primary) 100%) !important; }");
      lines.push("    #logo-icon svg g path[fill^=\"#ff\" i], ytd-logo svg g path[fill^=\"#ff\" i] { fill: var(--primary) !important; }");
      lines.push("    #logo-icon [fill=\"white\" i], .ytd-logo [fill=\"white\" i] { fill: var(--on_primary) !important; }");
      lines.push("    .ytSearchboxComponentInputBox { background-color: var(--surface_container) !important; color: var(--on_surface) !important; }");
      lines.push("    ytd-button-renderer.style-primary .yt-spec-button-shape-next--filled { background-color: var(--primary) !important; color: var(--on_primary) !important; }");
    }

    if (unmapped.length) {
      const shown = unmapped.sort().slice(0, 30).join(", ") + (unmapped.length > 30 ? `, +${unmapped.length - 30} more` : "");
      lines.push(`    /* Variables left unmapped: ${shown} */`);
    }

    return { ok: true, found, mapped, body: lines.join("\n") };
  }

  // ─── 🎯 Interactive Visual Picker ─────────────────────────────────────────
  const S = {
    active: false, hydrated: false, note: "",
    rules: [], undo: [], redo: [], stack: [], depth: 0,
    locked: false, targetMode: "selector", group: "bg",
    activeVar: "", elementVars: [],
    dialogPos: null, raf: 0, saveSeq: 0
  };

  const RULE_RE = /^(.+?)\s*\{\s*(.*?)\s*\}\s*(?:\/\*\s*(.*?)\s*\*\/)?$/;
  function parseRule(line) {
    const m = RULE_RE.exec(line);
    if (!m) return { raw: line };
    const [, sel, decl, rawMeta = ""] = m;
    return { sel, decl, meta: rawMeta.trim() };
  }

  const ruleCss = (r) => (r.raw !== undefined ? r.raw : r.sel + " { " + r.decl + " }");
  const ruleLine = (r) => (r.raw !== undefined ? r.raw : ruleCss(r) + (r.meta ? " /* " + r.meta + " */" : ""));
  const target = () => S.stack.at(S.depth) || null;

  const GROUPS = {
    bg: {
      extra: {
        label: "👻 Transparent",
        css: "background: transparent !important; box-shadow: none !important;",
        meta: "bg: transparent"
      }
    },
    text: {
      extra: {
        label: "↩ Inherit colour",
        css: "color: inherit !important;",
        meta: "text: inherit"
      }
    },
    border: {
      extra: {
        label: "⊘ No border",
        css: "border-color: transparent !important;",
        meta: "border: none"
      }
    },
    fill: {
      extra: {
        label: "🎨 Current Color",
        css: "fill: currentColor !important;",
        meta: "fill: currentColor"
      }
    }
  };

  function declFor(group, token) {
    if (group === "text") return `color: var(--${token}) !important;`;
    if (group === "border") return `border-color: var(--${token}) !important;`;
    if (group === "fill") return `fill: var(--${token}) !important;`;

    let d = `background-color: var(--${token}) !important;`;
    if (token === "primary") d += " color: var(--on_primary) !important;";
    else if (token === "primary_container") d += " color: var(--on_primary_container) !important;";
    else if (token === "secondary") d += " color: var(--on_secondary) !important;";
    else if (token === "secondary_container") d += " color: var(--on_secondary_container) !important;";
    else if (token === "tertiary") d += " color: var(--on_tertiary) !important;";
    else if (token === "tertiary_container") d += " color: var(--on_tertiary_container) !important;";
    else if (token === "error") d += " color: var(--on_error) !important;";
    else if (token.startsWith("surface")) d += " color: var(--on_surface) !important;";
    return d;
  }

  function important(text) {
    return text.split(";").map((d) => d.trim()).filter(Boolean)
      .map((d) => (/!important$/i.test(d) ? d : d + " !important") + ";").join(" ");
  }

  function getElementVars(elm) {
    if (!elm || elm.nodeType !== 1) return [];
    const cs = getComputedStyle(elm);
    const foundVars = [];
    const seen = new Set();

    const addVar = (prop) => {
      if (!prop.startsWith("--") || SKIP_VAR_PREFIXES.test(prop) || seen.has(prop)) return;
      const v = cs.getPropertyValue(prop).trim();
      if (v) {
        seen.add(prop);
        foundVars.push({ name: prop, value: v });
      }
    };

    // 1. Detect variables embedded inside Tailwind class names (e.g. bg-(--sidebar-surface-primary))
    for (const cls of elm.classList) {
      const m1 = cls.match(/^[a-z]+-\(--([a-zA-Z0-9_-]+)\)$/);
      if (m1) addVar("--" + m1);
      const m2 = cls.match(/^[a-z]+-token-([a-zA-Z0-9_-]+)$/);
      if (m2) addVar("--" + m2);
    }

    // 2. Detect variables declared inline or via stylesheets
    if (elm.style) {
      for (const p of elm.style) addVar(p);
    }

    try {
      for (const sheet of document.styleSheets) {
        try {
          for (const r of sheet.cssRules) {
            if (r.selectorText && elm.matches(r.selectorText) && r.style) {
              for (const p of r.style) addVar(p);
            }
          }
        } catch (_) {}
      }
    } catch (_) {}

    return foundVars;
  }

  // ─── Live styles on target page ───────────────────────────────────────────
  const liveStyle = document.createElement("style");
  const hoverStyle = document.createElement("style");
  function mountStyles() {
    if (!liveStyle.isConnected) (document.head || document.documentElement).append(liveStyle, hoverStyle);
  }
  function renderLive() { mountStyles(); liveStyle.textContent = S.rules.map(ruleCss).join("\n"); }
  function setHover(css) { mountStyles(); hoverStyle.textContent = css || ""; }

  // ─── Shadow UI ────────────────────────────────────────────────────────────
  const UI_CSS = [
    ":host { all: initial !important; display: block !important; position: fixed !important; top: 0 !important; left: 0 !important; width: 0 !important; height: 0 !important; overflow: visible !important; z-index: 2147483647 !important; pointer-events: none !important; isolation: isolate !important; }",
    "* { box-sizing: border-box; }",
    ".mask { position: fixed; z-index: 2147483646; display: none; pointer-events: none !important; border-radius: 4px; outline: 2px dashed #e6c280; box-shadow: 0 0 0 200vmax rgba(18, 15, 12, 0.6); }",
    ".panel { position: fixed; z-index: 2147483647; pointer-events: auto; background: #191614; color: #f5ebe0; border: 1px solid #d4a359; border-radius: 10px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.85); font: 12px/1.4 system-ui, sans-serif; user-select: none; }",
    ".bar { top: 12px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 8px; padding: 6px 10px; white-space: nowrap; cursor: grab; touch-action: none; max-width: calc(100vw - 24px); }",
    ".grip { opacity: 0.5; padding: 0 2px; cursor: grab; }",
    ".title { font-weight: 700; color: #e6c280; }",
    ".info { max-width: 340px; overflow: hidden; text-overflow: ellipsis; color: #c4b8aa; font: 11px ui-monospace, monospace; }",
    ".state { font-size: 11px; color: #c4b8aa; } .state.ok { color: #81c784; } .state.err { color: #e57373; } .state.warn { color: #e6c280; }",
    "button { font: inherit; color: #f5ebe0; background: #2d2722; border: 1px solid #3d342c; border-radius: 6px; padding: 4px 8px; cursor: pointer; white-space: nowrap; }",
    "button:hover:not(:disabled) { border-color: #d4a359; } button:disabled { opacity: 0.4; cursor: default; }",
    "button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid #e6c280; outline-offset: 1px; }",
    ".x { background: #b8545e; border-color: #b8545e; color: #fff; font-weight: 700; }",
    ".grow { flex: 1; }",
    ".dlg { top: 64px; right: 16px; width: 420px; max-width: calc(100vw - 32px); max-height: calc(100vh - 96px); overflow: auto; padding: 12px; outline: none; transition: opacity 0.15s; }",
    ".dlg.ghost:not(:hover):not(:focus-within) { opacity: 0.25; }",
    ".head { display: flex; align-items: center; gap: 6px; padding-bottom: 8px; margin-bottom: 8px; border-bottom: 1px solid #3d342c; cursor: grab; touch-action: none; }",
    ".head .title { flex: 1; }",
    ".row { display: flex; align-items: center; gap: 6px; margin: 6px 0; }",
    ".lbl { flex: none; width: 68px; color: #c4b8aa; font-size: 11px; }",
    ".tag { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #e6c280; font: 11px ui-monospace, monospace; }",
    "input[type=range] { flex: 1; accent-color: #e6c280; margin: 0; }",
    "select, input[type=text] { flex: 1; min-width: 0; font: 11px ui-monospace, monospace; color: #f5ebe0; background: #25201c; border: 1px solid #3d342c; border-radius: 6px; padding: 5px 6px; user-select: text; }",
    ".seg { flex: 1; display: flex; } .seg button { flex: 1; border-radius: 0; } .seg button:first-child { border-radius: 6px 0 0 6px; } .seg button:last-child { border-radius: 0 6px 6px 0; }",
    ".seg button[aria-pressed=true] { background: #e6c280; border-color: #e6c280; color: #191614; font-weight: 700; }",
    ".grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin: 8px 0; max-height: 230px; overflow-y: auto; }",
    ".grid button { display: flex; align-items: center; gap: 7px; text-align: left; padding: 4px 7px; }",
    ".sw { flex: none; width: 13px; height: 13px; border-radius: 50%; border: 1px solid #55493d; }",
    ".hint { margin: 8px 0 0; color: #8f857a; font-size: 10.5px; }",
    ".drawer { bottom: 16px; right: 16px; width: 390px; max-width: calc(100vw - 32px); max-height: 60vh; padding: 12px; display: flex; flex-direction: column; }",
    ".list { overflow: auto; display: flex; flex-direction: column; gap: 4px; }",
    ".item { display: flex; align-items: center; gap: 6px; padding: 4px 6px; background: #25201c; border: 1px solid #3d342c; border-radius: 6px; }",
    ".item:hover { border-color: #d4a359; }",
    ".item .sel { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font: 11px ui-monospace, monospace; }",
    ".item .meta { flex: none; color: #e6c280; font-size: 10.5px; }",
    ".item button { padding: 1px 6px; }"
  ].join("\n");

  const BAR_HTML = [
    "<span class='grip' aria-hidden='true'>⠿</span>",
    "<span class='title'>🎯 Dusky picker</span>",
    "<span class='info' id='binfo'></span>",
    "<span class='state' id='bstate'></span>",
    "<button id='bundo' title='Undo (Ctrl+Z)'>↶</button>",
    "<button id='bredo' title='Redo (Ctrl+Shift+Z)'>↷</button>",
    "<button id='brules' title='Rules saved for this site'>Rules</button>",
    "<button id='bexit' class='x' title='Stop picking (Esc)'>✕ Exit</button>"
  ].join("");

  const DIALOG_HTML = [
    "<div class='head' id='dhead'>",
    "<span class='grip' aria-hidden='true'>⠿</span>",
    "<span class='title'>🎨 Theme this element</span>",
    "<button id='dghost' title='See-through while pointer is elsewhere' aria-pressed='false'>👁</button>",
    "<button id='dclose' title='Close (Esc)'>✕</button>",
    "</div>",
    "<div class='row'><span class='lbl'>Element</span><span class='tag' id='dtag'></span></div>",
    "<div class='row'><span class='lbl'>Depth</span>",
    "<button id='dchild' title='Down, towards hovered target (↓)'>↓ child</button>",
    "<input type='range' id='dslider' min='0' max='0' value='0' aria-label='DOM depth'>",
    "<button id='dparent' title='Up, towards parent container (↑)'>↑ parent</button>",
    "</div>",
    "<div class='row' id='dmode-row'><span class='lbl'>Target</span>",
    "<div class='seg' id='dmode-seg' role='group' aria-label='Target Mode'>",
    "<button data-mode='selector' aria-pressed='true'>Element Selector</button>",
    "<button data-mode='variable' aria-pressed='false' id='dmode-var-btn'>CSS Variable</button>",
    "</div></div>",
    "<div class='row' id='dsel-row'><span class='lbl'>Selector</span><select id='dsel' aria-label='CSS selector'></select></div>",
    "<div class='row' id='dvar-row' style='display:none;'><span class='lbl'>Variable</span><select id='dvar' aria-label='CSS variable to map'></select></div>",
    "<div class='row' id='dprop-row'><span class='lbl'>Property</span>",
    "<div class='seg' id='dseg' role='group' aria-label='Property'>",
    "<button data-group='bg' aria-pressed='true'>Background</button>",
    "<button data-group='text' aria-pressed='false'>Text</button>",
    "<button data-group='border' aria-pressed='false'>Border</button>",
    "<button data-group='fill' aria-pressed='false' id='dfill-btn'>Fill (SVG)</button>",
    "</div></div>",
    "<div class='grid' id='dgrid'></div>",
    "<div class='row'><button id='dextra' class='grow'></button>",
    "<button id='dhide' class='x grow' title='display: none — Shift+click on page does this'>🙈 Hide element</button></div>",
    "<div class='row'><input type='text' id='dcustom' placeholder='custom CSS, e.g. border-radius: 8px; opacity: .9' aria-label='Custom CSS'>",
    "<button id='dapply'>Apply</button></div>",
    "<p class='hint' id='dhint'>Hover swatch to preview · click to save · ↑ ↓ change depth · Esc closes</p>"
  ].join("");

  const DRAWER_HTML = [
    "<div class='head' id='rhead'>",
    "<span class='grip' aria-hidden='true'>⠿</span>",
    "<span class='title'>📋 Rules for this site</span>",
    "<button id='rclear' class='x' title='Remove every rule (Ctrl+Z brings them back)'>Clear all</button>",
    "<button id='rclose' title='Close'>✕</button>",
    "</div>",
    "<div class='list' id='rlist'></div>",
    "<p class='hint'>Hover a rule to highlight elements · ✕ removes it · saved into picks block</p>"
  ].join("");

  const hostEl = document.createElement("dusky-picker");
  for (const [prop, value] of [
    ["all", "initial"], ["display", "block"], ["position", "fixed"],
    ["top", "0"], ["left", "0"], ["width", "0"], ["height", "0"],
    ["overflow", "visible"], ["z-index", "2147483647"],
    ["pointer-events", "none"], ["isolation", "isolate"],
  ]) {
    try { hostEl.style.setProperty(prop, value, "important"); } catch (_) {}
  }

  const root = hostEl.attachShadow({ mode: "closed" });
  root.innerHTML = "<style>" + UI_CSS + "</style><div class='mask' id='mask'></div>";
  const q = (id) => root.getElementById(id);

  const isOurs = (e) => {
    try {
      if (e.composedPath().includes(hostEl)) return true;
    } catch (_) {}
    try {
      const t = e.target;
      if (t === hostEl) return true;
      if (t instanceof Node && t.getRootNode() === root) return true;
    } catch (_) {}
    return false;
  };

  let bar = null, dialog = null, drawer = null;

  function el(tag, attrs, ...children) {
    const n = document.createElement(tag);
    for (const k in attrs) {
      const v = attrs[k];
      if (k === "text") n.textContent = v;
      else if (k === "class") n.className = v;
      else if (k === "style") Object.assign(n.style, v);
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "disabled") n.disabled = !!v;
      else n.setAttribute(k, v);
    }
    n.append(...children);
    return n;
  }

  function drag(panel, handle, onMove) {
    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button, input, select, textarea, a, [contenteditable]")) return;
      const r = panel.getBoundingClientRect();
      const ox = e.clientX - r.left, oy = e.clientY - r.top;
      const w = r.width, h = r.height;
      const move = (ev) => {
        const x = Math.min(Math.max(0, ev.clientX - ox), Math.max(0, innerWidth - w));
        const y = Math.min(Math.max(0, ev.clientY - oy), Math.max(0, innerHeight - h));
        Object.assign(panel.style, { left: x + "px", top: y + "px", right: "auto", bottom: "auto", transform: "none" });
        if (onMove) onMove(x, y);
      };
      const stop = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
        try { if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId); } catch (_) {}
      };
      try { handle.setPointerCapture(e.pointerId); } catch (_) {}
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
      e.preventDefault();
      e.stopPropagation();
    });
  }

  function drawMask() {
    const m = q("mask"), t = target();
    if (!t || !t.isConnected) { m.style.display = "none"; return; }
    const r = t.getBoundingClientRect();
    Object.assign(m.style, { display: "block", left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
  }
  function scheduleMask() {
    if (!S.raf) S.raf = requestAnimationFrame(() => { S.raf = 0; drawMask(); });
  }

  // ─── Precision Filter: Blacklist Tailwind Utilities & Dynamic IDs ─────────
  const SKIP_CLASS = /^(is-|has-|js-|dusky)|^(active|selected|open|hover|focus|focused|visible|hidden|show|shown|collapsed|expanded|disabled|checked|current)$/;
  const HASHY = /^(css|sc|jsx|jss|svelte|emotion)-|^_[a-z0-9]+$|__[a-z0-9]{5,}$|^[^-_]*\d[^-_]*$/i;
  const HASHY_ID = /^(radix|aria|headlessui|react-select|__next)-|^:[a-z0-9]+:$/i;
  const TAILWIND_UTILITY = /^(flex|grid|block|inline|hidden|grow|shrink|relative|absolute|fixed|sticky|static|box-border|border-box|z-\d+|w-.*|h-.*|min-w-.*|max-w-.*|min-h-.*|max-h-.*|p-.*|px-.*|py-.*|pt-.*|pb-.*|pl-.*|pr-.*|m-.*|mx-.*|my-.*|mt-.*|mb-.*|ml-.*|mr-.*|col-.*|row-.*|items-.*|justify-.*|content-.*|self-.*|gap-.*|space-.*|cursor-.*|select-.*|touch:.*|last:.*|first:.*|group\/.*|peer\/.*|focus:.*|hover:.*|dark:.*|@.*|\[.*\]|bg-\(.*|bg-token-.*|text-token-.*|whitespace-.*|text-pretty)$/i;

  function goodClasses(n) {
    const all = [...n.classList].filter((c) =>
      !SKIP_CLASS.test(c) &&
      !HASHY.test(c) &&
      !TAILWIND_UTILITY.test(c) &&
      !c.includes(":") &&
      !c.includes("(") &&
      !c.includes("/")
    );
    return all.slice(0, 3);
  }

  const simple = (n) => n.localName + goodClasses(n).map((c) => "." + CSS.escape(c)).join("");
  const describe = (n) => n.localName + (n.id && !HASHY_ID.test(n.id) ? "#" + n.id : "") + goodClasses(n).map((c) => "." + c).join("");
  const attrStr = (v) => '"' + v.replace(/["\\]/g, "\\$&") + '"';

  function pathSel(n) {
    const parts = [];
    for (let cur = n; cur && cur !== document.body && cur !== document.documentElement && parts.length < 3; cur = cur.parentElement) {
      if (cur.id && !HASHY.test(cur.id) && !HASHY_ID.test(cur.id)) { parts.unshift("#" + CSS.escape(cur.id)); break; }
      let s = simple(cur);
      const siblings = cur.parentElement ? [...cur.parentElement.children] : [];
      if (siblings.some((c) => c !== cur && c.matches(s))) {
        s += ":nth-of-type(" + (siblings.filter((c) => c.localName === cur.localName).indexOf(cur) + 1) + ")";
      }
      parts.unshift(s);
    }
    return parts.join(" > ") || n.localName;
  }

  function candidates(n) {
    if (!n || n === document.documentElement) return [{ sel: "html", count: 1 }];
    if (n === document.body) return [{ sel: "body", count: 1 }];
    const out = [];
    if (n.id && !HASHY.test(n.id) && !HASHY_ID.test(n.id)) out.push("#" + CSS.escape(n.id));
    const s = simple(n);
    if (s !== n.localName) out.push(s);
    for (const a of ["role", "aria-label", "data-testid", "name"]) {
      const v = n.getAttribute(a);
      if (v && v.length < 60) out.push(n.localName + "[" + a + "=" + attrStr(v) + "]");
    }
    out.push(pathSel(n), n.localName);
    const seen = new Set();
    return out.filter((sel) => !seen.has(sel) && seen.add(sel)).map((sel) => {
      let count = 0;
      try { count = document.querySelectorAll(sel).length; } catch (_) {}
      return { sel, count };
    });
  }

  function buildBar() {
    bar = el("section", { class: "panel bar", role: "toolbar", "aria-label": "Dusky picker" });
    bar.innerHTML = BAR_HTML;
    root.append(bar);
    drag(bar, bar);
    q("bundo").addEventListener("click", undo);
    q("bredo").addEventListener("click", redo);
    q("brules").addEventListener("click", toggleDrawer);
    q("bexit").addEventListener("click", () => setActive(false));
    if (S.note) setState("⚠ not saving: " + S.note, "err");
    else if (!paletteLoaded()) setState("⚠ live palette variables not loaded on this page", "warn");
    refreshBar();
  }

  function refreshBar() {
    if (!bar) return;
    const t = target();
    q("binfo").textContent = t
      ? "<" + describe(t) + ">" + (S.stack.length > 1 ? "  · depth " + S.depth + "/" + (S.stack.length - 1) : "")
      : "Hover element · click to theme · Shift+click hides · Esc exits";
    q("bundo").disabled = !S.undo.length;
    q("bredo").disabled = !S.redo.length;
    q("brules").textContent = "Rules (" + S.rules.length + ")";
  }

  function setState(text, cls) {
    const s = q("bstate");
    if (s) { s.textContent = text; s.className = "state " + cls; }
  }

  const selected = () => (dialog ? q("dsel").value : candidates(target()).at(0).sel);
  function outline(extra) {
    if (S.targetMode === "variable") {
      setHover("");
      return;
    }
    const sel = selected();
    setHover(sel + " { outline: 2px dashed #e6c280 !important; outline-offset: -2px !important; }" + (extra ? "\n" + sel + " { " + extra + " }" : ""));
  }

  function openDialog() {
    if (dialog) dialog.remove();
    dialog = el("section", { class: "panel dlg", role: "dialog", "aria-label": "Theme this element", tabindex: "-1" });
    dialog.innerHTML = DIALOG_HTML;
    if (S.dialogPos) Object.assign(dialog.style, { left: S.dialogPos.x + "px", top: S.dialogPos.y + "px", right: "auto" });
    root.append(dialog);
    drag(dialog, q("dhead"), (x, y) => { S.dialogPos = { x, y }; });

    const t = target();
    S.elementVars = getElementVars(t);
    const isSvg = t && (t.closest("svg") || t.tagName.toLowerCase() === "svg" || t.tagName.toLowerCase() === "path");

    if (isSvg) {
      S.group = "fill";
    } else {
      S.group = "bg";
    }

    q("dclose").addEventListener("click", closeDialog);
    q("dghost").addEventListener("click", (e) => {
      const on = dialog.classList.toggle("ghost");
      e.currentTarget.setAttribute("aria-pressed", String(on));
    });
    q("dslider").addEventListener("input", (e) => { S.depth = Number(e.target.value); retarget(); });
    q("dchild").addEventListener("click", () => step(-1));
    q("dparent").addEventListener("click", () => step(1));
    q("dsel").addEventListener("change", () => outline());

    const modeSeg = q("dmode-seg");
    const selRow = q("dsel-row");
    const varRow = q("dvar-row");
    const propRow = q("dprop-row");
    const varBtn = q("dmode-var-btn");

    if (S.elementVars.length === 0) {
      varBtn.disabled = true;
      varBtn.title = "No active CSS custom properties detected on this element";
      S.targetMode = "selector";
    } else {
      varBtn.disabled = false;
      varBtn.title = `Found ${S.elementVars.length} variable(s) on this element`;
    }

    modeSeg.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-mode]");
      if (!b || b.disabled) return;
      S.targetMode = b.dataset.mode;
      for (const x of modeSeg.children) x.setAttribute("aria-pressed", String(x === b));
      if (S.targetMode === "variable") {
        selRow.style.display = "none";
        propRow.style.display = "none";
        varRow.style.display = "flex";
      } else {
        selRow.style.display = "flex";
        propRow.style.display = "flex";
        varRow.style.display = "none";
      }
      outline();
    });

    const dseg = q("dseg");
    for (const x of dseg.children) x.setAttribute("aria-pressed", String(x.dataset.group === S.group));

    dseg.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-group]");
      if (!b) return;
      S.group = b.dataset.group;
      for (const x of dseg.children) x.setAttribute("aria-pressed", String(x === b));
      q("dextra").textContent = GROUPS[S.group].extra.label;
      outline();
    });

    const grid = q("dgrid");
    for (const [token, label] of TOKENS) {
      const b = el("button", { title: "var(--" + token + ")" },
        el("i", { class: "sw", style: { background: "var(--" + token + ", transparent)" } }),
        el("span", { text: label }));
      b.addEventListener("mouseenter", () => {
        if (S.targetMode === "selector") outline(declFor(S.group, token));
      });
      b.addEventListener("mouseleave", () => outline());
      b.addEventListener("click", () => {
        if (S.targetMode === "variable") {
          const vname = q("dvar").value;
          if (vname) applyVar(vname, token);
        } else {
          apply(declFor(S.group, token), S.group + ": " + token);
        }
      });
      grid.append(b);
    }

    const extra = q("dextra");
    extra.textContent = GROUPS[S.group].extra.label;
    extra.addEventListener("mouseenter", () => {
      if (S.targetMode === "selector") outline(GROUPS[S.group].extra.css);
    });
    extra.addEventListener("mouseleave", () => outline());
    extra.addEventListener("click", () => apply(GROUPS[S.group].extra.css, GROUPS[S.group].extra.meta));

    const hide = q("dhide");
    hide.addEventListener("mouseenter", () => outline("display: none !important;"));
    hide.addEventListener("mouseleave", () => outline());
    hide.addEventListener("click", () => apply("display: none !important;", "hidden"));

    const custom = q("dcustom");
    const applyCustom = () => { const tVal = custom.value.trim(); if (tVal) apply(important(tVal), "custom"); };
    q("dapply").addEventListener("click", applyCustom);
    custom.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); applyCustom(); } });

    refreshDialog();
    dialog.focus({ preventScroll: true });
  }

  function refreshDialog() {
    const t = target();
    if (!dialog || !t) return;
    q("dtag").textContent = "<" + describe(t) + ">";
    const sl = q("dslider");
    sl.max = String(Math.max(0, S.stack.length - 1));
    sl.value = String(S.depth);
    q("dchild").disabled = S.depth === 0;
    q("dparent").disabled = S.depth >= S.stack.length - 1;

    const sel = q("dsel");
    sel.textContent = "";
    for (const c of candidates(t)) {
      sel.append(el("option", { value: c.sel, text: c.sel + "   — " + c.count + (c.count === 1 ? " match" : " matches") }));
    }

    const dvar = q("dvar");
    dvar.textContent = "";
    for (const v of S.elementVars) {
      dvar.append(el("option", { value: v.name, text: `${v.name} (${v.value})` }));
    }

    outline();
  }

  function closeDialog() {
    if (dialog) dialog.remove();
    dialog = null;
    S.locked = false;
    setHover("");
  }

  function apply(decl, meta) {
    addRule(selected(), decl, meta);
    closeDialog();
  }

  function applyVar(varName, token) {
    addRule(":root", `${varName}: var(--${token}) !important;`, `var: ${varName} -> ${token}`);
    closeDialog();
  }

  function toggleDrawer() {
    if (drawer) { drawer.remove(); drawer = null; return; }
    drawer = el("section", { class: "panel drawer", role: "dialog", "aria-label": "Rules for this site" });
    drawer.innerHTML = DRAWER_HTML;
    root.append(drawer);
    drag(drawer, q("rhead"));
    q("rclose").addEventListener("click", toggleDrawer);
    q("rclear").addEventListener("click", () => { if (S.rules.length) { snapshot(); S.rules = []; commit(); } });
    refreshDrawer();
  }

  function refreshDrawer() {
    if (!drawer) return;
    const list = q("rlist");
    list.textContent = "";
    if (!S.rules.length) {
      list.append(el("p", { class: "hint", text: "No rules yet — click any element on the page." }));
      return;
    }
    S.rules.forEach((r, i) => {
      const item = el("div", { class: "item" },
        el("span", { class: "sel", title: ruleLine(r), text: r.raw !== undefined ? r.raw : r.sel }),
        el("span", { class: "meta", text: r.raw !== undefined ? "manual" : r.meta }),
        el("button", { title: "Remove this rule", text: "✕", onclick: () => { snapshot(); S.rules.splice(i, 1); commit(); } }));
      if (r.raw === undefined) {
        item.addEventListener("mouseenter", () => setHover(r.sel + " { outline: 2px dashed #e6c280 !important; outline-offset: -2px !important; }"));
        item.addEventListener("mouseleave", () => (dialog ? outline() : setHover("")));
      }
      list.append(item);
    });
  }

  function snapshot() {
    S.undo.push(S.rules.slice());
    if (S.undo.length > 100) S.undo.shift();
    S.redo = [];
  }

  function addRule(sel, decl, meta) {
    const [group = ""] = ((meta || "").split(":").at(0) || "").trim().split(" ");
    let i = -1;
    if (group === "var") {
      const varMatch = decl.match(/^(--[a-zA-Z0-9_-]+):/);
      const [, varName = ""] = varMatch || [];
      i = S.rules.findIndex((r) => r.decl && r.decl.startsWith(varName + ":"));
    } else if (group !== "custom") {
      i = S.rules.findIndex((r) => r.sel === sel && (((r.meta || "").split(":").at(0) || "").trim() === group));
    }
    snapshot();
    const rule = { sel, decl, meta };
    if (i >= 0) S.rules[i] = rule; else S.rules.push(rule);
    commit();
  }

  function undo() { if (S.undo.length) { S.redo.push(S.rules); S.rules = S.undo.pop(); commit(); } }
  function redo() { if (S.redo.length) { S.undo.push(S.rules); S.rules = S.redo.pop(); commit(); } }
  function commit() { renderLive(); refreshBar(); refreshDrawer(); persist(); }

  async function persist() {
    const seq = ++S.saveSeq;
    setState("saving…", "");
    const body = S.rules.map((r) => "    " + ruleLine(r)).join("\n");
    const reply = await browser.runtime.sendMessage({ type: "splice", region: "picks", body })
      .catch((e) => ({ ok: false, error: String((e && e.message) || e) }));
    if (seq !== S.saveSeq) return;
    if (reply && reply.ok) setState("✓ saved " + String(reply.path).split("/").pop(), "ok");
    else setState("⚠ not saved: " + ((reply && reply.error) || "no reply"), "err");
  }

  async function hydrate() {
    if (S.hydrated) return;
    const reply = await browser.runtime.sendMessage({ type: "read" })
      .catch((e) => ({ ok: false, error: String((e && e.message) || e) }));
    if (reply && reply.ok) {
      S.hydrated = true;
      S.note = "";
      S.rules = String(reply.picks || "").split("\n").map((l) => l.trim()).filter(Boolean).map(parseRule);
    } else {
      S.note = (reply && reply.error) || "cannot reach native host";
    }
  }

  function setStack(elm) {
    const chain = [];
    for (let n = elm; n && n.nodeType === 1; n = n.parentElement) chain.push(n);
    S.stack = chain;
    S.depth = 0;
    retarget();
  }
  function retarget() { drawMask(); refreshBar(); refreshDialog(); }
  function step(delta) {
    if (!S.stack.length) return;
    S.depth = Math.min(Math.max(0, S.depth + delta), S.stack.length - 1);
    retarget();
  }
  function typing() {
    const a = root.activeElement || document.activeElement;
    return !!a && (a.isContentEditable || /^(input|select|textarea)$/i.test(a.tagName));
  }

  function onOver(e) { if (!S.locked && !isOurs(e)) setStack(e.target); }
  function onPointerDown(e) {
    if (isOurs(e)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }
  function onClick(e) {
    if (isOurs(e)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (!S.stack.length) setStack(e.target);
    if (e.shiftKey) { addRule(candidates(target()).at(0).sel, "display: none !important;", "hidden"); return; }
    S.locked = true;
    openDialog();
  }
  function onKey(e) {
    const k = e.key, ctrl = e.ctrlKey || e.metaKey;
    if (k === "Escape") { if (dialog) closeDialog(); else if (drawer) toggleDrawer(); else setActive(false); }
    else if (typing()) return;
    else if (k === "ArrowUp" || k === "ArrowDown") { if (!S.stack.length) return; step(k === "ArrowUp" ? 1 : -1); }
    else if (ctrl && !e.altKey && k.toLowerCase() === "z") { if (e.shiftKey) redo(); else undo(); }
    else if (ctrl && !e.altKey && k.toLowerCase() === "y") redo();
    else return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }
  const LISTENERS = [["mouseover", onOver], ["pointerdown", onPointerDown], ["click", onClick], ["keydown", onKey]];

  async function setActive(on) {
    if (on === S.active) return;
    S.active = on;
    if (on) {
      await hydrate();
      document.documentElement.append(hostEl);
      buildBar();
      renderLive();
      for (const [type, fn] of LISTENERS) window.addEventListener(type, fn, true);
      window.addEventListener("scroll", scheduleMask, { capture: true, passive: true });
      window.addEventListener("resize", scheduleMask, { passive: true });
    } else {
      closeDialog();
      if (drawer) toggleDrawer();
      if (bar) bar.remove();
      bar = null;
      for (const [type, fn] of LISTENERS) window.removeEventListener(type, fn, true);
      window.removeEventListener("scroll", scheduleMask, { capture: true });
      window.removeEventListener("resize", scheduleMask);
      S.stack = [];
      S.depth = 0;
      S.locked = false;
      drawMask();
      hostEl.remove();
    }
  }

  browser.runtime.onMessage.addListener((msg) => {
    switch (msg && msg.type) {
      case "ping":
        return Promise.resolve({ ok: true, active: S.active, rules: S.rules.length });
      case "scan":
        try { return Promise.resolve(scan()); }
        catch (e) { return Promise.resolve({ ok: false, error: "Scan failed: " + ((e && e.message) || e) }); }
      case "picker":
        return setActive(msg.enable === undefined ? !S.active : !!msg.enable).then(() => ({ ok: true, active: S.active }));
      case "reset":
        S.rules = []; S.undo = []; S.redo = []; S.hydrated = true; S.note = "";
        renderLive(); refreshBar(); refreshDrawer();
        return Promise.resolve({ ok: true });
      default:
        return undefined;
    }
  });
})();
