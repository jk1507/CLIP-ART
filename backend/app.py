import os
import json
import uuid
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.config import OUTPUT_DIR, BASE_DIR
from backend.pipeline import ClipEnginePipeline

app = FastAPI(title="ClipEngine API", version="1.0.0")

# Mount output and frontend static directories
frontend_dir = BASE_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
app.mount("/output_files", StaticFiles(directory=str(OUTPUT_DIR)), name="output_files")

# In-memory job store for background processing
JOBS: Dict[str, Dict[str, Any]] = {}
ANALYSIS_CACHE: Dict[str, Dict[str, Any]] = {}

class ProcessRequest(BaseModel):
    youtube_url: str
    max_clips: Optional[int] = 3

class RenderSingleRequest(BaseModel):
    youtube_url: str
    video_id: str
    clip_index: int
    start_time: float
    end_time: float
    hook_title: str
    viral_score: int
    reasoning: str

@app.get("/")
def serve_index():
    return FileResponse(frontend_dir / "index.html")

@app.post("/api/analyze")
@app.post("/api/process")
async def analyze_video(req: ProcessRequest, background_tasks: BackgroundTasks):
    """
    Step 1 (Jet-Speed): Transcribes and detects viral highlights in seconds.
    Does NOT force full video rendering up-front.
    User gets instant highlight cards and can choose which ones to render and download!
    """
    url = req.youtube_url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="YouTube URL is required")

    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {
        "job_id": job_id,
        "url": url,
        "status": "analyzing",
        "progress": 5,
        "message": "Inspecting video stream...",
        "highlights": None,
        "error": None
    }

    def run_analysis(j_id: str, target_url: str, clip_count: int):
        pipeline = ClipEnginePipeline()
        def callback(msg: str, pct: int):
            if j_id in JOBS:
                JOBS[j_id]["progress"] = pct
                JOBS[j_id]["message"] = msg

        try:
            res = pipeline.analyze_and_detect(target_url, max_clips=clip_count, progress_callback=callback)
            ANALYSIS_CACHE[res["video_id"]] = res
            JOBS[j_id]["status"] = "ready_for_selection"
            JOBS[j_id]["progress"] = 100
            JOBS[j_id]["message"] = f"Found {len(res['highlights'])} viral moments! Ready for selective download."
            JOBS[j_id]["highlights"] = res
        except Exception as e:
            JOBS[j_id]["status"] = "failed"
            JOBS[j_id]["error"] = str(e)
            JOBS[j_id]["message"] = f"Failed: {str(e)}"

    background_tasks.add_task(run_analysis, job_id, url, req.max_clips or 3)
    return {"job_id": job_id, "status": "analyzing"}

@app.post("/api/render-clip")
async def render_chosen_clip(req: RenderSingleRequest, background_tasks: BackgroundTasks):
    """
    Step 2 (On-Demand Render & Download):
    Renders ONLY the specific clip chosen by the user in high speed!
    """
    render_job_id = f"render_{req.video_id}_{req.clip_index}_{str(uuid.uuid4())[:4]}"
    JOBS[render_job_id] = {
        "job_id": render_job_id,
        "status": "rendering",
        "progress": 10,
        "message": f"Rendering clip '{req.hook_title}' in 1080x1920...",
        "clip": None,
        "error": None
    }

    def run_single_render(r_id: str, data: RenderSingleRequest):
        pipeline = ClipEnginePipeline()
        def callback(msg: str, pct: int):
            if r_id in JOBS:
                JOBS[r_id]["progress"] = pct
                JOBS[r_id]["message"] = msg

        try:
            cached_analysis = ANALYSIS_CACHE.get(data.video_id, {})
            words = cached_analysis.get("words", [])
            clip_res = pipeline.render_single_highlight(
                youtube_url=data.youtube_url,
                video_id=data.video_id,
                clip_idx=data.clip_index,
                start_time=data.start_time,
                end_time=data.end_time,
                hook_title=data.hook_title,
                viral_score=data.viral_score,
                reasoning=data.reasoning,
                words=words,
                progress_callback=callback
            )
            JOBS[r_id]["status"] = "completed"
            JOBS[r_id]["progress"] = 100
            JOBS[r_id]["message"] = "Render complete! Ready to download."
            JOBS[r_id]["clip"] = clip_res
        except Exception as e:
            JOBS[r_id]["status"] = "failed"
            JOBS[r_id]["error"] = str(e)
            JOBS[r_id]["message"] = f"Render failed: {str(e)}"

    background_tasks.add_task(run_single_render, render_job_id, req)
    return {"render_job_id": render_job_id, "status": "rendering"}

@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return JOBS[job_id]

@app.get("/api/clips")
def list_clips():
    """Lists all previously exported clips in the output folder."""
    clips = []
    for file in OUTPUT_DIR.glob("*_9x16.mp4"):
        clips.append({
            "filename": file.name,
            "url": f"/output_files/{file.name}",
            "size_mb": round(file.stat().st_size / (1024 * 1024), 2),
            "created": file.stat().st_mtime
        })
    clips.sort(key=lambda x: x["created"], reverse=True)
    return clips
