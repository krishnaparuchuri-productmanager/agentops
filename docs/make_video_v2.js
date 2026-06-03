/**
 * AgentOps demo video v2
 * - No audio
 * - Center watermark (light, hard to crop)
 * - LangSmith observability slides added (slides 8 & 9)
 * - Total: ~80s across 10 slides
 *
 * Run: node make_video_v2.js
 */

const { execSync } = require('child_process');
const fs   = require('fs');
const path = require('path');

const FFMPEG = 'C:/Users/ADMIN/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build/bin/ffmpeg.exe';
const SS_DIR = path.join(__dirname, 'screenshots');
const OUT_DIR = path.join(__dirname, 'video_v2');
const FINAL  = path.join(__dirname, 'agentops-demo.mp4'); // overwrite in-place

fs.mkdirSync(OUT_DIR, { recursive: true });

// ── Watermark: centered, white @ 12% opacity ────────────────────────────────
// Positioned at centre of frame — hard to crop, subtle enough not to distract
const WM = `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='krishnaparuchuri.com':x=(w-tw)/2:y=(h-th)/2:fontsize=36:fontcolor=white@0.12:shadowcolor=black@0.08:shadowx=1:shadowy=1`;

// ── Helper: build annotation drawtext chain ─────────────────────────────────
function annotLines(lines, startY = 80, lineH = 28) {
  return lines.map((line, i) => {
    const safe = (line || ' ')
      .replace(/\\/g, '\\\\')
      .replace(/'/g, '’')   // curly apostrophe avoids ffmpeg quoting issues
      .replace(/:/g, '\\:')
      .replace(/\[/g, '\\[')
      .replace(/\]/g, '\\]');
    const y = startY + i * lineH;
    const size = i === 0 ? 22 : 18;
    const color = i === 0 ? 'white' : 'cccccc';
    return `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='${safe}':x=1450:y=${y}:fontsize=${size}:fontcolor=${color}`;
  }).join(',');
}

// ── Base image filter: scale screenshot → 1920×1080 with right annotation panel
function baseFilter(annotationLines, titleText, slideIdx, total) {
  const dots = Array.from({length: total}, (_, i) => i === slideIdx ? '●' : '○').join(' ');
  return [
    'scale=1440:900:force_original_aspect_ratio=decrease',
    'pad=1440:1080:(ow-iw)/2:(oh-ih)/2:color=1a1a2e',
    'pad=1920:1080:0:0:color=111827',
    'drawbox=x=1440:y=0:w=2:h=1080:color=334155:t=fill',
    `drawtext=fontfile=/Windows/Fonts/arialbd.ttf:text='AgentOps':x=1450:y=30:fontsize=26:fontcolor=818cf8`,
    `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='Agent Governance Platform':x=1450:y=56:fontsize=14:fontcolor=6b7280`,
    annotationLines,
    `drawtext=fontfile=/Windows/Fonts/arialbd.ttf:text='${titleText.replace(/'/g, '’')}':x=40:y=1040:fontsize=24:fontcolor=white`,
    `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='${dots}':x=1450:y=1040:fontsize=20:fontcolor=9999ff`,
    WM,
  ].join(',');
}

// ── LangSmith slide filter: dark bg with rendered text (no image source) ───
function langsmithFilter(lines, titleText, slideIdx, total) {
  const dots = Array.from({length: total}, (_, i) => i === slideIdx ? '●' : '○').join(' ');

  // Build body lines starting at y=120
  const bodyLines = lines.map((line, i) => {
    const safe = (line || ' ')
      .replace(/\\/g, '\\\\')
      .replace(/'/g, '’')
      .replace(/:/g, '\\:')
      .replace(/\[/g, '\\[')
      .replace(/\]/g, '\\]');
    const y = 120 + i * 32;
    const size = i === 0 ? 24 : i === 1 ? 20 : 18;
    let color = 'e2e8f0';
    if (line.startsWith('#')) color = '818cf8';   // heading = purple
    if (line.startsWith('  •')) color = 'a5f3fc'; // bullet = cyan
    if (line.startsWith('  ✓') || line.startsWith('  [OK]')) color = '4ade80'; // green
    if (line.startsWith('  !')) color = 'fbbf24'; // warn = amber
    return `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='${safe}':x=80:y=${y}:fontsize=${size}:fontcolor=${color}`;
  }).join(',');

  return [
    // Solid dark background — no image input needed (we colour the padded canvas)
    'color=color=0f172a:size=1920x1080',
    // LangSmith header bar
    'drawbox=x=0:y=0:w=1920:h=70:color=1e293b:t=fill',
    `drawtext=fontfile=/Windows/Fonts/arialbd.ttf:text='LangSmith APAC':x=40:y=20:fontsize=28:fontcolor=818cf8`,
    `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='apac.smith.langchain.com  —  Live observability for MediAssist + GMP':x=40:y=50:fontsize=16:fontcolor=6b7280`,
    bodyLines,
    `drawtext=fontfile=/Windows/Fonts/arialbd.ttf:text='${titleText.replace(/'/g, '’')}':x=40:y=1040:fontsize=24:fontcolor=white`,
    `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='${dots}':x=1840:y=1040:fontsize=20:fontcolor=9999ff`,
    WM,
  ].join(',');
}

// ── Slide definitions ────────────────────────────────────────────────────────
// type: 'image' uses a screenshot file; type: 'text' renders on dark bg
const SLIDES = [
  {
    type: 'image', img: '01-login.png', dur: 6,
    title: 'Login Screen',
    annotation: [
      'AgentOps — AI Agent',
      'Governance Platform',
      '',
      'Manages AI agents from',
      'registration through',
      'retirement.',
      '',
      'Two production systems',
      'governed:',
      '• GMP Deviation Review',
      '• MediAssist AI',
      '  (Router + 5 agents)',
    ],
  },
  {
    type: 'image', img: '02-registry.png', dur: 8,
    title: 'Agent Registry',
    annotation: [
      'Agent Registry',
      '',
      '7 agents across two',
      'AI systems with stage',
      'badges at a glance.',
      '',
      'Lifecycle stages:',
      '  Proposed',
      '  Under Review',
      '  Approved',
      '  Under Monitoring',
      '  In Production',
      '  Deprecated',
      '  Retired',
    ],
  },
  {
    type: 'image', img: '08-register-agent.png', dur: 7,
    title: 'Register New Agent',
    annotation: [
      'Register New Agent',
      '',
      '3-step form:',
      '  1  Identity',
      '  2  Context &',
      '     Classification',
      '  3  Config',
      '',
      'Set at registration:',
      '• Model selection',
      '• Golden rules',
      '• Guardrails',
      '• Budget limits',
      '• Sub-agents / parent',
    ],
  },
  {
    type: 'image', img: '03-detail-overview.png', dur: 9,
    title: 'Agent Topology',
    annotation: [
      'Topology Card',
      '',
      'MediAssist Router',
      'orchestrates 5 agents.',
      '',
      'Model chosen by task',
      'complexity:',
      '',
      '  Haiku — routing,',
      '  scheduling, orders',
      '',
      '  Sonnet — scribe,',
      '  results, billing',
      '',
      'Chips are clickable.',
    ],
  },
  {
    type: 'image', img: '04-detail-evals.png', dur: 8,
    title: 'Eval-Gated Promotion',
    annotation: [
      'Eval-Gated Promotion',
      '',
      'Cannot submit for',
      'approval until evals',
      'pass.',
      '',
      '6 dimensions 0-10:',
      '• Critical value detect',
      '• Doc completeness',
      '• Billing compliance',
      '• Clinical accuracy',
      '• HIPAA adherence',
      '• Scheduling accuracy',
      '',
      'Red < 6.5  Amber < 8',
    ],
  },
  {
    type: 'image', img: '05-detail-costs.png', dur: 7,
    title: 'Cost & Token Tracking',
    annotation: [
      'Cost Tracking',
      '',
      'Daily USD + tokens',
      'per agent.',
      '',
      'Budget alerts at 80%',
      'of daily cap.',
      '',
      'Model cost delta:',
      '  Haiku  $0.25/M in',
      '  Sonnet $3.00/M in',
      '  (12x on output)',
      '',
      'Cost at agent',
      'granularity.',
    ],
  },
  {
    type: 'image', img: '06-detail-audit.png', dur: 7,
    title: 'Immutable Audit Log',
    annotation: [
      'Immutable Audit Log',
      '',
      'Every event is',
      'append-only.',
      '',
      'No UPDATE or DELETE',
      'endpoint exists.',
      '',
      'Recorded:',
      '• Stage transitions',
      '• Approval decisions',
      '• Eval submissions',
      '• Cost records',
      '',
      'Full traceability for',
      'regulated domains.',
    ],
  },
  {
    // LangSmith slide 1: Projects list
    type: 'text', dur: 9,
    title: 'LangSmith — Live Observability',
    lines: [
      '# Tracing Projects',
      '',
      'Both production systems push traces to',
      'LangSmith APAC after every real AI call.',
      '',
      '  Project              Recent Run    Traces   Error   P50',
      '  ─────────────────────────────────────────────────────────',
      '  [OK] medassist          3 hrs ago      2       0%    2.26s',
      '  [OK] gmp-deviation-review  4 hrs ago   1       0%    0.83s',
      '',
      '  Total tokens (7d)  medassist: 688  gmp: 1,993',
      '',
      '  PHI anonymisation runs before every trace push.',
      '  No raw patient data ever reaches LangSmith.',
    ],
  },
  {
    // LangSmith slide 2: Trace detail
    type: 'text', dur: 10,
    title: 'LangSmith — Trace Detail',
    lines: [
      '# Trace: medassist-scheduling',
      '',
      '  Run name     medassist-scheduling',
      '  Start time   Jun 3 2026, 3:10 PM AEST',
      '  Latency      1.67s',
      '  Status       [OK] Success',
      '',
      '  INPUT',
      '  ! task_type    scheduling',
      '  • user_input   [ANONYMISED] Suggest 3 appointment',
      '                 time slots for the next 7 days...',
      '',
      '  OUTPUT',
      '  • response   json { "suggestions": [ ... ] }',
      '',
      '  The Cloudflare Worker strips PHI, routes by',
      '  task_type, then fires trace push via ctx.waitUntil()',
    ],
  },
  {
    type: 'image', img: '07-governance-queue.png', dur: 10,
    title: 'Governance Queue',
    annotation: [
      'Governance Queue',
      '',
      'Pending approvals +',
      'active alerts.',
      '',
      'Maker-checker:',
      'Proposer != Reviewer',
      '',
      'Active alerts:',
      '• billing compliance',
      '  5.9 / 10',
      '• SOAP notes missing',
      '  HPI field',
      '• Cost threshold 93%',
      '',
      'LangSmith APAC traces',
      'linked per run.',
    ],
  },
];

const TOTAL = SLIDES.length;

// ── Build clips ──────────────────────────────────────────────────────────────
const clipPaths = [];

for (let i = 0; i < SLIDES.length; i++) {
  const slide = SLIDES[i];
  const clipPath = path.join(OUT_DIR, `clip_${i}.mp4`).replace(/\\/g, '/');
  console.log(`\n[${i+1}/${TOTAL}] ${slide.title}`);

  let cmd;

  if (slide.type === 'image') {
    const imgPath = path.join(SS_DIR, slide.img).replace(/\\/g, '/');
    const vf = baseFilter(
      annotLines(slide.annotation),
      slide.title,
      i, TOTAL
    );
    cmd = [
      `"${FFMPEG}"`, `-y`,
      `-loop 1 -i "${imgPath}"`,
      `-vf "${vf}"`,
      `-c:v libx264 -preset fast -crf 22 -pix_fmt yuv420p`,
      `-t ${slide.dur} -r 25 -an`,
      `"${clipPath}"`,
    ].join(' ');

  } else {
    // Text-only slide: use lavfi color source
    const dots = Array.from({length: TOTAL}, (_, di) => di === i ? '●' : '○').join(' ');

    const bodyFilters = slide.lines.map((line, li) => {
      const safe = (line || ' ')
        .replace(/\\/g, '\\\\')
        .replace(/'/g, '’')
        .replace(/:/g, '\\:')
        .replace(/\[/g, '\\[')
        .replace(/\]/g, '\\]');
      const y = 100 + li * 34;
      let color = 'e2e8f0'; size = 20;
      if (line.startsWith('#'))   { color = '818cf8'; size = 26; }
      if (line.startsWith('  [OK]') || line.startsWith('  ✓')) color = '4ade80';
      if (line.startsWith('  !')) color = 'fbbf24';
      if (line.startsWith('  •')) color = 'a5f3fc';
      if (line.startsWith('  ─') || line.startsWith('  Project')) { color = '4b5563'; size = 17; }
      return `drawtext=fontfile=/Windows/Fonts/consola.ttf:text='${safe}':x=60:y=${y}:fontsize=${size}:fontcolor=${color}`;
    }).join(',');

    const fullFilter = [
      `color=color=0f172a:size=1920x1080`,
      `drawbox=x=0:y=0:w=1920:h=70:color=1e293b:t=fill`,
      `drawtext=fontfile=/Windows/Fonts/arialbd.ttf:text='LangSmith APAC — Live Observability':x=40:y=20:fontsize=26:fontcolor=818cf8`,
      `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='apac.smith.langchain.com — traces from MediAssist + GMP via Cloudflare Worker ctx.waitUntil()':x=40:y=52:fontsize=15:fontcolor=6b7280`,
      bodyFilters,
      `drawtext=fontfile=/Windows/Fonts/arialbd.ttf:text='${slide.title.replace(/'/g, '’')}':x=40:y=1042:fontsize=22:fontcolor=white`,
      `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='${dots}':x=1840:y=1042:fontsize=18:fontcolor=9999ff`,
      WM,
    ].join(',');

    cmd = [
      `"${FFMPEG}"`, `-y`,
      `-f lavfi -i "${fullFilter}"`,
      `-c:v libx264 -preset fast -crf 22 -pix_fmt yuv420p`,
      `-t ${slide.dur} -r 25 -an`,
      `"${clipPath}"`,
    ].join(' ');
  }

  try {
    execSync(cmd, { stdio: 'pipe' });
    console.log(`  OK → clip_${i}.mp4`);
    clipPaths.push(clipPath);
  } catch (err) {
    console.error('  Error:', err.stderr?.toString().slice(-600));
    process.exit(1);
  }
}

// ── Concat ───────────────────────────────────────────────────────────────────
console.log('\nConcatenating...');
const listFile = path.join(OUT_DIR, 'concat.txt');
fs.writeFileSync(listFile, clipPaths.map(p => `file '${p}'`).join('\n'));

execSync([
  `"${FFMPEG}"`, `-y`,
  `-f concat -safe 0 -i "${listFile.replace(/\\/g, '/')}"`,
  `-c copy`,
  `"${FINAL.replace(/\\/g, '/')}"`,
].join(' '), { stdio: 'inherit' });

console.log(`\nDone → ${FINAL}`);
