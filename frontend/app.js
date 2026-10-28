// ClipEngine Frontend Orchestration

const clipForm = document.getElementById("clipForm");
const youtubeUrlInput = document.getElementById("youtubeUrl");
const clipCountSelect = document.getElementById("clipCount");
const submitBtn = document.getElementById("submitBtn");

const statusContainer = document.getElementById("statusContainer");
const statusTitle = document.getElementById("statusTitle");
const statusDesc = document.getElementById("statusDesc");
const percentText = document.getElementById("percentText");
const progressBar = document.getElementById("progressBar");

const clipsGrid = document.getElementById("clipsGrid");
const clipCountLabel = document.getElementById("clipCountLabel");

let pollInterval = null;
let currentVideoData = null;

// Initial load: fetch existing rendered clips
loadExistingClips();

clipForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = youtubeUrlInput.value.trim();
  if (!url) return;

  const maxClips = parseInt(clipCountSelect.value, 10);

  // Update UI to running state
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span>⚡ Discovering Viral Moments...</span>`;
  statusContainer.classList.remove("hidden");
  updateStatus("Initiating Jet-Speed Analysis (Audio stream & Whisper)...", 10);

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ youtube_url: url, max_clips: maxClips })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to start analysis");
    }

    const data = await res.json();
    startAnalysisPolling(data.job_id, url);
  } catch (err) {
    alert("Error: " + err.message);
    resetForm();
  }
});

function startAnalysisPolling(jobId, youtubeUrl) {
  if (pollInterval) clearInterval(pollInterval);

  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;

      const job = await res.json();
      updateStatus(job.message, job.progress);

      if (job.status === "ready_for_selection") {
        clearInterval(pollInterval);
        resetForm();
        currentVideoData = job.highlights;
        currentVideoData.youtube_url = youtubeUrl;
        renderHighlightCandidates(job.highlights);
      } else if (job.status === "failed") {
        clearInterval(pollInterval);
        alert("Analysis Failed: " + (job.error || "Unknown error"));
        resetForm();
      }
    } catch (e) {
      console.error("Poll error:", e);
    }
  }, 1500);
}

function updateStatus(message, progress) {
  statusTitle.textContent = message;
  const pct = Math.max(0, Math.min(100, progress || 0));
  percentText.textContent = `${pct}%`;
  progressBar.style.width = `${pct}%`;

  if (pct < 35) {
    statusDesc.textContent = "High-speed audio stream extraction...";
  } else if (pct < 70) {
    statusDesc.textContent = "Multi-core faster-whisper transcription (int8)...";
  } else if (pct < 90) {
    statusDesc.textContent = "Extracting viral hooks & sentence snapping...";
  } else {
    statusDesc.textContent = "Ready! Choose any clip to render and download.";
  }
}

function resetForm() {
  submitBtn.disabled = false;
  submitBtn.innerHTML = `<span>⚡ Find Viral Clips (Jet Speed)</span>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-arrow">
      <path d="M5 12h14M12 5l7 7-7 7"/>
    </svg>`;
}

function renderHighlightCandidates(data) {
  const highlights = data.highlights || [];
  clipCountLabel.textContent = `${highlights.length} viral highlights found (click to render & download)`;
  clipsGrid.innerHTML = "";

  highlights.forEach((clip, index) => {
    const card = document.createElement("div");
    card.className = "clip-card";
    card.id = `card-clip-${index + 1}`;

    card.innerHTML = `
      <div class="video-preview-wrapper" style="background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);">
        <div class="preview-placeholder">
          <div style="font-size: 2.2rem; margin-bottom: 0.5rem;">🔥</div>
          <p style="font-weight: 700; color: #f8fafc;">Viral Moment #${index + 1}</p>
          <p style="font-size: 0.8rem; color: #94a3b8;">${clip.duration}s (${clip.start_time}s - ${clip.end_time}s)</p>
        </div>
        <div class="score-badge">
          ⭐ Score: ${clip.viral_score}/100
        </div>
      </div>
      <div class="clip-body">
        <h4 class="clip-title">${escapeHtml(clip.hook_title)}</h4>
        <div class="clip-meta">
          <span>⏱️ ${clip.duration}s duration</span>
          <span>📐 1080x1920 (9:16)</span>
        </div>
        <p class="clip-reason">${escapeHtml(clip.reasoning)}</p>
        <div class="clip-actions" id="actions-${index + 1}">
          <button class="download-btn render-trigger-btn" onclick="triggerSelectiveRender(${index + 1}, ${clip.start_time}, ${clip.end_time}, '${escapeQuotes(clip.hook_title)}', ${clip.viral_score}, '${escapeQuotes(clip.reasoning)}')">
            ⚡ Render & Download (User Choice)
          </button>
        </div>
      </div>
    `;

    clipsGrid.appendChild(card);
  });
}

async function triggerSelectiveRender(clipIdx, startTime, endTime, hookTitle, viralScore, reasoning) {
  if (!currentVideoData) return;

  const actionContainer = document.getElementById(`actions-${clipIdx}`);
  if (actionContainer) {
    actionContainer.innerHTML = `
      <button class="download-btn" disabled style="background: rgba(99, 102, 241, 0.3);">
        <span class="spinner" style="width: 16px; height: 16px; border-width: 2px; margin-right: 6px;"></span>
        Rendering 9:16 vertical MP4...
      </button>
    `;
  }

  try {
    const res = await fetch("/api/render-clip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        youtube_url: currentVideoData.youtube_url,
        video_id: currentVideoData.video_id,
        clip_index: clipIdx,
        start_time: startTime,
        end_time: endTime,
        hook_title: hookTitle,
        viral_score: viralScore,
        reasoning: reasoning
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Render failed to start");
    }

    const job = await res.json();
    pollSingleRender(job.render_job_id, clipIdx);
  } catch (err) {
    alert("Render Error: " + err.message);
  }
}

function pollSingleRender(renderJobId, clipIdx) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${renderJobId}`);
      if (!res.ok) return;

      const job = await res.json();
      const actionContainer = document.getElementById(`actions-${clipIdx}`);

      if (job.status === "completed") {
        clearInterval(interval);
        const clip = job.clip;
        const card = document.getElementById(`card-clip-${clipIdx}`);

        // Update card with video preview player and instant download button
        if (card) {
          const preview = card.querySelector(".video-preview-wrapper");
          preview.innerHTML = `
            <video src="${clip.download_url}" controls autoplay playsinline></video>
            <div class="score-badge">
              🔥 Viral Score: ${clip.viral_score}/100
            </div>
          `;
        }

        if (actionContainer) {
          actionContainer.innerHTML = `
            <a href="${clip.download_url}" download="${clip.output_filename}" class="download-btn" style="background: #10b981; border-color: #10b981;">
              ✅ Download 1080x1920 MP4 (${clip.duration}s)
            </a>
          `;
        }

        // Trigger automatic user download prompt
        const dlLink = document.createElement("a");
        dlLink.href = clip.download_url;
        dlLink.download = clip.output_filename;
        document.body.appendChild(dlLink);
        dlLink.click();
        document.body.removeChild(dlLink);

      } else if (job.status === "failed") {
        clearInterval(interval);
        alert("Failed to render clip: " + (job.error || "Unknown error"));
        if (actionContainer) {
          actionContainer.innerHTML = `<button class="download-btn" onclick="location.reload()">⚠️ Retry</button>`;
        }
      }
    } catch (e) {
      console.error(e);
    }
  }, 2000);
}

