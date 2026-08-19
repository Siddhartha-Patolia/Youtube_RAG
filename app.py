import threading
from dash import Dash, html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
from main import YTRag

rag = YTRag()

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
)

# -----------------------------
# Shared state for the in-flight streamed answer.
# A background thread (not a process) writes to this while the
# stream-interval polls it -- avoids forking the process, which
# hangs the Gemini gRPC client.
# -----------------------------
stream_state = {
    "answer": "",
    "generating": False,
    "done": True,
    "consumed": True,
}


def _generate_worker(question):
    stream_state["generating"] = True
    try:
        for partial in rag.get_response_stream(question):
            stream_state["answer"] = partial
    finally:
        stream_state["generating"] = False
        stream_state["done"] = True


# -----------------------------
# Helper to create a chat bubble
# -----------------------------
def create_message(role, text):

    if role == "user":
        return html.Div(
            text,
            style={
                "backgroundColor": "#007bff",
                "color": "white",
                "padding": "12px",
                "borderRadius": "12px",
                "margin": "8px",
                "maxWidth": "70%",
                "marginLeft": "auto",
            },
        )

    return dcc.Markdown(
        text,
        style={
            "backgroundColor": "#eeeeee",
            "padding": "12px",
            "borderRadius": "12px",
            "margin": "8px",
            "maxWidth": "70%",
        },
    )


def render_chat(history, live_text=None):
    chat = [create_message(msg["role"], msg["text"]) for msg in history]
    if live_text is not None:
        chat.append(create_message("assistant", live_text))
    return chat


# -----------------------------
# Layout
# -----------------------------
app.layout = dbc.Container(
    [
        html.H2("🎥 YouTube RAG"),
        html.Br(),
        dbc.Row(
            [
                dbc.Col(
                    dcc.Input(
                        id="url",
                        placeholder="Paste YouTube URL",
                        style={"width": "100%"},
                    ),
                    width=9,
                ),
                dbc.Col(
                    dbc.Button(
                        "Load Video",
                        id="load-btn",
                        color="primary",
                    ),
                    width=3,
                ),
            ]
        ),
        html.Hr(),
        html.Div(
            id="video-status",
            children="No video loaded.",
        ),
        html.Hr(),
        html.Div(
            id="chat-window",
            style={
                "height": "450px",
                "overflowY": "scroll",
                "border": "1px solid lightgray",
                "padding": "10px",
                "backgroundColor": "#fafafa",
            },
        ),
        html.Div(
            id="gen-indicator",
            style={
                "fontSize": "0.85em",
                "color": "#888",
                "height": "20px",
                "margin": "4px 0",
            },
        ),
        dbc.Row(
            [
                dbc.Col(
                    dcc.Input(
                        id="question",
                        placeholder="Ask something...",
                        style={"width": "100%"},
                    ),
                    width=10,
                ),
                dbc.Col(
                    dbc.Button(
                        "Send",
                        id="send-btn",
                        color="success",
                    ),
                    width=2,
                ),
            ]
        ),

        # Hidden conversation state
        dcc.Store(
            id="chat-history",
            data=[],
        ),

        # Polls stream_state while a response is being generated
        dcc.Interval(
            id="stream-interval",
            interval=300,
            disabled=True,
        ),
    ],
    fluid=True,
)


# -----------------------------
# Index video callback
# -----------------------------
@callback(
    Output("video-status", "children"),
    Input("load-btn", "n_clicks"),
    State("url", "value"),
    prevent_initial_call=True,
)
def load_video(_,url):
    rag.process_video(url)
    return f"Video ID: {rag.vid_id} indexed successfully."


# -----------------------------
# Send message: kicks off generation in a background thread
# -----------------------------
@callback(
    Output("chat-window", "children"),
    Output("chat-history", "data"),
    Output("question", "value"),
    Output("stream-interval", "disabled"),
    Output("gen-indicator", "children"),
    Input("send-btn", "n_clicks"),
    State("question", "value"),
    State("chat-history", "data"),
    prevent_initial_call=True,
)
def send_message(_, question, history):

    if not question or stream_state["generating"]:
        raise PreventUpdate

    history.append({"role": "user", "text": question})

    stream_state["answer"] = ""
    stream_state["done"] = False
    stream_state["consumed"] = False
    stream_state["generating"] = True

    threading.Thread(target=_generate_worker, args=(question,), daemon=True).start()

    return render_chat(history), history, "", False, "Generating response..."


# -----------------------------
# Poll the in-flight answer and render it as it streams in
# -----------------------------
@callback(
    Output("chat-window", "children", allow_duplicate=True),
    Output("chat-history", "data", allow_duplicate=True),
    Output("stream-interval", "disabled", allow_duplicate=True),
    Output("gen-indicator", "children", allow_duplicate=True),
    Input("stream-interval", "n_intervals"),
    State("chat-history", "data"),
    prevent_initial_call=True,
)
def update_stream(_, history):

    if stream_state["done"]:
        if not stream_state["consumed"]:
            history.append({"role": "assistant", "text": stream_state["answer"]})
            stream_state["consumed"] = True
        return render_chat(history), history, True, ""

    return render_chat(history, stream_state["answer"] or "..."), history, False, "Generating response..."


if __name__ == "__main__":
    app.run(debug=True)
