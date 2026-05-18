from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import base64
import re
import sys
import asyncio
import os
import uuid
import traceback

_TRANSCRIPT_PREFIX = re.compile(r'^(Human|User|Assistant|Thought|Action|Observation|Tool)\s*:\s*', re.IGNORECASE)

def _sanitize_response(text: str) -> str:
    """Strip any transcript-style prefix lines the model accidentally emits."""
    lines = text.splitlines()
    clean = [l for l in lines if not _TRANSCRIPT_PREFIX.match(l)]
    return "\n".join(clean).strip()

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from src.agent import get_me_agent
from src.workflows.email_automation import manual_email_triage
from src.auth.google_auth import build_flow, save_creds_from_flow, has_token
from src.tools.sms import send_sms
from src.utils.security import verify_owner, verify_twilio

load_dotenv()

# Allow Google to return broader scopes than requested (adds openid/userinfo automatically)
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def _materialize_google_token():
    """Backwards compat: decode legacy GOOGLE_TOKEN_B64 env var into token.json."""
    if os.path.exists("token.json"):
        return
    encoded = os.getenv("GOOGLE_TOKEN_B64")
    if not encoded:
        return
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        with open("token.json", "w") as f:
            f.write(decoded)
        print("✅ token.json materialized from GOOGLE_TOKEN_B64")
    except Exception as e:
        print(f"⚠️  Failed to materialize token.json: {e}")


def _redirect_uri(request: Request) -> str:
    """Build the OAuth callback URL from the incoming request, honoring proxy headers."""
    base = os.getenv("OAUTH_REDIRECT_BASE")  # optional override
    if base:
        return base.rstrip("/") + "/auth/google/callback"
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host"))
    return f"{proto}://{host}/auth/google/callback"


@asynccontextmanager
async def lifespan(app: FastAPI):
    _materialize_google_token()
    # --- Startup readiness check ---
    missing = []
    for key in ("XAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
                "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "MY_PHONE_NUMBER"):
        if not os.getenv(key):
            missing.append(key)
    if missing:
        print(f"⚠️  STARTUP: missing env vars: {', '.join(missing)}")
    else:
        print("✅ STARTUP: all required env vars present")
    if not has_token():
        print("⚠️  STARTUP: Google token missing — visit /auth/google to authorize")
    else:
        print("✅ STARTUP: Google token present")
    # --- Scheduler ---
    try:
        from src.workflows.automation import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"⚠️  Scheduler disabled during startup: {e}")
    yield


app = FastAPI(title="AI Me - Wesley's Personal Agent", lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = None  # For memory persistence

class BlogRequest(BaseModel):
    topic: str
    keywords: list[str] = []
    notes: str = ""           # extra context/direction, or Wesley's answers to needs_input questions
    word_count: int = 600     # target length
    callback_url: str = ""    # if set, return immediately and POST result here when done

@app.get("/ping")
async def ping():
    """Public liveness check — call this first to wake the server before sending a chat message."""
    return {"alive": True}


@app.post("/chat", dependencies=[Depends(verify_owner)])
async def chat(request: ChatRequest):
    """Talk to your AI Me with memory"""
    thread_id = request.thread_id or str(uuid.uuid4())
    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: get_me_agent().invoke(
                    {"messages": [{"role": "user", "content": request.message}]},
                    config={"configurable": {"thread_id": thread_id}},
                ),
            ),
            timeout=90,  # 90 s — enough for multi-tool chains, under Render's hard limit
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={"error": "Request timed out after 90 seconds. The server may be waking up — try again."},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})

    return {
        "response": _sanitize_response(result["messages"][-1].content),
        "thread_id": thread_id
    }


