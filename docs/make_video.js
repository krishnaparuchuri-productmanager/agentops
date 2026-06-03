/**
 * AgentOps demo video generator
 * Creates a 70s annotated MP4 from the 8 dashboard screenshots.
 *
 * Layout: 1920 × 1080
 *   Left  1440px — screenshot (scaled/padded to fit 1440×900 then centred)
 *   Right  480px — annotation panel (dark bg, white text)
 *   Bottom 180px (shared) — caption bar + progress dots
 *
 * Run: node make_video.js
 * Requires: ffmpeg in PATH (or set FFMPEG env var), screenshots/ folder
 */

const { execSync, spawnSync } = require('child_process');
const fs   = require('fs');
const path = require('path');

// ─── Config ────────────────────────────────────────────────────────────────
const FFMPEG   = process.env.FFMPEG ||
  'C:/Users/ADMIN/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build/bin/ffmpeg.exe';
const SS_DIR   = path.join(__dirname, 'screenshots');
const OUT_DIR  = path.join(__dirname, 'video');
const FINAL    = path.join(__dirname, 'agentops-demo.mp4');

fs.mkdirSync(OUT_DIR, { recursive: true });

// ─── Slides ─────────────────────────────────────────────────────────────────
// duration in seconds
const SLIDES = [
  {
    img: '01-login.png',
    dur: 7,
    title: 'Login Screen',
    annotation: [
      'AgentOps: AI Agent',
      'Governance Platform',
      '',
      'Every AI agent needs',
      'a governance layer —',
      'from creation through',
      'retirement.',
      '',
      'Demo auth: any',
      'username/password',
      '(4+ characters).',
    ],
    narration: 'Welcome to AgentOps — a multi-agent governance platform that manages AI agents across their full lifecycle. From the moment an agent is proposed, every decision is tracked, approved, and audited.',
  },
  {
    img: '02-registry.png',
    dur: 9,
    title: 'Agent Registry',
    annotation: [
      'Agent Registry',
      '',
      '7 managed agents',
      'across two production',
      'AI systems:',
      '',
      '• GMP Deviation',
      '  Review — single agent',
      '',
      '• MediAssist AI —',
      '  Router + 5 specialists',
      '',
      'Stage badges show',
      'lifecycle position at',
      'a glance.',
    ],
    narration: 'The Agent Registry shows every managed agent with its current lifecycle stage. Two production systems are governed here: the GMP Deviation Review single agent, and the MediAssist multi-agent system with a router and five clinical specialists.',
  },
  {
    img: '08-register-agent.png',
    dur: 8,
    title: 'Register New Agent',
    annotation: [
      'Register New Agent',
      '',
      '3-step form:',
      '  1. Identity',
      '  2. Context &',
      '     Classification',
      '  3. Config',
      '',
      'Define at registration:',
      '• Model selection',
      '• Golden rules',
      '• Guardrails',
      '• Budget limits',
      '• Sub-agents / parent',
    ],
    narration: 'Registering an agent is a deliberate act. A three-step form captures identity, classification, and configuration — including model selection, golden rules, clinical guardrails, and daily budget caps — before the agent ever runs.',
  },
  {
    img: '03-detail-overview.png',
    dur: 10,
    title: 'Agent Topology',
    annotation: [
      'Agent Detail —',
      'Topology Card',
      '',
      'MediAssist Router',
      'orchestrates 5 agents:',
      '• Scheduler (Haiku)',
      '• Scribe (Sonnet)',
      '• Orders (Haiku)',
      '• Results (Sonnet)',
      '• Billing (Sonnet)',
      '',
      'Model chosen by task',
      'complexity — fast/cheap',
      'for routing, powerful',
      'for clinical reasoning.',
      '',
      'Chips are clickable →',
      'navigate to any agent.',
    ],
    narration: 'The Agent Topology Card visualises the full orchestration tree. The MediAssist router delegates to five specialists — Haiku for scheduling and order mapping, Sonnet for clinical reasoning tasks like scribe notes, lab results, and billing. Each chip is clickable for instant navigation.',
  },
  {
    img: '04-detail-evals.png',
    dur: 9,
    title: 'Eval-Gated Promotion',
    annotation: [
      'Eval-Gated Promotion',
      '',
      'An agent cannot be',
      'submitted for approval',
      'until it passes evals.',
      '',
      'Six dimensions scored',
      '0 – 10:',
      '• Critical value detection',
      '• Documentation completeness',
      '• Billing compliance',
      '• Clinical accuracy',
      '• HIPAA adherence',
      '• Scheduling accuracy',
      '',
      'Red < 6.5 · Amber < 8',
      'Green >= 8',
    ],
    narration: 'Promotion through the lifecycle is eval-gated. An agent must achieve a passing score before an approval request can even be submitted. Six evaluation dimensions surface weak spots — billing compliance in red is what keeps MediAssist Billing in Under Review stage.',
  },
  {
    img: '05-detail-costs.png',
    dur: 8,
    title: 'Cost & Token Tracking',
    annotation: [
      'Cost & Token Tracking',
      '',
      'Daily USD spend and',
      'token usage per agent.',
      '',
      'Budget alerts fire at',
      '80% of daily cap.',
      '',
      'Model cost difference:',
      '• Haiku  $0.25/M in',
      '          $1.25/M out',
      '• Sonnet $3.00/M in',
      '          $15.00/M out',
      '',
      'Know your AI costs at',
      'agent granularity.',
    ],
    narration: 'Cost tracking is per-agent and per-day. Budget alerts fire at 80 percent of the daily cap. The cost difference between Haiku and Sonnet is significant — Sonnet is 12 times more expensive on output tokens — which is why model selection by task complexity matters.',
  },
  {
    img: '06-detail-audit.png',
    dur: 8,
    title: 'Immutable Audit Log',
    annotation: [
      'Immutable Audit Log',
      '',
      'Every event is',
      'append-only.',
      '',
      'Recorded events:',
      '• Stage transitions',
      '• Approval requests',
      '• Approval decisions',
      '• Eval submissions',
      '• Cost records',
      '',
      'No UPDATE or DELETE',
      'endpoint exists in',
      'the codebase.',
      '',
      'Full traceability for',
      'regulated domains.',
    ],
    narration: 'The audit log is immutable by design. Every lifecycle transition, approval, and eval submission writes an append-only row. There is no update or delete endpoint anywhere in the codebase — a deliberate choice for regulated-domain AI governance.',
  },
  {
    img: '07-governance-queue.png',
    dur: 11,
    title: 'Governance Queue',
    annotation: [
      'Governance Queue',
      '',
      'Pending approvals +',
      'active alerts in one',
      'view.',
      '',
      'Maker-checker design:',
      'Proposer != Reviewer.',
      '',
      'Active alerts shown:',
      '• billing_compliance 5.9',
      '• SOAP notes missing HPI',
      '• Critical value spike',
      '• Cost threshold 93.5%',
      '',
      'LangSmith traces pushed',
      'from every live call —',
      'via APAC endpoint for',
      'data residency.',
    ],
    narration: 'The Governance Queue is where oversight happens. Pending approvals require a different person to review than the proposer — maker-checker from financial transaction safety applied to AI governance. Active alerts surface eval degradation, golden rule violations, and cost warnings. Every live MediAssist call pushes a trace to LangSmith APAC for full observability.',
  },
];

