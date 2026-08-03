from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from dotenv import load_dotenv

load_dotenv()

class YTRag():

    def __init__(self):
        self.vector_store = None
        self.retriever = None
        self.vid_id = None
        self.llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview")

    def url_parser(self, url:str) -> str:
        video_id = parse_qs(urlparse(url).query)["v"][0]
        self.vid_id = video_id
        return video_id

    def get_transcript(self,url:str):

        vid_id = self.url_parser(url)
        ytt = YouTubeTranscriptApi()
        script = ytt.fetch(vid_id, languages=['en'])

        combined_transcript = ""
        for sentences in script:
            combined_transcript += (sentences.text + " ")

        return combined_transcript, vid_id

    def vectorize_transcript(self,transcript: str, video_id:str):

        # convert string to Document obejct
        doc = Document(
            page_content=transcript,
            metadata={
                "video_id": video_id,
            }
        )

        # Text splitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size = 1000,
            chunk_overlap = 100
        )

        docs = splitter.split_documents([doc])

        # generate embeddings
        embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-2-preview")
        self.vector_store = FAISS.from_documents(docs,embeddings)
        self.retriever = self.vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": 5,
                "fetch_k": 20
            }
        )  

    def process_video(self, url:str):
        combined_transcript, vid_id = self.get_transcript(url)
        self.vectorize_transcript(combined_transcript, vid_id)

    def fetch_valid_chunks(self, query:str):

        valid_chunks = self.retriever.invoke(query)

        valid_chunks_list = [
            f"{i+1}. {chunk.page_content}"
            for i, chunk in enumerate(valid_chunks)
        ]

        return valid_chunks_list


    def get_response(self, query:str):

        valid_chunks_list = self.fetch_valid_chunks(query)

        prompt = PromptTemplate(
            template= "You are a helpful assistant. Answer the following query in a concide manner using the context available. In case of missing information, dont assume information that is not given in the context. Also take care of proper formatting. Query: {query}. \n Context: {valid_chunks_list}",
            input_variables=["query", "valid_chunks_list"]
        )

        final_prompt = prompt.invoke({"query":query, "valid_chunks_list":valid_chunks_list})
        res = self.llm.invoke(final_prompt)
        return res.content[0]["text"]











    