@app.post("/generate/blog", dependencies=[Depends(verify_owner)])
async def generate_blog(request: BlogRequest, background_tasks: BackgroundTasks):
    """Generate a blog post in Wesley's voice.

    First checks RAG memory for Wesley's existing opinions/content on the topic.
    If context is thin and no notes are provided, returns questions for Wesley
    to answer before generating (status: 'needs_input').

    If callback_url is set, returns immediately with {"status": "processing", "job_id": "..."}
    and POSTs the finished result to that URL when done. Otherwise, waits synchronously.
    """
    from src.agent import SYSTEM_PROMPT
    from src.memory.rag_memory import retrieve_relevant_memory
    from langchain_xai import ChatXAI
    from langchain_core.messages import SystemMessage, HumanMessage

    async def _run_generation(req: BlogRequest, job_id: str, callback: str):
        """Core generation logic — runs inline (sync) or as a background task."""
        import httpx

        async def _post_callback(payload: dict):
            if not callback:
                return
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    await client.post(callback, json=payload)
            except Exception:
                pass  # best-effort delivery

        try:
            llm = ChatXAI(model="grok-3-latest")
            loop = asyncio.get_event_loop()

            # Check RAG memory for Wesley's existing content on this topic
            context = ""
            try:
                context = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: retrieve_relevant_memory(req.topic, k=5)),
                    timeout=10,
                )
            except Exception:
                context = ""

            context_is_thin = len(context.strip()) < 300

            # If no existing content and no notes from Wesley, ask him first
            if context_is_thin and not req.notes:
                q_prompt = (
                    f"I need to write a blog post about: '{req.topic}'\n"
                    f"I don't have enough of my own content on this topic yet. "
                    f"Generate 3-4 short, specific questions to ask me so the post reflects my actual "
                    f"experience and opinions — not generic advice. Return ONLY a JSON array of question strings."
                )
                q_result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: llm.invoke([
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=q_prompt),
                    ])),
                    timeout=30,
                )
                import json as _json
                raw_q = q_result.content.strip()
                if raw_q.startswith("```"):
                    raw_q = re.sub(r"^```[a-z]*\n?", "", raw_q).rstrip("` \n")
                try:
                    questions = _json.loads(raw_q)
                except Exception:
                    questions = [raw_q]
                payload = {
                    "status": "needs_input",
                    "job_id": job_id,
                    "topic": req.topic,
                    "questions": questions,
                    "instructions": "Answer these questions and resubmit with your answers in the 'notes' field.",
                }
                await _post_callback(payload)
                return payload

            # Generate the post grounded in Wesley's actual content
            kw_line = f"\nKeywords to work in naturally: {', '.join(req.keywords)}" if req.keywords else ""
            notes_line = f"\nWesley's direct input on this topic:\n{req.notes}" if req.notes else ""
            context_line = f"\n\nRelevant context from Wesley's existing content:\n{context}" if context.strip() else ""

            prompt = (
                f"Write a blog post for taskbullet.com in my voice.\n"
                f"Topic: {req.topic}{kw_line}{notes_line}{context_line}\n"
                f"Target length: ~{req.word_count} words.\n\n"
                f"Ground the post in the real context and opinions above — don't invent takes I haven't expressed. "
                f"Format: compelling title on line 1 (no 'Title:' prefix), blank line, then the post body. "
                f"No meta-commentary. Just the title and post."
            )

            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: llm.invoke([
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ])),
                timeout=60,
            )
            raw = result.content.strip()
            lines = raw.split("\n", 2)
            title = lines[0].strip()
            body = lines[2].strip() if len(lines) >= 3 else (lines[1].strip() if len(lines) >= 2 else raw)
            payload = {
                "status": "ready",
                "job_id": job_id,
                "title": title,
                "body": body,
                "word_count": len(body.split()),
                "grounded_in_memory": not context_is_thin,
            }
            await _post_callback(payload)
            return payload

        except Exception as e:
            payload = {"status": "error", "job_id": job_id, "detail": str(e)}
            await _post_callback(payload)
            return payload

    job_id = str(uuid.uuid4())

    if request.callback_url:
        # Async mode — return immediately, deliver result to callback when done
        background_tasks.add_task(
            lambda: asyncio.run(_run_generation(request, job_id, request.callback_url))
        )
        return {"status": "processing", "job_id": job_id}
    else:
        # Sync mode — wait and return directly
        try:
            result = await asyncio.wait_for(_run_generation(request, job_id, ""), timeout=90)
            return result
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Blog generation timed out.")


@app.post("/email/triage", dependencies=[Depends(verify_owner)])
async def trigger_email_triage():
    """Manually trigger proactive inbox triage. Creates drafts for reply-needed emails."""
    report = await manual_email_triage()
    return {"status": "Email triage complete", "report": report}


