from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from main import YTRag

app = FastAPI(title="YT RAG API")

# Chrome extension origins are unpredictable (chrome-extension://<random-id>),
# so allow all origins for now; tighten to the extension's fixed ID once known.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

rag = YTRag()


class ProcessVideoRequest(BaseModel):
    url: str


class AskRequest(BaseModel):
    video_id: str
    query: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/videos")
def process_video(req: ProcessVideoRequest):
    try:
        rag.process_video(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"video_id": rag.vid_id}


@app.post("/ask")
def ask(req: AskRequest):
    if req.video_id not in rag.vector_store_cache:
        raise HTTPException(status_code=404, detail="Video not indexed. Call /videos first.")
    answer = rag.get_response_for(req.video_id, req.query)
    return {"answer": answer}


@app.post("/ask/stream")
def ask_stream(req: AskRequest):
    if req.video_id not in rag.vector_store_cache:
        raise HTTPException(status_code=404, detail="Video not indexed. Call /videos first.")

    def event_stream():
        prev = ""
        for partial in rag.get_response_stream_for(req.video_id, req.query):
            yield partial[len(prev):]
            prev = partial

    return StreamingResponse(event_stream(), media_type="text/plain")
