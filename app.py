from dash import Dash, html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
from main import YTRag

rag = YTRag()

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP]
)

# -----------------------------
# Get the response to the query from the RAG model.
# -----------------------------
def ask_question(question):
    return rag.get_response(question)


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

    return html.Div(
        text,
        style={
            "backgroundColor": "#eeeeee",
            "padding": "12px",
            "borderRadius": "12px",
            "margin": "8px",
            "maxWidth": "70%",
        },
    )


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
        html.Br(),
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
# Chat callback
# -----------------------------
@callback(
    Output("chat-window", "children"),
    Output("chat-history", "data"),
    Output("question", "value"),
    Input("send-btn", "n_clicks"),
    State("question", "value"),
    State("chat-history", "data"),
    prevent_initial_call=True,
)
def send_message(_, question, history):

    if not question:
        raise PreventUpdate

    history.append(
        {
            "role": "user",
            "text": question,
        }
    )

    answer = ask_question(question)

    history.append(
        {
            "role": "assistant",
            "text": answer,
        }
    )

    chat = []

    for msg in history:
        chat.append(
            create_message(
                msg["role"],
                msg["text"],
            )
        )

    return chat, history, ""


if __name__ == "__main__":
    app.run(debug=True)