function escapeQuotes(str) {
  if (!str) return "";
  return str.replace(/'/g, "\\'").replace(/"/g, "&quot;");
}

async function loadExistingClips() {
  try {
    const res = await fetch("/api/clips");
    if (!res.ok) return;
    const clips = await res.json();
    if (clips.length > 0) {
      clipCountLabel.textContent = `${clips.length} clip(s) available`;
      clipsGrid.innerHTML = "";
      clips.forEach((c) => {
        const card = document.createElement("div");
        card.className = "clip-card";
        card.innerHTML = `
          <div class="video-preview-wrapper">
            <video src="${c.url}" controls playsinline preload="metadata"></video>
            <div class="score-badge">
              ✨ Rendered Clip
            </div>
          </div>
          <div class="clip-body">
            <h4 class="clip-title">${escapeHtml(c.filename)}</h4>
            <div class="clip-meta">
              <span>💾 ${c.size_mb} MB</span>
              <span>📐 1080x1920 (9:16)</span>
            </div>
            <div class="clip-actions">
              <a href="${c.url}" download="${c.filename}" class="download-btn">
                ⬇️ Download MP4
              </a>
            </div>
          </div>
        `;
        clipsGrid.appendChild(card);
      });
    }
  } catch (e) {
    console.error("Could not fetch existing clips:", e);
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
