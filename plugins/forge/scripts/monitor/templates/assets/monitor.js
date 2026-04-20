/* forge monitor 共通 SSE クライアント (v3.0)
 *
 * 各テンプレートは以下のいずれかで render 関数を登録する:
 *   window.Forge.render = function(data) { ... }
 *
 * Forge.render は /session のレスポンス(session/plan/refs 等)を受け取り
 * DOM を更新する。render 未登録の場合は fallbackRender が使われる。
 */

(function () {
  "use strict";

  const API_SESSION = "/session";
  const API_SSE = "/sse";

  const Forge = {
    render: null,         // 各テンプレートが上書き
    onSessionEnd: null,   // 各テンプレートがオーバーライド可
    data: null,           // 直近の session データ
    state: {
      sseState: "connecting",
      lastUpdate: null,
      sessionEnded: false,
    },
  };

  window.Forge = Forge;

  // ── SSE 接続状態の表示 ────────────────────────────
  function setPulseState(state) {
    Forge.state.sseState = state;
    document.querySelectorAll("[data-role=sse-pulse]").forEach((el) => {
      el.dataset.state = state;
      el.textContent = pulseLabel(state);
    });
  }

  function pulseLabel(state) {
    switch (state) {
      case "live":    return "live";
      case "ended":   return "ended";
      case "error":   return "offline";
      default:        return "connecting";
    }
  }

  // ── /session 取得とレンダリング ───────────────────
  async function fetchAndRender() {
    try {
      const resp = await fetch(API_SESSION, { cache: "no-store" });
      if (!resp.ok) {
        console.warn("[forge] /session fetch failed:", resp.status);
        return;
      }
      const data = await resp.json();
      Forge.data = data;
      Forge.state.lastUpdate = new Date();
      renderTopbar(data);
      if (typeof Forge.render === "function") {
        try {
          Forge.render(data);
        } catch (e) {
          console.error("[forge] render error:", e);
        }
      } else {
        fallbackRender(data);
      }
    } catch (e) {
      console.warn("[forge] fetchAndRender error:", e);
    }
  }

  // ── topbar の skill / subtitle 更新 ───────────────
  function renderTopbar(data) {
    const skillEl = document.querySelector("[data-role=skill-tag]");
    if (skillEl) {
      skillEl.textContent = data.skill || "session";
    }
    const subtitleEl = document.querySelector("[data-role=session-subtitle]");
    if (subtitleEl && data.session_dir) {
      const basename = data.session_dir.split("/").pop();
      subtitleEl.textContent = basename;
    }
  }

  // ── テンプレート未実装時のフォールバック ─────────
  function fallbackRender(data) {
    const mount = document.querySelector("[data-role=main]");
    if (!mount) return;
    const files = Object.entries(data.files || {})
      .filter(([, v]) => v && v.exists)
      .map(([k]) => k);
    mount.innerHTML = `
      <div class="card">
        <h2 class="card__title">session</h2>
        <div class="card__body">
          <div class="muted mono">${escapeHtml(data.session_dir || "")}</div>
          <div style="margin-top: 0.75rem">
            <span class="muted">files:</span>
            ${files.map((f) => `<span class="badge">${escapeHtml(f)}</span>`).join(" ")}
          </div>
        </div>
      </div>
    `;
  }

  // ── session_end バナー ────────────────────────────
  function showSessionEndBanner(message) {
    if (Forge.state.sessionEnded) return;
    Forge.state.sessionEnded = true;
    setPulseState("ended");

    const existing = document.querySelector(".session-end-banner");
    if (existing) return;

    const banner = document.createElement("div");
    banner.className = "session-end-banner";
    banner.innerHTML = `
      <span class="status-dot status-dot--skipped"></span>
      <span class="session-end-banner__text">
        ${escapeHtml(message || "セッションが終了しました。")}
      </span>
    `;
    document.body.appendChild(banner);

    if (typeof Forge.onSessionEnd === "function") {
      try { Forge.onSessionEnd(); } catch (e) { console.error(e); }
    }
  }

  // ── SSE 接続 ──────────────────────────────────────
  function connectSSE() {
    if (!window.EventSource) {
      console.warn("[forge] EventSource not supported; polling fallback");
      setPulseState("error");
      // 5 秒ごとにポーリング
      setInterval(fetchAndRender, 5000);
      return;
    }

    const es = new EventSource(API_SSE);
    es.addEventListener("open", () => setPulseState("live"));
    es.addEventListener("error", () => {
      if (Forge.state.sessionEnded) return;
      setPulseState("error");
    });
    es.addEventListener("update", () => {
      setPulseState("live");
      fetchAndRender();
    });
    es.addEventListener("session_end", (ev) => {
      let payload = {};
      try {
        payload = JSON.parse(ev.data || "{}");
      } catch (_) { /* noop */ }
      showSessionEndBanner(payload.message);
      try { es.close(); } catch (_) { /* noop */ }
    });
  }

  // ── ユーティリティ ────────────────────────────────
  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  Forge.escapeHtml = escapeHtml;

  function formatTimestamp(ts) {
    if (!ts) return "";
    try {
      const d = new Date(ts);
      return d.toLocaleString();
    } catch (_) {
      return String(ts);
    }
  }
  Forge.formatTimestamp = formatTimestamp;

  // ── Markdown 軽量レンダラー(見出し / 段落 / コード) ─
  function renderMarkdown(src) {
    if (!src) return "";
    const lines = String(src).split("\n");
    const out = [];
    let inCode = false;
    let codeLang = "";
    let codeBuf = [];
    let para = [];

    function flushPara() {
      if (para.length) {
        out.push("<p>" + escapeHtml(para.join(" ")) + "</p>");
        para = [];
      }
    }

    for (const raw of lines) {
      const line = raw;
      if (inCode) {
        if (/^```\s*$/.test(line)) {
          out.push(
            `<pre><code class="lang-${escapeHtml(codeLang)}">` +
            escapeHtml(codeBuf.join("\n")) +
            "</code></pre>"
          );
          inCode = false;
          codeBuf = [];
          codeLang = "";
        } else {
          codeBuf.push(line);
        }
        continue;
      }
      const m = /^```(\w*)/.exec(line);
      if (m) {
        flushPara();
        inCode = true;
        codeLang = m[1] || "";
        continue;
      }
      if (/^\s*$/.test(line)) {
        flushPara();
        continue;
      }
      const h = /^(#{1,6})\s+(.*)$/.exec(line);
      if (h) {
        flushPara();
        const level = h[1].length;
        out.push(`<h${level}>${escapeHtml(h[2])}</h${level}>`);
        continue;
      }
      const li = /^\s*[-*]\s+(.*)$/.exec(line);
      if (li) {
        flushPara();
        out.push(`<li>${escapeHtml(li[1])}</li>`);
        continue;
      }
      para.push(line.trim());
    }
    if (inCode && codeBuf.length) {
      out.push("<pre><code>" + escapeHtml(codeBuf.join("\n")) + "</code></pre>");
    }
    flushPara();
    return out.join("\n");
  }
  Forge.renderMarkdown = renderMarkdown;

  // ── フィルタ / バッジ等のヘルパ ───────────────────
  function badge(label, variant) {
    const cls = variant ? `badge badge--${variant}` : "badge";
    return `<span class="${cls}">${escapeHtml(label)}</span>`;
  }
  Forge.badge = badge;

  function sevDot(severity) {
    const s = String(severity || "").toLowerCase();
    const known = new Set(["critical", "major", "minor"]);
    const cls = known.has(s) ? `sev-dot sev-dot--${s}` : "sev-dot";
    return `<span class="${cls}" title="${escapeHtml(s || "")}"></span>`;
  }
  Forge.sevDot = sevDot;

  function statusDot(status) {
    const s = String(status || "").toLowerCase();
    const known = new Set([
      "pending", "in_progress", "fixed", "skipped", "needs_review",
    ]);
    const cls = known.has(s) ? `status-dot status-dot--${s}` : "status-dot";
    return `<span class="${cls}" title="${escapeHtml(s || "")}"></span>`;
  }
  Forge.statusDot = statusDot;

  // ── 起動 ──────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    setPulseState("connecting");
    fetchAndRender();
    connectSSE();
  });
})();
