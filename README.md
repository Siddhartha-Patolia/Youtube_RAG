# YT_RAG — YouTube Video Q&A (RAG)

A small Retrieval-Augmented Generation app: paste a YouTube URL, and ask
questions about the video's content. It fetches the transcript, embeds it
into a local vector store, retrieves the most relevant chunks for each
question, and asks Gemini to answer using only that context.

The RAG core (`main.py`) is shared by three front ends:
- a local **Dash web app** (`app.py`),
- a **FastAPI backend** (`api.py`) deployable to Cloud Run, and
- a **Chrome extension** (`extension/`) that talks to that deployed API.

## How it works

1. **Load a video** — the transcript is fetched via the [Supadata](https://supadata.ai)
   API and split into ~1000-character overlapping chunks.
2. **Embed & index** — each chunk is embedded with Gemini's embedding model
   and stored in a local FAISS vector index, one index per video ID.
3. **Ask a question** — the question is embedded, FAISS retrieves the most
   relevant chunks (MMR search for diverse, non-redundant results), and
   those chunks are stuffed into a prompt alongside the question.
4. **Generate an answer** — Gemini answers grounded strictly in the
   retrieved context, streamed back to the caller token-by-token.

## Files

| File | Responsibility |
|---|---|
| [`main.py`](main.py) | Core RAG pipeline (`YTRag` class): transcript fetching, chunking, embedding, FAISS indexing/retrieval, and prompting/generation (one-shot and streaming, single-video and multi-video/`video_id`-scoped). No UI or transport code. |
| [`app.py`](app.py) | Dash web UI for local use: page layout, chat rendering, and the callbacks that wire buttons to `YTRag`. Streams responses via a background thread. |
| [`api.py`](api.py) | FastAPI backend exposing `YTRag` over HTTP (`/videos`, `/ask`, `/ask/stream`, `/health`) for the Chrome extension or any other remote client. |
| [`extension/`](extension) | Chrome extension (Manifest V3): a side panel UI that auto-detects the YouTube video in your current tab and calls the FastAPI backend to load it and chat with it. |
| [`Dockerfile`](Dockerfile) | Container image for deploying `api.py` to Google Cloud Run. |
| [`requirements.txt`](requirements.txt) | Python dependencies, shared by `app.py` and `api.py`. |
| [`.env`](.env) *(not committed)* | Holds `GOOGLE_API_KEY` (Gemini) and `SUPADATA_API_KEY` (transcript fetching). |
| `faiss_indexes/` *(generated, not committed)* | Per-video FAISS indexes persisted to disk, one folder per video ID, so a previously loaded video doesn't need to be re-embedded after a restart. |

## `main.py` — the `YTRag` class

- `url_parser(url)` — extracts the video ID from a YouTube URL.
- `get_transcript(url)` — fetches the transcript via the Supadata API.
  (Not `youtube_transcript_api` — YouTube blocks transcript scraping from
  most cloud-provider IPs, including Cloud Run's, so transcript fetching
  goes through Supadata's managed API instead.)
- `vectorize_transcript(transcript, video_id)` — chunks the transcript
  (`RecursiveCharacterTextSplitter`, 1000 chars / 100 overlap), embeds the
  chunks, builds a FAISS index, and saves it to `faiss_indexes/<video_id>/`.
- `process_video(url)` — orchestrates loading a video, checking caches
  first (in-memory dict → on-disk FAISS index → fresh transcript fetch +
  embed, in that order) so the same video is never re-embedded needlessly.
- `fetch_valid_chunks(query)` / `fetch_valid_chunks_for(video_id, query)` —
  run MMR retrieval (`k=5`, `fetch_k=10`) against a video's index. The
  `_for` variant builds the retriever from `vector_store_cache[video_id]`
  directly instead of shared instance state, so concurrent requests for
  different videos (as happen under `api.py`) don't clobber each other.
- `get_response` / `get_response_stream` and their `_for` counterparts —
  build the grounded prompt from retrieved chunks and call Gemini, either
  as a single blocking call or as a generator yielding the answer as it
  streams in.

The LLM (`gemini-3-flash-preview`) is configured with `temperature=0`,
`max_output_tokens=512`, and `thinking_budget=0` — grounded Q&A doesn't
need creative sampling or hidden reasoning tokens, and disabling the
latter avoids answers getting cut off mid-sentence. An `InMemoryCache`
is also registered globally so identical repeated questions return
instantly instead of re-hitting the API.

## `app.py` — the local Dash UI

- Builds the Dash layout: URL input + "Load Video" button, a chat window,
  a "generating…" status line, and the question input + "Send" button.
- `load_video` callback — calls `rag.process_video(url)` and shows the
  indexed video ID.
- `send_message` callback — appends the user's question to the chat,
  kicks off a background thread that streams `rag.get_response_stream()`
  into shared state, and enables a polling `dcc.Interval`.
- `update_stream` callback — fires on each interval tick, renders the
  in-progress answer as it grows, and finalizes it into the chat history
  once generation completes.
- Assistant replies are rendered with `dcc.Markdown` so formatting
  (bold, headers, bullet lists) from the model's answer displays properly.

Streaming runs in a plain thread (not a separate process) deliberately —
the Gemini client is gRPC-based, which doesn't survive being forked
mid-process.

## `api.py` — the FastAPI backend

A thin, stateless-per-request HTTP wrapper around `YTRag`, meant to be
deployed remotely and called by the Chrome extension:

- `GET /health` — liveness check.
- `POST /videos` `{url}` → `{video_id}` — indexes a video (or serves it
  from cache).
- `POST /ask` `{video_id, query}` → `{answer}` — one-shot answer.
- `POST /ask/stream` `{video_id, query}` — same, but streamed back as
  plain-text chunks (`StreamingResponse`) as Gemini generates them.

CORS is wide open (`allow_origins=["*"]`) since Chrome extension origins
are unpredictable (`chrome-extension://<random-id>`); tighten this to the
extension's fixed ID once it's published if you want to lock it down.

## `extension/` — the Chrome extension

A Manifest V3 **side panel** (`sidepanel.html` / `sidepanel.js` /
`sidepanel.css`, no build step) rather than a popup — it stays docked
open until you close it, surviving outside clicks and tab switches
instead of disappearing (and losing the chat) the moment you click
elsewhere on the page.

- `background.js` calls `chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })`
  so clicking the toolbar icon opens the panel.
- On open, reads the active tab's URL and pre-fills it if it looks like a
  YouTube watch page. This needs a persistent `https://www.youtube.com/*`
  host permission rather than the transient `activeTab` grant — the side
  panel API intercepts the toolbar-icon click before it reaches the usual
  `activeTab`-granting event, so `activeTab` alone isn't reliable here.
  (This auto-fill only runs once, when the panel opens — switching to a
  different video's tab while the panel stays docked open doesn't
  refresh it; paste the URL manually in that case.)
- **Load** calls `POST /videos` on the configured backend.
- Asking a question calls `POST /ask/stream` and renders the answer into
  the chat bubble incrementally as it streams in, running the streamed
  markdown (bold, bullet/numbered lists) through a small renderer in
  `sidepanel.js` so formatting displays properly instead of showing raw
  `**`/`*` characters.
- The backend URL is configurable via the ⚙ settings panel (stored with
  `chrome.storage.sync`), defaulting to the deployed Cloud Run URL.
  `manifest.json`'s `host_permissions` allow localhost, any `*.run.app`
  origin, and `youtube.com` — add another origin there (and reload the
  extension) if you host the backend elsewhere.
- Icons (`extension/icons/`) are generated at 16/32/48/128px from a
  source image with its background flood-filled to transparent, so the
  toolbar icon blends in instead of showing a white box.

Load it via `chrome://extensions` → Developer mode → **Load unpacked** →
select the `extension/` folder. Since this is a personal-scale project,
`api.py` has no per-user auth/rate limiting — everyone using this
extension shares one backend and one API quota, so don't distribute it
widely without adding that first.

## Deployment — Cloud Run

Currently deployed at `https://yt-rag-477224356188.asia-south2.run.app`.

`Dockerfile` packages `api.py` + `main.py` (see `.dockerignore` for what's
excluded, e.g. `app.py` and the Dash-only pieces aren't needed in the
container). Deploy via the Cloud Run console's **"Continuously deploy from
a repository"** option, pointed at this GitHub repo's `main` branch — it
builds from the `Dockerfile` on every push and rolls out automatically.

Required environment variables/secrets on the Cloud Run service (under
**Variables & Secrets**, referenced from Secret Manager, not hardcoded):

```
GOOGLE_API_KEY=<your Gemini API key>
SUPADATA_API_KEY=<your Supadata API key>
```

The container listens on `$PORT` (Cloud Run sets this to `8080`), per
`uvicorn api:app --host 0.0.0.0 --port ${PORT}` in the `Dockerfile`.

Caveat: the on-disk `faiss_indexes/` cache only survives for a given
container instance's lifetime — Cloud Run can spin up new instances or
scale to zero between requests, so the "skip re-embedding across
restarts" benefit doesn't fully carry over in production the way it does
locally, unless you later add persistent/shared storage.

## Setup (local Dash app)

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GOOGLE_API_KEY=your-gemini-api-key
SUPADATA_API_KEY=your-supadata-api-key
```

Run the app:

```bash
python app.py
```

Then open `http://127.0.0.1:8050`.

## Setup (local FastAPI backend, for testing the extension)

```bash
uvicorn api:app --reload
```

Runs on `http://127.0.0.1:8000` by default, matching the Chrome
extension's default backend URL.