@app.post("/sms", dependencies=[Depends(verify_twilio)])
async def sms_webhook(request: Request):
    """Twilio SMS webhook — receives an incoming text, runs the agent, replies via SMS."""
    # Note: verify_twilio already consumed and validated the form body.
    # Re-read it here (FastAPI caches the form parse within the request lifetime).
    form = await request.form()
    incoming_message = form.get("Body", "")
    from_number = form.get("From", "")

    if not incoming_message or not from_number:
        return {"status": "ignored"}

    result = get_me_agent().invoke(
        {"messages": [{"role": "user", "content": incoming_message}]},
        config={"configurable": {"thread_id": f"sms-{from_number}"}},
    )
    reply = result["messages"][-1].content

    # Truncate to SMS limit (1600 chars to leave room for Twilio overhead)
    send_sms(from_number, reply[:1600])

    return {"status": "ok"}


@app.post("/voice", dependencies=[Depends(verify_twilio)])
async def voice_webhook(request: Request):
    """Twilio Voice webhook — spoken conversation with Me."""
    from twilio.twiml.voice_response import VoiceResponse, Gather
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    speech = form.get("SpeechResult", "").strip()

    if speech:
        try:
            result = get_me_agent().invoke(
                {"messages": [{"role": "user", "content": speech}]},
                config={"configurable": {"thread_id": f"voice-{call_sid}"}},
            )
            reply = _sanitize_response(result["messages"][-1].content)[:500]
        except Exception as e:
            reply = "Sorry, I ran into an issue. Try again."
            print(f"Voice agent error: {e}")
    else:
        reply = "Hey, it's Me. What do you need?"

    resp = VoiceResponse()
    gather = Gather(input="speech", action="/voice", timeout=5, speechTimeout="auto")
    gather.say(reply, voice="Polly.Joanna")
    resp.append(gather)
    # Fallback if caller says nothing after timeout
    resp.say("I didn't catch that. Call back anytime.", voice="Polly.Joanna")
    return Response(content=str(resp), media_type="text/xml")


@app.get("/drafts", dependencies=[Depends(verify_owner)])
async def get_drafts():
    """List current Gmail drafts as structured JSON."""
    try:
        from src.tools.email import _list_gmail_drafts
        drafts = _list_gmail_drafts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch drafts: {e}")
    return {"drafts": drafts}