// ─── TTS via PowerShell ──────────────────────────────────────────────────────
function generateAudio(text, outWav) {
  if (fs.existsSync(outWav)) return; // skip if already generated
  const escaped = text.replace(/'/g, "''");
  const ps = `
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = -1
$synth.Volume = 100
$synth.SelectVoiceByHints('Female')
$synth.SetOutputToWaveFile('${outWav.replace(/\\/g, '\\\\')}')
$synth.Speak('${escaped}')
$synth.Dispose()
`.trim();
  spawnSync('powershell', ['-Command', ps], { stdio: 'inherit' });
}

// ─── Build per-slide clips ───────────────────────────────────────────────────
const clipPaths = [];

for (let i = 0; i < SLIDES.length; i++) {
  const slide = SLIDES[i];
  const imgPath = path.join(SS_DIR, slide.img).replace(/\\/g, '/');
  const wavPath = path.join(OUT_DIR, `audio_${i}.wav`).replace(/\\/g, '/');
  const clipPath = path.join(OUT_DIR, `clip_${i}.mp4`).replace(/\\/g, '/');

  console.log(`\n[${i+1}/${SLIDES.length}] ${slide.title}`);

  // 1. Generate narration audio
  console.log('  Generating audio...');
  generateAudio(slide.narration, wavPath);

  // 2. Prep annotation lines for drawtext
  // We add a right panel: pad the image from 1440→1920, then write text
  const panelX = 1450; // start of text in right panel
  const lineH   = 28;  // px per annotation line
  const startY  = 80;  // first line Y

  // Build drawtext filter chain for annotation lines
  const annotLines = slide.annotation;
  const drawtextFilters = annotLines.map((line, li) => {
    const safeText = line
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "’")   // curly apostrophe avoids ffmpeg quoting issues
      .replace(/:/g, '\\:')
      .replace(/\[/g, '\\[')
      .replace(/\]/g, '\\]')
      || ' ';
    const y = startY + li * lineH;
    const fontSize = li === 0 ? 22 : 18;
    const color = li === 0 ? 'white' : 'cccccc';
    return `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='${safeText}':x=${panelX}:y=${y}:fontsize=${fontSize}:fontcolor=${color}:line_spacing=4`;
  }).join(',');

  // Title bar at bottom
  const titleFilter = `drawtext=fontfile=/Windows/Fonts/arialbd.ttf:text='${slide.title.replace(/'/g, "’")}':x=40:y=1040:fontsize=24:fontcolor=white`;

  // Step indicator dots  e.g. "● ○ ○ ○"
  const dotsText = SLIDES.map((_, di) => di === i ? '●' : '○').join(' ');
  const dotsFilter = `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='${dotsText}':x=1450:y=1040:fontsize=20:fontcolor=9999ff`;

  const fullFilter = [
    // Scale screenshot to fit 1440×900, pad to 1440×1080 (centre vertically)
    `scale=1440:900:force_original_aspect_ratio=decrease`,
    `pad=1440:1080:(ow-iw)/2:(oh-ih)/2:color=1a1a2e`,
    // Extend canvas rightward to 1920 with dark panel
    `pad=1920:1080:0:0:color=111827`,
    // Panel separator line
    `drawbox=x=1440:y=0:w=2:h=1080:color=334155:t=fill`,
    // "AgentOps" label in panel header
    `drawtext=fontfile=/Windows/Fonts/arialbd.ttf:text='AgentOps':x=1450:y=30:fontsize=26:fontcolor=818cf8`,
    `drawtext=fontfile=/Windows/Fonts/arial.ttf:text='Agent Governance Platform':x=1450:y=56:fontsize=14:fontcolor=6b7280`,
    drawtextFilters,
    titleFilter,
    dotsFilter,
  ].join(',');

  // 3. Build clip with ffmpeg
  // Use image as still frame for slide.dur seconds, combine with audio (pad audio if shorter)
  const audioDur = slide.dur + 0.5; // slight tail
  const cmd = [
    `"${FFMPEG}"`,
    `-y`,
    `-loop 1 -i "${imgPath}"`,
    `-i "${wavPath}"`,
    `-vf "${fullFilter}"`,
    `-c:v libx264 -preset fast -crf 22`,
    `-c:a aac -b:a 128k`,
    `-t ${slide.dur}`,
    `-shortest`,
    `-pix_fmt yuv420p`,
    `-r 25`,
    `"${clipPath}"`,
  ].join(' ');

  console.log('  Encoding clip...');
  try {
    execSync(cmd, { stdio: 'pipe' });
    console.log(`  Done -> clip_${i}.mp4`);
    clipPaths.push(clipPath);
  } catch (err) {
    console.error('  FFmpeg error:', err.stderr?.toString().slice(-500));
    process.exit(1);
  }
}

// ─── Concat all clips ────────────────────────────────────────────────────────
console.log('\nConcatenating clips...');
const listFile = path.join(OUT_DIR, 'concat.txt');
fs.writeFileSync(listFile, clipPaths.map(p => `file '${p}'`).join('\n'));

const concatCmd = [
  `"${FFMPEG}"`,
  `-y`,
  `-f concat -safe 0 -i "${listFile.replace(/\\/g, '/')}"`,
  `-c copy`,
  `"${FINAL.replace(/\\/g, '/')}"`,
].join(' ');

execSync(concatCmd, { stdio: 'inherit' });
console.log(`\nDone! -> ${FINAL}`);
