// vid-scenes 前端：原生 JS，无构建步骤。

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = (s) => {
  if (s == null) return "-";
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
};
const STATUS = { pending: "排队中", queued: "排队中", processing: "处理中", running: "处理中", rendering: "渲染中", ready: "就绪", done: "完成", composed: "未渲染", error: "失败" };
const LEVEL = { low: "低", mid: "中", high: "高" };

const state = { view: "library", videoId: null, musicId: null, compId: null, defaults: null };

// ---------- 通用 ----------

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* 非 JSON */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

let toastTimer;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " error" : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), isError ? 6000 : 2500);
}
const guard = (fn) => async (...args) => {
  try { await fn(...args); } catch (e) { toast(e.message, true); }
};

function progressHTML(job) {
  if (!job || !["queued", "running"].includes(job.status)) return "";
  return `<div class="progress"><div style="width:${Math.round(job.progress * 100)}%"></div></div>
          <div class="meta">${esc(job.message || STATUS[job.status])}</div>`;
}

function uploadFiles(url, files, field) {
  const fd = new FormData();
  for (const f of files) fd.append(field, f);
  return api(url, { method: "POST", body: fd });
}

// ---------- 导航 ----------

function showView(view) {
  state.view = view;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  refresh();
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

// ---------- 素材库 ----------

let gridSig = "";
async function loadLibrary() {
  const [videos, stats] = await Promise.all([api("/api/videos"), api("/api/library/stats")]);
  $("#lib-stats").innerHTML = `<b>${stats.videos}</b> 个素材 · <b>${stats.clips}</b> 个可用片段 · 共 <b>${fmtTime(stats.clip_seconds)}</b>`;
  const grid = $("#video-grid");
  const sig = JSON.stringify([videos, state.videoId]);
  if (sig === gridSig) {
    if (state.videoId) loadVideoDetail(false);
    return;
  }
  gridSig = sig;
  if (!videos.length) {
    grid.innerHTML = `<p class="empty" style="grid-column:1/-1">拖拽视频到页面，或点击右上角上传</p>`;
  } else {
    grid.innerHTML = videos.map((v) => `
      <div class="card ${v.id === state.videoId ? "selected" : ""}" data-id="${v.id}">
        <div class="thumb" style="${v.thumb_url ? `background-image:url('${v.thumb_url}')` : ""}">
          <span class="badge ${v.status}">${STATUS[v.status] || v.status}</span>
        </div>
        <div class="body">
          <div class="title" title="${esc(v.filename)}">${esc(v.filename)}</div>
          <div class="meta">${fmtTime(v.duration)} · ${v.width ? `${v.width}×${v.height}` : "-"} · ${v.clip_count} 片段</div>
          ${progressHTML(v.job, v.status)}
          ${v.status === "error" ? `<div class="err-text">${esc(v.error)}</div>` : ""}
        </div>
      </div>`).join("");
    grid.querySelectorAll(".card").forEach((c) => c.addEventListener("click", () => {
      state.videoId = Number(c.dataset.id);
      gridSig = "";
      grid.querySelectorAll(".card").forEach((x) => x.classList.toggle("selected", x === c));
      loadVideoDetail(true);
    }));
  }
  if (state.videoId && !videos.some((v) => v.id === state.videoId)) state.videoId = null;
  if (state.videoId) loadVideoDetail(false);
  else $("#video-detail").hidden = true;
}

let detailSig = "";
async function loadVideoDetail(force) {
  const v = await api(`/api/videos/${state.videoId}`);
  const sig = `${v.id}:${v.status}:${v.clips.length}:${v.clips.filter((c) => c.enabled).length}`;
  const el = $("#video-detail");
  if (!force && sig === detailSig) return;
  detailSig = sig;
  el.hidden = false;
  const maxMotion = Math.max(0.0001, ...v.clips.map((c) => c.motion || 0));
  el.innerHTML = `
    <div class="detail-head">
      ${v.proxy_url ? `<video id="vd-player" src="${v.proxy_url}" controls muted preload="metadata"></video>` : ""}
      <div class="detail-info">
        <h2>${esc(v.filename)}</h2>
        <div class="kv">
          <span>状态</span><b>${STATUS[v.status] || v.status}</b>
          <span>时长</span><b>${fmtTime(v.duration)}</b>
          <span>分辨率</span><b>${v.width ? `${v.width}×${v.height}` : "-"}</b>
          <span>帧率</span><b>${v.fps ? v.fps.toFixed(2) : "-"}</b>
          <span>编码</span><b>${esc(v.codec || "-")}</b>
          <span>片段</span><b>${v.clips.length}（启用 ${v.clips.filter((c) => c.enabled).length}）</b>
        </div>
        <div class="actions">
          <button class="btn" id="vd-reprocess">重新处理</button>
          <button class="btn danger" id="vd-delete">删除素材</button>
        </div>
      </div>
    </div>
    <div class="clip-grid">
      ${v.clips.map((c) => `
        <div class="clip ${c.enabled ? "" : "disabled"}" data-id="${c.id}" data-start="${c.start}" data-end="${c.end}">
          <div class="thumb" style="${c.thumb_url ? `background-image:url('${c.thumb_url}')` : ""}" title="点击在上方播放"></div>
          <input class="toggle" type="checkbox" ${c.enabled ? "checked" : ""} title="参与编排">
          <div class="info">
            <span class="swatch" style="background:${c.color_hex || "#000"}"></span>
            <span>${c.duration.toFixed(1)}s</span>
            <span class="motion" title="运动强度"><div style="width:${Math.round(100 * (c.motion || 0) / maxMotion)}%"></div></span>
          </div>
        </div>`).join("")}
    </div>`;

  const player = $("#vd-player", el);
  let loopEnd = null, loopStart = 0;
  if (player) {
    player.addEventListener("timeupdate", () => {
      if (loopEnd != null && player.currentTime >= loopEnd) player.currentTime = loopStart;
    });
  }
  el.querySelectorAll(".clip").forEach((clipEl) => {
    $(".thumb", clipEl).addEventListener("click", () => {
      if (!player) return;
      loopStart = Number(clipEl.dataset.start);
      loopEnd = Number(clipEl.dataset.end);
      player.currentTime = loopStart;
      player.play();
    });
    $(".toggle", clipEl).addEventListener("change", guard(async (e) => {
      await api(`/api/clips/${clipEl.dataset.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: e.target.checked }),
      });
      clipEl.classList.toggle("disabled", !e.target.checked);
      detailSig = "";
    }));
  });
  $("#vd-reprocess", el).addEventListener("click", guard(async () => {
    await api(`/api/videos/${v.id}/reprocess`, { method: "POST" });
    toast("已重新加入处理队列");
    refresh();
  }));
  $("#vd-delete", el).addEventListener("click", guard(async () => {
    if (!confirm(`删除素材“${v.filename}”及其所有片段？`)) return;
    await api(`/api/videos/${v.id}`, { method: "DELETE" });
    state.videoId = null;
    el.hidden = true;
    refresh();
  }));
}

$("#video-input").addEventListener("change", guard(async (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  if (!files.length) return;
  toast(`正在上传 ${files.length} 个视频…`);
  await uploadFiles("/api/videos", files, "files");
  toast("上传完成，开始后台处理");
  refresh();
}));

// ---------- 音乐 ----------

let musicListSig = "";
async function loadMusicList() {
  const list = await api("/api/music");
  const ul = $("#music-list");
  const sig = JSON.stringify([list, state.musicId]);
  if (sig !== musicListSig) {
    musicListSig = sig;
    ul.innerHTML = list.map((m) => `
      <li data-id="${m.id}" class="${m.id === state.musicId ? "selected" : ""}">
        <div class="title" title="${esc(m.filename)}">${esc(m.filename)}</div>
        <div class="meta"><span>${STATUS[m.status] || m.status}</span>
          ${m.bpm ? `<span>${m.bpm.toFixed(1)} BPM</span>` : ""}<span>${fmtTime(m.duration)}</span></div>
        ${progressHTML(m.job, m.status)}
      </li>`).join("") || `<li class="meta">还没有音乐</li>`;
    ul.querySelectorAll("li[data-id]").forEach((li) => li.addEventListener("click", () => {
      state.musicId = Number(li.dataset.id);
      musicSig = "";
      loadMusicList();
    }));
  }
  if (state.musicId && !list.some((m) => m.id === state.musicId)) state.musicId = null;
  if (state.musicId) await loadMusicDetail();
}

let musicSig = "";
async function loadMusicDetail() {
  const m = await api(`/api/music/${state.musicId}`);
  const sig = `${m.id}:${m.status}`;
  if (sig === musicSig) return;
  musicSig = sig;
  const el = $("#music-detail");
  if (m.status !== "ready") {
    el.innerHTML = `<h2>${esc(m.filename)}</h2><p class="meta">${STATUS[m.status] || m.status}</p>
      ${m.status === "error" ? `<div class="err-text">${esc(m.error)}</div>` : progressHTML(m.job, m.status)}`;
    return;
  }
  const a = m.analysis;
  const levels = a.bars.reduce((acc, b) => ((acc[b.level] = (acc[b.level] || 0) + 1), acc), {});
  state.defaults ??= await api("/api/compose/defaults");
  const d = state.defaults;
  const beatOpts = (sel) => [1, 2, 4, 8, 16].map((n) => `<option value="${n}" ${n === sel ? "selected" : ""}>${n} 拍</option>`).join("");
  el.innerHTML = `
    <h2>${esc(m.filename)}</h2>
    <div class="kv">
      <span>BPM</span><b>${a.bpm.toFixed(1)}</b>
      <span>时长</span><b>${fmtTime(a.duration)}</b>
      <span>节拍 / 小节</span><b>${a.beats.length} 拍 · ${a.downbeats.length} 小节</b>
      <span>能量分布</span><b>低 ${levels.low || 0} · 中 ${levels.mid || 0} · 高 ${levels.high || 0} 小节</b>
      <span>分析引擎</span><b>${esc(a.engine)}</b>
    </div>
    <div class="wave-wrap"><canvas id="wave"></canvas></div>
    <div class="legend">
      <span><i style="background:var(--low)"></i>低能量</span>
      <span><i style="background:var(--mid)"></i>中能量</span>
      <span><i style="background:var(--high)"></i>高能量</span>
      <span>细线 = 拍 · 粗线 = 小节第一拍</span>
    </div>
    <audio id="music-audio" src="${m.audio_url}" controls preload="metadata"></audio>
    <div class="compose-box">
      <h3>生成卡点视频</h3>
      <div class="form-row">
        <label class="field">分辨率
          <select id="cf-res">
            <option value="1920x1080">1920×1080</option>
            <option value="1280x720">1280×720</option>
            <option value="1080x1920">1080×1920（竖版）</option>
          </select></label>
        <label class="field">帧率
          <select id="cf-fps"><option>30</option><option>60</option><option>25</option><option>24</option></select></label>
        <label class="field">低能量切点间隔<select id="cf-low">${beatOpts(d.cut_beats.low)}</select></label>
        <label class="field">中能量切点间隔<select id="cf-mid">${beatOpts(d.cut_beats.mid)}</select></label>
        <label class="field">高能量切点间隔<select id="cf-high">${beatOpts(d.cut_beats.high)}</select></label>
        <label class="field">随机种子<input id="cf-seed" type="number" value="${Math.floor(Math.random() * 10000)}"></label>
        <button class="btn primary" id="cf-go">生成并渲染</button>
      </div>
    </div>`;
  const audio = $("#music-audio", el);
  drawWave($("#wave", el), a, audio);
  $("#cf-go", el).addEventListener("click", guard(async (e) => {
    e.target.disabled = true;
    try {
      const [width, height] = $("#cf-res").value.split("x").map(Number);
      const comp = await postJSON("/api/compositions", {
        music_id: m.id,
        settings: {
          width, height, fps: Number($("#cf-fps").value), seed: Number($("#cf-seed").value),
          cut_beats: { low: Number($("#cf-low").value), mid: Number($("#cf-mid").value), high: Number($("#cf-high").value) },
        },
      });
      toast(`已编排 ${comp.segment_count} 个镜头，开始渲染`);
      state.compId = comp.id;
      showView("renders");
    } finally {
      e.target.disabled = false;
    }
  }));
}

function drawWave(canvas, a, audio) {
  const css = getComputedStyle(document.documentElement);
  const color = (n) => css.getPropertyValue(n).trim();
  const dpr = window.devicePixelRatio || 1;
  const render = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const x = (t) => (t / a.duration) * w;
    const lv = { low: color("--low"), mid: color("--mid"), high: color("--high") };
    for (const b of a.bars) {
      ctx.globalAlpha = 0.18;
      ctx.fillStyle = lv[b.level];
      ctx.fillRect(x(b.start), 0, x(b.end) - x(b.start), h);
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = color("--muted");
    const n = a.waveform.length, bw = w / n;
    a.waveform.forEach((p, i) => {
      const ph = p * (h - 10);
      ctx.fillRect(i * bw, (h - ph) / 2, Math.max(1, bw - 0.3), ph);
    });
    ctx.strokeStyle = "rgba(255,255,255,0.18)";
    ctx.lineWidth = 1;
    const down = new Set(a.downbeats);
    for (const t of a.beats) {
      if (down.has(t)) continue;
      ctx.beginPath(); ctx.moveTo(x(t) + 0.5, h - 10); ctx.lineTo(x(t) + 0.5, h); ctx.stroke();
    }
    ctx.strokeStyle = "rgba(255,255,255,0.55)";
    for (const t of a.downbeats) {
      ctx.beginPath(); ctx.moveTo(x(t) + 0.5, h - 22); ctx.lineTo(x(t) + 0.5, h); ctx.stroke();
    }
    if (!audio.paused || audio.currentTime > 0) {
      ctx.fillStyle = "#fff";
      ctx.fillRect(x(audio.currentTime), 0, 2, h);
    }
  };
  render();
  let raf;
  const loop = () => { render(); if (!audio.paused) raf = requestAnimationFrame(loop); };
  audio.addEventListener("play", () => { cancelAnimationFrame(raf); loop(); });
  audio.addEventListener("seeked", render);
  canvas.addEventListener("click", (e) => {
    const r = canvas.getBoundingClientRect();
    audio.currentTime = ((e.clientX - r.left) / r.width) * a.duration;
    render();
  });
  new ResizeObserver(render).observe(canvas);
}

$("#music-input").addEventListener("change", guard(async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  toast("正在上传音乐…");
  const r = await uploadFiles("/api/music", [file], "file");
  state.musicId = r.id;
  musicSig = "";
  toast("上传完成，开始分析");
  refresh();
}));

// ---------- 成片 ----------

let compListSig = "";
async function loadComps() {
  const list = await api("/api/compositions");
  const ul = $("#comp-list");
  const sig = JSON.stringify([list, state.compId]);
  if (sig !== compListSig) {
    compListSig = sig;
    ul.innerHTML = list.map((c) => `
      <li data-id="${c.id}" class="${c.id === state.compId ? "selected" : ""}">
        <div class="title">#${c.id} · ${esc(c.music_filename)}</div>
        <div class="meta"><span>${STATUS[c.status] || c.status}</span><span>${c.segment_count} 镜头</span><span>${fmtTime(c.duration)}</span></div>
        ${progressHTML(c.job, c.status)}
      </li>`).join("") || `<li class="meta">还没有成片</li>`;
    ul.querySelectorAll("li[data-id]").forEach((li) => li.addEventListener("click", () => {
      state.compId = Number(li.dataset.id);
      compSig = "";
      loadComps();
    }));
  }
  if (state.compId && !list.some((c) => c.id === state.compId)) state.compId = null;
  if (state.compId) await loadCompDetail();
}

let compSig = "";
async function loadCompDetail() {
  const c = await api(`/api/compositions/${state.compId}`);
  const el = $("#comp-detail");
  const sig = `${c.id}:${c.status}:${c.output_url}`;
  if (sig === compSig) {
    const p = $("#comp-progress", el);
    if (p) p.innerHTML = progressHTML(c.job, c.status);
    return;
  }
  compSig = sig;
  const tl = c.timeline;
  const s = c.settings || {};
  el.innerHTML = `
    <h2>#${c.id} · ${esc(c.music_filename)}</h2>
    <div class="kv">
      <span>状态</span><b>${STATUS[c.status] || c.status}</b>
      <span>规格</span><b>${s.width}×${s.height} @ ${s.fps}fps</b>
      <span>镜头数</span><b>${tl.segments.length}</b>
      <span>切点间隔</span><b>低 ${s.cut_beats?.low} / 中 ${s.cut_beats?.mid} / 高 ${s.cut_beats?.high} 拍</b>
      <span>随机种子</span><b>${s.seed}</b>
    </div>
    <div id="comp-progress">${progressHTML(c.job, c.status)}</div>
    ${c.status === "error" ? `<div class="err-text">${esc(c.error)}</div>` : ""}
    ${c.output_url ? `<video class="out-video" id="out-video" src="${c.output_url}?v=${Date.now()}" controls style="margin-top:14px"></video>` : ""}
    <div class="timeline" id="tl">
      ${tl.segments.map((g) => `<div class="seg ${g.level}" data-start="${g.start}" style="flex:${g.frames};${c.clip_thumbs[g.clip_id] ? `background-image:url('${c.clip_thumbs[g.clip_id]}')` : ""}" title="#${g.index + 1} ${fmtTime(g.start)} · ${g.duration.toFixed(2)}s · ${LEVEL[g.level]}能量 · 片段 ${g.clip_id}${g.hold ? " · 定帧补齐" : ""}"></div>`).join("")}
    </div>
    <div class="actions">
      ${c.output_url ? `<a class="btn primary" href="${c.output_url}" download="vid-scenes-${c.id}.mp4">下载</a>` : ""}
      <button class="btn" id="cd-regen">换一组素材重新生成</button>
      <button class="btn" id="cd-rerender">重新渲染</button>
      <button class="btn danger" id="cd-delete">删除</button>
    </div>`;
  const video = $("#out-video", el);
  const segs = [...el.querySelectorAll(".seg")];
  segs.forEach((sg) => sg.addEventListener("click", () => {
    if (video) { video.currentTime = Number(sg.dataset.start) + 0.001; video.play(); }
  }));
  if (video) {
    video.addEventListener("timeupdate", () => {
      const t = video.currentTime;
      let cur = 0;
      for (let i = 0; i < segs.length; i++) if (Number(segs[i].dataset.start) <= t) cur = i;
      segs.forEach((sg, i) => sg.classList.toggle("active", i === cur));
    });
  }
  $("#cd-regen", el).addEventListener("click", guard(async () => {
    const comp = await postJSON("/api/compositions", { music_id: c.music_id, settings: { ...s, seed: (s.seed || 0) + 1 } });
    state.compId = comp.id;
    compSig = "";
    toast("已用新的随机种子重新编排");
    refresh();
  }));
  $("#cd-rerender", el).addEventListener("click", guard(async () => {
    await api(`/api/compositions/${c.id}/render`, { method: "POST" });
    compSig = "";
    refresh();
  }));
  $("#cd-delete", el).addEventListener("click", guard(async () => {
    if (!confirm(`删除成片 #${c.id}？`)) return;
    await api(`/api/compositions/${c.id}`, { method: "DELETE" });
    state.compId = null;
    el.innerHTML = `<p class="empty">在“音乐”页生成卡点视频</p>`;
    refresh();
  }));
}

// ---------- 拖拽上传 ----------

let dragDepth = 0;
window.addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { dragDepth++; $("#drop-overlay").hidden = false; } });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("#drop-overlay").hidden = true; } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", guard(async (e) => {
  e.preventDefault();
  dragDepth = 0;
  $("#drop-overlay").hidden = true;
  const files = [...e.dataTransfer.files];
  const videos = files.filter((f) => f.type.startsWith("video/"));
  const audios = files.filter((f) => f.type.startsWith("audio/"));
  if (videos.length) { toast(`正在上传 ${videos.length} 个视频…`); await uploadFiles("/api/videos", videos, "files"); }
  for (const a of audios) { const r = await uploadFiles("/api/music", [a], "file"); state.musicId = r.id; musicSig = ""; }
  if (!videos.length && !audios.length) return toast("只支持视频或音频文件", true);
  toast("上传完成，开始后台处理");
  refresh();
}));

// ---------- 刷新与轮询 ----------

let busy = false;
async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const active = await api("/api/jobs?active=1");
    const ind = $("#jobs-indicator");
    ind.hidden = !active.length;
    if (active.length) {
      const run = active.find((j) => j.status === "running");
      ind.innerHTML = `<span class="dot"></span>${active.length} 个任务${run ? ` · ${esc(run.message || "")} ${Math.round(run.progress * 100)}%` : ""}`;
    }
    if (state.view === "library") await loadLibrary();
    else if (state.view === "music") await loadMusicList();
    else await loadComps();
    schedule(active.length ? 1500 : 6000);
  } catch (e) {
    toast(e.message, true);
    schedule(6000);
  } finally {
    busy = false;
  }
}
let timer;
function schedule(ms) { clearTimeout(timer); timer = setTimeout(refresh, ms); }

refresh();