@app.post("/drafts/{draft_id}/send", dependencies=[Depends(verify_owner)])
async def send_draft(draft_id: str):
    """Send a Gmail draft by id."""
    try:
        from src.tools.email import _send_gmail_draft
        _send_gmail_draft(draft_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not send draft: {e}")
    return {"sent": True, "draft_id": draft_id}


@app.get("/plan/weekly", dependencies=[Depends(verify_owner)])
async def weekly_plan():
    """Manually trigger weekly plan"""
    try:
        from src.workflows.automation import send_weekly_plan
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Weekly planner unavailable: {e}")
    plan = await send_weekly_plan()
    return {"status": "Weekly plan generated", "plan": plan}

@app.post("/upload", dependencies=[Depends(verify_owner)])
async def upload_note(file: UploadFile = File(...)):
    """Upload a .txt or .md file into long-term RAG memory."""
    allowed = {".txt", ".md"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Only .txt and .md are accepted.",
        )
    try:
        from src.tools.rag_upload import upload_note_from_text
        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")
        chunks = upload_note_from_text(text, title=file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    return {"chunks": chunks, "title": file.filename}


@app.post("/transcribe-drive-videos", dependencies=[Depends(verify_owner)])
async def transcribe_drive_videos(folder_id: str = "1InK4vWIsweRJzAzge3B2OagEO7U4Rb7R", label: str = "video transcript"):
    """Download video/audio files from a Drive folder, transcribe with Whisper,
    and store transcripts in RAG memory.

    Defaults to Wesley's videos folder. Skips files over 24MB (Whisper API limit).
    Returns a summary of what was transcribed.
    """
    try:
        import io
        import openai
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        from src.auth.google_auth import DRIVE_READONLY_SCOPE, load_creds as _load_creds
        from src.tools.rag_upload import upload_note_from_text

        import io
        import subprocess
        import tempfile
        import math
        import openai
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        from src.auth.google_auth import DRIVE_READONLY_SCOPE, load_creds as _load_creds
        from src.tools.rag_upload import upload_note_from_text

        WHISPER_MAX_BYTES = 24 * 1024 * 1024  # 24 MB — Whisper API hard limit is 25 MB
        CHUNK_SECS = 18 * 60               # 18-minute chunks for long files
        AUDIO_VIDEO_MIMES = {
            "video/mp4", "video/quicktime", "video/x-msvideo", "video/webm",
            "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/webm",
        }

        def _extract_compressed_audio(src_path: str, dest_path: str):
            """Use ffmpeg to extract mono 32kbps mp3 — keeps file small for Whisper."""
            subprocess.run(
                ["ffmpeg", "-i", src_path, "-vn", "-ar", "16000",
                 "-ac", "1", "-b:a", "32k", "-y", dest_path],
                check=True, capture_output=True,
            )

        def _get_duration(audio_path: str) -> float:
            """Return duration in seconds via ffprobe."""
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                capture_output=True, text=True, check=True,
            )
            return float(r.stdout.strip())

        def _transcribe_file(oai_client, path: str, filename: str) -> str:
            with open(path, "rb") as fh:
                fh.name = filename
                return oai_client.audio.transcriptions.create(model="whisper-1", file=fh).text

        creds = _load_creds([DRIVE_READONLY_SCOPE])
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)

        # List all video/audio files in folder
        q = f"'{folder_id}' in parents and trashed = false"
        results = svc.files().list(
            q=q, pageSize=50, fields="files(id, name, mimeType, size)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        files = [f for f in results.get("files", []) if f.get("mimeType", "") in AUDIO_VIDEO_MIMES]

        if not files:
            return {"message": "No video/audio files found in that folder.", "transcribed": 0}

        oai = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        transcribed = 0
        skipped = []
        errors = []

        for f in files:
            tmp_video = tmp_audio = None
            try:
                # Download video to temp file
                ext = os.path.splitext(f["name"])[1] or ".mp4"
                tmp_video = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                request_dl = svc.files().get_media(fileId=f["id"], supportsAllDrives=True)
                downloader = MediaIoBaseDownload(tmp_video, request_dl)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                tmp_video.flush()
                tmp_video_path = tmp_video.name
                tmp_video.close()

                # Extract compressed audio
                tmp_audio_path = tmp_video_path + ".mp3"
                _extract_compressed_audio(tmp_video_path, tmp_audio_path)
                audio_size = os.path.getsize(tmp_audio_path)

                if audio_size <= WHISPER_MAX_BYTES:
                    # Small enough — transcribe directly
                    text = _transcribe_file(oai, tmp_audio_path, f["name"] + ".mp3")
                else:
                    # Too long — split into CHUNK_SECS chunks
                    duration = _get_duration(tmp_audio_path)
                    n_chunks = math.ceil(duration / CHUNK_SECS)
                    parts = []
                    for i in range(n_chunks):
                        chunk_path = tmp_audio_path + f".chunk{i}.mp3"
                        start = i * CHUNK_SECS
                        subprocess.run(
                            ["ffmpeg", "-i", tmp_audio_path, "-ss", str(start),
                             "-t", str(CHUNK_SECS), "-y", chunk_path],
                            check=True, capture_output=True,
                        )
                        parts.append(_transcribe_file(oai, chunk_path, f"chunk{i}.mp3"))
                        os.unlink(chunk_path)
                    text = " ".join(parts)

                if text.strip():
                    upload_note_from_text(text.strip(), title=f"{label} — {f['name']}")
                    transcribed += 1

            except Exception as e:
                errors.append({"file": f["name"], "error": str(e)})
            finally:
                for p in [getattr(tmp_video, 'name', None),
                          (tmp_video.name + ".mp3") if tmp_video else None]:
                    if p and os.path.exists(p):
                        try:
                            os.unlink(p)
                        except Exception:
                            pass

        return {
            "transcribed": transcribed,
            "skipped": skipped,
            "errors": errors,
            "files_found": [f["name"] for f in files],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/ingest-social-videos", dependencies=[Depends(verify_owner)])
async def ingest_social_videos(
    url: str,
    label: str = "",
    limit: int = 50,
):
    """Download audio from any social video page (Facebook, YouTube, Instagram, TikTok, etc.)
    using yt-dlp, transcribe with Whisper, and store in RAG memory.

    `url`   — page/channel/playlist URL or single video URL
    `label` — tag stored with each transcript (e.g. 'taskbullet facebook reels')
    `limit` — max number of videos to process (default 50)

    Note: Facebook may require cookies for private/restricted content.
    Public pages like facebook.com/TaskBullet/reels/ should work without auth.
    """
    try:
        import tempfile
        import yt_dlp
        import openai

        from src.tools.rag_upload import upload_note_from_text

        WHISPER_MAX_BYTES = 24 * 1024 * 1024
        CHUNK_SECS = 18 * 60
        tag = label or url

        oai = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        def _transcribe_path(path: str, name: str) -> str:
            import math, subprocess
            size = os.path.getsize(path)
            if size <= WHISPER_MAX_BYTES:
                with open(path, "rb") as fh:
                    fh.name = name
                    return oai.audio.transcriptions.create(model="whisper-1", file=fh).text
            # Split into chunks
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, check=True,
            )
            duration = float(r.stdout.strip())
            n_chunks = math.ceil(duration / CHUNK_SECS)
            parts = []
            for i in range(n_chunks):
                chunk_path = path + f".chunk{i}.mp3"
                subprocess.run(
                    ["ffmpeg", "-i", path, "-ss", str(i * CHUNK_SECS),
                     "-t", str(CHUNK_SECS), "-y", chunk_path],
                    check=True, capture_output=True,
                )
                with open(chunk_path, "rb") as fh:
                    fh.name = f"chunk{i}.mp3"
                    parts.append(oai.audio.transcriptions.create(model="whisper-1", file=fh).text)
                os.unlink(chunk_path)
            return " ".join(parts)

        transcribed = 0
        errors = []

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "32",
                }],
                "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "playlistend": limit,
                "ignoreerrors": True,   # skip unavailable videos
                "extract_flat": False,
            }

            loop = asyncio.get_event_loop()

            def _download_and_transcribe():
                nonlocal transcribed
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)

                entries = []
                if info:
                    if "entries" in info:
                        entries = [e for e in info["entries"] if e]
                    else:
                        entries = [info]

                for entry in entries:
                    video_id = entry.get("id", "unknown")
                    title = entry.get("title", video_id)
                    audio_path = os.path.join(tmpdir, f"{video_id}.mp3")
                    if not os.path.exists(audio_path):
                        errors.append({"video": title, "error": "audio file not found after download"})
                        continue
                    try:
                        text = _transcribe_path(audio_path, f"{video_id}.mp3")
                        if text.strip():
                            upload_note_from_text(text.strip(), title=f"{tag} — {title}")
                            transcribed += 1
                    except Exception as e:
                        errors.append({"video": title, "error": str(e)})

            await asyncio.wait_for(
                loop.run_in_executor(None, _download_and_transcribe),
                timeout=600,  # 10 min max for a batch
            )

        return {
            "transcribed": transcribed,
            "errors": errors,
            "source_url": url,
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Social video ingest timed out (10 min limit).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/ingest-drive-folder", dependencies=[Depends(verify_owner)])
async def ingest_drive_folder(folder_id: str, label: str = ""):
    """Read all Google Docs in a Drive folder and store them in long-term RAG memory.

    Pass the bare folder ID from the Drive URL. Optionally set `label` to tag
    the chunks (e.g. 'church talks'). Returns a summary of what was ingested.
    """
    try:
        from googleapiclient.discovery import build
        from src.auth.google_auth import DRIVE_READONLY_SCOPE, DOCS_READONLY_SCOPE, load_creds as _load_creds
        from src.tools.rag_upload import upload_note_from_text
        from src.tools.google_docs import _doc_to_text

        drive_creds = _load_creds([DRIVE_READONLY_SCOPE])
        drive_svc = build("drive", "v3", credentials=drive_creds, cache_discovery=False)
        docs_creds = _load_creds([DOCS_READONLY_SCOPE])
        docs_svc = build("docs", "v1", credentials=docs_creds, cache_discovery=False)

        # List all Google Docs in the folder
        q = (f"'{folder_id}' in parents and "
             "mimeType = 'application/vnd.google-apps.document' and trashed = false")
        results = drive_svc.files().list(
            q=q,
            pageSize=200,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = results.get("files", [])
        if not files:
            return {"message": "No Google Docs found in that folder.", "ingested": 0, "total_chunks": 0}

        ingested = 0
        total_chunks = 0
        errors = []
        tag = label or folder_id
        for f in files:
            try:
                doc = docs_svc.documents().get(documentId=f["id"]).execute()
                text = _doc_to_text(doc)
                if not text.strip():
                    continue
                n = upload_note_from_text(text, title=f"{tag} — {f['name']}")
                total_chunks += n
                ingested += 1
            except Exception as doc_err:
                errors.append({"file": f["name"], "error": str(doc_err)})

        return {
            "ingested": ingested,
            "total_chunks": total_chunks,
            "skipped_errors": errors,
            "files": [f["name"] for f in files],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/")
async def root():
    """Serve the chat UI"""
    return FileResponse("static/index.html")

@app.get("/api")
async def api_status():
    return {"status": "✅ AI Me is running with automation", "message": "Daily briefing (7am) & weekly plan (Sun 8pm) active"}

@app.get("/health")
async def health():
    """Public health check — minimal to avoid leaking config info."""
    from src.auth.google_auth import has_token
    authorized = has_token()
    return {
        "status": "ok",
        "google_authorized": authorized,
        "google_action": None if authorized else "Visit /auth/google to authorize",
    }


@app.get("/health/full", dependencies=[Depends(verify_owner)])
async def health_full():
    """Full diagnostics — owner only."""
    keys = ["XAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_DB_URL",
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER",
            "MY_PHONE_NUMBER", "APP_PASSWORD"]
    status = {k: ("set" if os.getenv(k) else "MISSING") for k in keys}
    status["google_token"] = "present" if has_token() else "MISSING (visit /auth/google to authorize)"
    try:
        import twilio  # noqa: F401
        status["twilio_module"] = "installed"
    except ImportError:
        status["twilio_module"] = "MISSING"
    return status


# In-memory OAuth state store — avoids cross-domain cookie issues with Render + custom domain.
# Maps state token -> {code_verifier, expires_at}. Single instance; TTL is 10 min.
import time as _time
_oauth_state_store: dict = {}

def _store_oauth_state(state: str, code_verifier: str):
    """Save state → verifier with a 10-min TTL."""
    _oauth_state_store[state] = {"code_verifier": code_verifier, "expires_at": _time.time() + 600}
    # Prune expired entries opportunistically
    now = _time.time()
    expired = [k for k, v in _oauth_state_store.items() if v["expires_at"] < now]
    for k in expired:
        del _oauth_state_store[k]

def _pop_oauth_state(state: str) -> str | None:
    """Return code_verifier for the given state and remove it. Returns None if missing/expired."""
    entry = _oauth_state_store.pop(state, None)
    if not entry:
        return None
    if entry["expires_at"] < _time.time():
        return None
    return entry["code_verifier"]


@app.get("/diagnostics", dependencies=[Depends(verify_owner)])
async def diagnostics():
    """Owner-only: real-time subsystem health — Google, Twilio, Supabase, scheduler, reminders."""
    from datetime import timezone as _tz
    result: dict = {}

    # --- Google ---
    try:
        from src.auth.google_auth import (
            CORE_SCOPES,
            OPTIONAL_SCOPES,
            _load_token_dict,
            load_creds,
            missing_optional_scopes,
            missing_required_scopes,
        )
        token_data = _load_token_dict()
        creds = load_creds()
        result["google"] = {
            "token_present": True,
            "valid": creds.valid,
            "expired": creds.expired,
            "has_refresh_token": bool(creds.refresh_token),
            "granted_scopes": list(creds.scopes or []),
            "core_scopes": CORE_SCOPES,
            "optional_scopes": OPTIONAL_SCOPES,
            "missing_core_scopes": missing_required_scopes(token_data),
            "missing_optional_scopes": missing_optional_scopes(token_data),
        }
    except Exception as e:
        try:
            from src.auth.google_auth import (
                CORE_SCOPES,
                OPTIONAL_SCOPES,
                _load_token_dict,
                missing_optional_scopes,
                missing_required_scopes,
            )
            token_data = _load_token_dict()
            result["google"] = {
                "token_present": bool(token_data),
                "core_scopes": CORE_SCOPES,
                "optional_scopes": OPTIONAL_SCOPES,
                "missing_core_scopes": missing_required_scopes(token_data),
                "missing_optional_scopes": missing_optional_scopes(token_data),
                "error": str(e),
            }
        except Exception as status_error:
            result["google"] = {"token_present": False, "error": str(e), "status_error": str(status_error)}

    # --- Twilio ---
    from src.tools.sms import _twilio_configured
    twilio_ok, twilio_reason = _twilio_configured()
    result["twilio"] = {
        "configured": twilio_ok,
        "my_phone_set": bool(os.getenv("MY_PHONE_NUMBER")),
        "reason": twilio_reason or "ok",
    }

    # --- Supabase ---
    try:
        from supabase import create_client as _sb
        sb = _sb(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        sb.table("reminders").select("id").limit(1).execute()
        result["supabase"] = {"connected": True}
    except Exception as e:
        result["supabase"] = {"connected": False, "error": str(e)}

    # --- Scheduler ---
    try:
        from src.workflows.automation import scheduler as _sched
        jobs = []
        for job in _sched.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "next_run": next_run.isoformat() if next_run else "paused",
            })
        result["scheduler"] = {"running": _sched.running, "jobs": jobs}
    except Exception as e:
        result["scheduler"] = {"running": False, "error": str(e)}

    # --- Reminders ---
    try:
        from supabase import create_client as _sb2
        from datetime import datetime as _dt
        sb2 = _sb2(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        now_iso = _dt.now(_tz.utc).isoformat()
        pending = sb2.table("reminders").select("id", count="exact").eq("fired", False).execute()
        overdue = sb2.table("reminders").select("id", count="exact").eq("fired", False).lte("remind_at", now_iso).execute()
        result["reminders"] = {
            "pending": pending.count,
            "overdue": overdue.count,
        }
    except Exception as e:
        result["reminders"] = {"error": str(e)}

    return result


@app.post("/diagnostics/check-reminders", dependencies=[Depends(verify_owner)])
async def manual_check_reminders():
    """Owner-only: force-run the reminder check job right now. Use to test without waiting an hour."""
    try:
        from src.workflows.automation import check_reminders
        await check_reminders()
        return {"status": "ok", "message": "Reminder check complete — see Render logs for details"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reminder check failed: {e}")



@app.get("/auth/google")
async def auth_google_start(request: Request):
    """Kick off Google OAuth. Visit this in a browser, click Allow, done."""
    flow = build_flow(_redirect_uri(request))
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force refresh_token issuance
    )
    # Store state server-side — avoids cross-domain cookie loss (onrender.com vs wesleynappi.com)
    _store_oauth_state(state, flow.code_verifier or "")
    return RedirectResponse(auth_url)


@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    """Google redirects here after user clicks Allow. Saves token to Supabase."""
    try:
        returned_state = request.query_params.get("state")
        if not returned_state:
            raise RuntimeError("Missing state parameter in callback. Start again at /auth/google")

        code_verifier = _pop_oauth_state(returned_state)
        if code_verifier is None:
            raise RuntimeError(
                "OAuth state not found or expired (10-min limit). Start again at /auth/google"
            )

        flow = build_flow(_redirect_uri(request))
        flow.fetch_token(
            authorization_response=str(request.url),
            code_verifier=code_verifier if code_verifier else None,
        )
        host = (request.url.hostname or "").lower()
        require_supabase = host not in {"127.0.0.1", "localhost"}
        status = save_creds_from_flow(flow, require_supabase=require_supabase)
    except Exception as e:
        return HTMLResponse(
            f"<h2>OAuth failed</h2><pre>{traceback.format_exc()}</pre>",
            status_code=500,
        )
    if status.get("verified_in_supabase"):
        persistence_note = "<p>Token saved and <strong>verified in Supabase</strong> — will survive all future redeploys.</p>"
    elif status.get("saved_to_file"):
        persistence_note = "<p>⚠️ Supabase unavailable — token saved to local file only. Authorize again once Supabase recovers to make it permanent.</p>"
    else:
        persistence_note = "<p>⚠️ Token may not have persisted. Check Render logs.</p>"
    return HTMLResponse(
        f"<h2>✅ Google authorized.</h2>"
        f"{persistence_note}"
        "<p>Calendar + Gmail tools are live.</p>"
        "<p><a href='/'>Back to chat</a></p>"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
