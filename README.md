# YT_RAG — YouTube Video Q&A (RAG)

A small Retrieval-Augmented Generation app: paste a YouTube URL, and ask
questions about the video's content. It fetches the transcript, embeds it
into a local vector store, retrieves the most relevant chunks for each
question, and asks Gemini to answer using only that context.

## How it works

1. **Load a video** — the transcript is fetched via `youtube_transcript_api`
   and split into ~1000-character overlapping chunks.
2. **Embed & index** — each chunk is embedded with Gemini's embedding model
   and stored in a local FAISS vector index, one index per video ID.
3. **Ask a question** — the question is embedded, FAISS retrieves the most
   relevant chunks (MMR search for diverse, non-redundant results), and
   those chunks are stuffed into a prompt alongside the question.
4. **Generate an answer** — Gemini answers grounded strictly in the
   retrieved context, streamed back to the UI token-by-token.

## Files

| File | Responsibility |
|---|---|
| [`main.py`](main.py) | Core RAG pipeline (`YTRag` class): transcript fetching, chunking, embedding, FAISS indexing/retrieval, and prompting/generation (both one-shot and streaming). No UI code. |
| [`app.py`](app.py) | Dash web UI: page layout, chat rendering, and the callbacks that wire buttons to `YTRag`. Owns the "generating…" indicator and the background thread that streams a response into the chat window. |
| [`requirements.txt`](requirements.txt) | Python dependencies. |
| [`.env`](.env) *(not committed)* | Holds `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) for the Gemini API. |
| `faiss_indexes/` *(generated, not committed)* | Per-video FAISS indexes persisted to disk, one folder per video ID, so a previously loaded video doesn't need to be re-embedded after a restart. |

## `main.py` — the `YTRag` class

- `url_parser(url)` — extracts the video ID from a YouTube URL.
- `get_transcript(url)` — fetches the transcript via `youtube_transcript_api`.
- `vectorize_transcript(transcript, video_id)` — chunks the transcript
  (`RecursiveCharacterTextSplitter`, 1000 chars / 100 overlap), embeds the
  chunks, builds a FAISS index, and saves it to `faiss_indexes/<video_id>/`.
- `process_video(url)` — orchestrates loading a video, checking caches
  first (in-memory dict → on-disk FAISS index → fresh transcript fetch +
  embed, in that order) so the same video is never re-embedded needlessly.
- `fetch_valid_chunks(query)` — runs MMR retrieval (`k=5`, `fetch_k=10`)
  against the loaded video's index.
- `get_response(query)` / `get_response_stream(query)` — build the grounded
  prompt from the retrieved chunks and call Gemini, either as a single
  blocking call or as a generator yielding the answer as it streams in.

The LLM (`gemini-3-flash-preview`) is configured with `temperature=0`,
`max_output_tokens=512`, and `thinking_budget=0` — grounded Q&A doesn't
need creative sampling or hidden reasoning tokens, and disabling the
latter avoids answers getting cut off mid-sentence. An `InMemoryCache`
is also registered globally so identical repeated questions return
instantly instead of re-hitting the API.

## `app.py` — the UI

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

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GOOGLE_API_KEY=your-gemini-api-key
```

Run the app:

```bash
python app.py
```

Then open `http://127.0.0.1:8050`.
