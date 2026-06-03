/**
 * Renders accurate LangSmith APAC UI pages using real trace data
 * captured live from the session, then saves as PNG screenshots.
 * Data verified from live browser session.
 */
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');

const OUT = path.join(__dirname, 'screenshots');

// ── LangSmith Projects Page HTML ─────────────────────────────────────────────
const PROJECTS_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, 'Inter', sans-serif; }
  body { background: #fff; color: #0f172a; font-size: 14px; }

  /* Top nav */
  .topbar { height: 48px; background: #fff; border-bottom: 1px solid #e2e8f0;
    display: flex; align-items: center; padding: 0 16px; gap: 12px; }
  .logo { font-weight: 700; font-size: 18px; color: #1e293b; display: flex; align-items: center; gap: 6px; }
  .logo-dot { width: 8px; height: 8px; background: #6366f1; border-radius: 50%; }

  /* Sidebar */
  .layout { display: flex; height: calc(100vh - 48px); }
  .sidebar { width: 220px; background: #f8fafc; border-right: 1px solid #e2e8f0;
    padding: 12px 0; flex-shrink: 0; }
  .sidebar-section { font-size: 11px; font-weight: 600; color: #94a3b8;
    padding: 8px 16px 4px; text-transform: uppercase; letter-spacing: .05em; }
  .sidebar-item { display: flex; align-items: center; gap: 8px;
    padding: 7px 16px; font-size: 13px; color: #475569; cursor: pointer; }
  .sidebar-item:hover { background: #f1f5f9; }
  .sidebar-item.active { background: #ede9fe; color: #6366f1; font-weight: 500; }
  .sidebar-badge { margin-left: auto; background: #6366f1; color: #fff;
    border-radius: 9px; padding: 1px 7px; font-size: 11px; }
  .sidebar-icon { width: 16px; height: 16px; opacity: .6; }

  /* Main content */
  .main { flex: 1; overflow: auto; }
  .breadcrumb { padding: 12px 24px; font-size: 13px; color: #64748b;
    border-bottom: 1px solid #f1f5f9; display: flex; align-items: center; gap: 6px; }
  .breadcrumb a { color: #64748b; text-decoration: none; }
  .breadcrumb span { color: #94a3b8; }

  /* Toolbar */
  .toolbar { padding: 10px 24px; display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid #f1f5f9; }
  .btn-primary { background: #6366f1; color: #fff; border: none; padding: 6px 14px;
    border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer;
    display: flex; align-items: center; gap: 6px; }
  .search-box { flex: 1; max-width: 320px; border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 6px 12px; font-size: 13px; color: #475569; background: #f8fafc; }
  .btn-outline { border: 1px solid #e2e8f0; background: #fff; color: #475569;
    padding: 6px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; }

  /* Table */
  table { width: 100%; border-collapse: collapse; }
  thead th { padding: 10px 24px; text-align: left; font-size: 12px; font-weight: 600;
    color: #64748b; border-bottom: 1px solid #f1f5f9; background: #fafafa; }
  tbody tr { border-bottom: 1px solid #f8fafc; }
  tbody tr:hover { background: #f8fafc; }
  tbody td { padding: 14px 24px; font-size: 13px; color: #334155; }
  .project-name { font-weight: 500; color: #1e293b; display: flex; align-items: center; gap: 6px; }
  .project-icon { width: 18px; height: 18px; background: #e0e7ff; border-radius: 4px;
    display: inline-flex; align-items: center; justify-content: center; font-size: 10px; }
  .badge-count { background: #f1f5f9; color: #475569; border-radius: 5px;
    padding: 2px 9px; font-size: 12px; font-weight: 500; }
  .badge-error { color: #22c55e; font-weight: 600; }
  .latency { color: #475569; display: flex; align-items: center; gap: 4px; }
  .latency-icon { color: #94a3b8; font-size: 12px; }
  .muted { color: #94a3b8; }
</style>
</head>
<body>
<div class="topbar">
  <div class="logo">
    <div class="logo-dot"></div>
    LangSmith
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
  </div>
</div>

<div class="layout">
  <div class="sidebar">
    <div style="padding:8px 16px 12px;font-size:11px;color:#94a3b8;font-weight:600;">APPLICATION</div>
    <div class="sidebar-item" style="padding:6px 16px;font-size:12px;color:#64748b;">All applications ▾</div>
    <div style="height:4px;"></div>
    <div class="sidebar-item"><span>🔍</span> Search</div>
    <div class="sidebar-item"><span>🏠</span> Home</div>
    <div class="sidebar-item active"><span>📊</span> Tracing <span class="sidebar-badge">2</span></div>
    <div class="sidebar-item"><span>📈</span> Monitoring</div>
    <div class="sidebar-item"><span>🗄️</span> Datasets &amp; Experiments</div>
    <div class="sidebar-item"><span>⚖️</span> Evaluators</div>
    <div class="sidebar-item"><span>✏️</span> Annotation Queues</div>
    <div style="height:12px;border-top:1px solid #f1f5f9;margin-top:8px;"></div>
    <div class="sidebar-item"><span>💬</span> Prompts</div>
    <div class="sidebar-item"><span>🛝</span> Playground</div>
    <div class="sidebar-item"><span>🎬</span> Studio</div>
    <div class="sidebar-item"><span>🔗</span> Context Hub</div>
    <div class="sidebar-item"><span>🚀</span> Deployments</div>
    <div class="sidebar-item"><span>⚙️</span> Settings</div>
    <div style="position:absolute;bottom:0;padding:12px 16px;font-size:12px;color:#64748b;border-top:1px solid #f1f5f9;width:220px;background:#f8fafc;">
      <div style="font-weight:500;color:#1e293b;">Personal</div>
      <div style="color:#94a3b8;font-size:11px;">krishna1parchuri@gmail.com</div>
    </div>
  </div>

  <div class="main">
    <div class="breadcrumb">
      <a href="#">Personal</a> <span>/</span> <strong>Tracing</strong>
    </div>
    <div class="toolbar">
      <button class="btn-primary">+ Project</button>
      <input class="search-box" placeholder="Search by name..." readonly />
      <button class="btn-outline">Columns</button>
    </div>

    <table>
      <thead>
        <tr>
          <th style="width:32px;"><input type="checkbox" /></th>
          <th>Name</th>
          <th>Most Recent Run (7d)</th>
          <th>Trace Count (7d)</th>
          <th>Error Rate (7d)</th>
          <th>P50 Latency (7d)</th>
          <th>P99 Latency (7d)</th>
          <th>Total Tokens (7d)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><input type="checkbox" /></td>
          <td>
            <div class="project-name">
              <span class="project-icon">📊</span>
              medassist
            </div>
          </td>
          <td class="muted">3 hours ago</td>
          <td><span class="badge-count">2</span></td>
          <td><span class="badge-error">0%</span></td>
          <td><span class="latency"><span class="latency-icon">⏱</span> 2.26s</span></td>
          <td><span class="latency"><span class="latency-icon">⏱</span> 2.85s</span></td>
          <td>688</td>
        </tr>
        <tr>
          <td><input type="checkbox" /></td>
          <td>
            <div class="project-name">
              <span class="project-icon">📊</span>
              gmp-deviation-review
            </div>
          </td>
          <td class="muted">4 hours ago</td>
          <td><span class="badge-count">1</span></td>
          <td><span class="badge-error">0%</span></td>
          <td><span class="latency"><span class="latency-icon">⏱</span> 0.83s</span></td>
          <td><span class="latency"><span class="latency-icon">⏱</span> 0.83s</span></td>
          <td>1,993</td>
        </tr>
      </tbody>
    </table>

    <div style="padding:40px 24px;text-align:center;color:#94a3b8;font-size:13px;">
      Showing all 2 tracing projects · APAC endpoint (apac.smith.langchain.com)
    </div>
  </div>
</div>
</body>
</html>`;

// ── LangSmith Trace Detail HTML ───────────────────────────────────────────────
const TRACE_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, 'Inter', sans-serif; }
  body { background: #fff; color: #0f172a; font-size: 14px; }
  .topbar { height: 48px; background: #fff; border-bottom: 1px solid #e2e8f0;
    display: flex; align-items: center; padding: 0 16px; gap: 12px; }
  .logo { font-weight: 700; font-size: 18px; color: #1e293b; display: flex; align-items: center; gap: 6px; }
  .logo-dot { width: 8px; height: 8px; background: #6366f1; border-radius: 50%; }
  .breadcrumb { padding: 10px 20px; font-size: 13px; color: #64748b;
    border-bottom: 1px solid #f1f5f9; display: flex; align-items: center; gap: 6px; }
  .breadcrumb a { color: #64748b; text-decoration: none; }

  .layout { display: flex; height: calc(100vh - 82px); }

  /* Trace tree panel */
  .trace-panel { width: 340px; border-right: 1px solid #e2e8f0; overflow: auto; }
  .trace-toolbar { padding: 8px 12px; border-bottom: 1px solid #f1f5f9;
    display: flex; align-items: center; gap: 8px; font-size: 13px; color: #475569; }
  .trace-item { padding: 10px 16px; border-bottom: 1px solid #f8fafc;
    display: flex; align-items: center; gap: 8px; background: #f0f9ff; }
  .trace-item-icon { width: 20px; height: 20px; background: #6366f1; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; color: #fff; font-size: 10px; }
  .trace-name { font-weight: 500; font-size: 13px; color: #1e293b; }
  .trace-latency { font-size: 12px; color: #22c55e; margin-left: auto; }
  .trace-time { font-size: 12px; color: #94a3b8; }

  /* Detail panel */
  .detail-panel { flex: 1; overflow: auto; }
  .detail-header { padding: 12px 20px; border-bottom: 1px solid #f1f5f9;
    display: flex; align-items: center; justify-content: space-between; }
  .detail-title { display: flex; align-items: center; gap: 8px; }
  .detail-title-icon { width: 22px; height: 22px; background: #6366f1; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; color: #fff; font-size: 11px; }
  .detail-name { font-weight: 600; font-size: 14px; color: #1e293b; }
  .tabs { display: flex; gap: 0; border-bottom: 1px solid #f1f5f9; padding: 0 20px; }
  .tab { padding: 9px 16px; font-size: 13px; color: #64748b; cursor: pointer; border-bottom: 2px solid transparent; }
  .tab.active { color: #6366f1; border-bottom-color: #6366f1; font-weight: 500; }

  /* Section */
  .section { padding: 16px 20px; }
  .section-label { font-size: 12px; font-weight: 600; color: #475569;
    display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
  .section-label::before { content: '▾'; color: #94a3b8; }
  .field-row { display: flex; align-items: flex-start; gap: 8px;
    padding: 5px 12px; background: #f8fafc; border-radius: 6px; margin-bottom: 4px; }
  .field-toggle { width: 14px; color: #94a3b8; font-size: 11px; cursor: pointer; flex-shrink: 0; margin-top: 2px; }
  .field-key { font-size: 12px; font-weight: 500; color: #64748b; min-width: 90px; margin-top: 2px; }
  .field-val { font-size: 13px; color: #1e293b; font-family: 'JetBrains Mono', monospace; }
  .field-val.green { color: #16a34a; font-weight: 500; }
  .field-val.muted { color: #94a3b8; }
  .code-block { background: #1e293b; color: #e2e8f0; padding: 14px 16px; border-radius: 6px;
    font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 12px;
    line-height: 1.6; margin: 4px 12px 0; }
  .code-key { color: #93c5fd; }
  .code-str { color: #86efac; }
  .code-num { color: #fde68a; }
  .anon-badge { display: inline-block; background: #fef3c7; color: #92400e;
    border-radius: 3px; padding: 1px 5px; font-size: 11px; font-weight: 600; margin-right: 4px; }
</style>
</head>
<body>
<div class="topbar">
  <div class="logo"><div class="logo-dot"></div> LangSmith <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg></div>
</div>
<div class="breadcrumb">
  <a href="#">Personal</a> / <a href="#">Tracing</a> / <a href="#">medassist</a> / <strong>medassist-scheduling</strong>
</div>
<div class="layout">
  <div class="trace-panel">
    <div class="trace-toolbar">
      <span>🔽</span> Trace &nbsp; <span style="background:#f1f5f9;padding:3px 10px;border-radius:5px;">Waterfall</span>
      <span style="margin-left:auto;">⚙️</span>
    </div>
    <div class="trace-item">
      <div class="trace-item-icon">T</div>
      <div>
        <div class="trace-name">medassist-scheduling</div>
        <div class="trace-time">⏱ 1.67s</div>
      </div>
      <div class="trace-latency">✓ 1.67s</div>
    </div>
  </div>

  <div class="detail-panel">
    <div class="detail-header">
      <div class="detail-title">
        <div class="detail-title-icon">T</div>
        <span class="detail-name">medassist-scheduling</span>
        <span style="font-size:12px;color:#94a3b8;margin-left:6px;">ID 🔗</span>
      </div>
      <div style="display:flex;gap:8px;">
        <button style="border:1px solid #e2e8f0;background:#fff;padding:5px 10px;border-radius:5px;font-size:12px;cursor:pointer;">+ Feedback</button>
        <button style="border:1px solid #e2e8f0;background:#fff;padding:5px 10px;border-radius:5px;font-size:12px;cursor:pointer;">⎘</button>
      </div>
    </div>

    <div class="tabs">
      <div class="tab">Feedback</div>
      <div class="tab active">Input</div>
      <div class="tab">Output</div>
      <div class="tab">Attributes</div>
    </div>

    <div class="section">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
        <div class="section-label" style="margin-bottom:0;">Input</div>
        <span style="font-size:12px;color:#6366f1;cursor:pointer;">Markdown ▾</span>
      </div>

      <div style="background:#f8fafc;border-radius:8px;padding:12px;margin-bottom:4px;">
        <div style="font-size:11px;font-weight:600;color:#64748b;margin-bottom:8px;">{ } Fields</div>
        <div class="field-row">
          <span class="field-toggle">▸</span>
          <span class="field-key">task_type</span>
          <span class="field-val green">scheduling</span>
        </div>
        <div class="field-row" style="flex-direction:column;align-items:flex-start;">
          <div style="display:flex;gap:8px;width:100%;">
            <span class="field-toggle">▸</span>
            <span class="field-key">user_input</span>
            <span class="field-val"><span class="anon-badge">ANONYMISED</span> Suggest 3 appointment time slots for the next 7 days starting [DATE]...</span>
          </div>
        </div>
      </div>
    </div>

    <div class="section" style="border-top:1px solid #f1f5f9;padding-top:14px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
        <div class="section-label" style="margin-bottom:0;">Output</div>
        <span style="font-size:12px;color:#6366f1;cursor:pointer;">Markdown ▾</span>
      </div>

      <div style="background:#f8fafc;border-radius:8px;padding:12px;">
        <div style="font-size:11px;font-weight:600;color:#64748b;margin-bottom:8px;">{ } Fields</div>
        <div class="field-row" style="flex-direction:column;">
          <div style="display:flex;gap:8px;">
            <span class="field-toggle">▾</span>
            <span class="field-key">response</span>
          </div>
          <div class="code-block" style="margin-top:8px;width:100%;">
<span class="code-key">"suggestions"</span>: [<br>
&nbsp;&nbsp;{<br>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="code-key">"slot"</span>: <span class="code-str">"Mon Jun 09 09:00–09:30"</span>,<br>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="code-key">"provider"</span>: <span class="code-str">"Dr. [ANONYMISED]"</span>,<br>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="code-key">"type"</span>: <span class="code-str">"follow-up"</span><br>
&nbsp;&nbsp;},<br>
&nbsp;&nbsp;{ <span class="code-key">"slot"</span>: <span class="code-str">"Tue Jun 10 14:00–14:30"</span> <span class="code-str">...</span> }<br>
]
          </div>
        </div>
      </div>
    </div>

    <div style="padding:12px 20px;border-top:1px solid #f1f5f9;display:flex;gap:24px;font-size:12px;color:#64748b;">
      <span>⏱ Latency: <strong style="color:#22c55e;">1.67s</strong></span>
      <span>📅 Jun 3, 2026 3:10 PM AEST</span>
      <span>🌏 APAC endpoint</span>
      <span>🔒 PHI anonymised before push</span>
    </div>
  </div>
</div>
</body>
</html>`;

async function run() {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox'],
    defaultViewport: { width: 1440, height: 820 },
  });

  const page = await browser.newPage();

  // Screenshot 1: Projects list
  await page.setContent(PROJECTS_HTML, { waitUntil: 'load' });
  await page.screenshot({ path: path.join(OUT, 'langsmith-projects.png') });
  console.log('Saved: langsmith-projects.png');

  // Screenshot 2: Trace detail
  await page.setContent(TRACE_HTML, { waitUntil: 'load' });
  await page.screenshot({ path: path.join(OUT, 'langsmith-trace-detail.png') });
  console.log('Saved: langsmith-trace-detail.png');

  await browser.close();
  console.log('Done.');
}

run().catch(e => { console.error(e); process.exit(1); });
