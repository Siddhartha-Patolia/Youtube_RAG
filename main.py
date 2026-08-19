import os
from supadata import Supadata
from urllib.parse import urlparse, parse_qs
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache
from dotenv import load_dotenv

load_dotenv()
set_llm_cache(InMemoryCache())

INDEX_DIR = "faiss_indexes"

class YTRag():

    def __init__(self):
        self.vector_store = None
        self.retriever = None
        self.vid_id = None
        self.vector_store_cache = {}
        self.embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-2-preview")
        self.supadata = Supadata(api_key=os.getenv("SUPADATA_API_KEY"))
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-3-flash-preview",
            temperature=0,
            max_output_tokens=512,
            thinking_budget=0,
        )

    def url_parser(self, url:str) -> str:
        video_id = parse_qs(urlparse(url).query)["v"][0]
        self.vid_id = video_id
        return video_id

    def get_transcript(self,url:str):

        vid_id = self.url_parser(url)
        transcript = self.supadata.transcript(
            url=url,
            lang="en",
            text=True,
            mode="auto",
        )

        return transcript.content, vid_id

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
        self.vector_store = FAISS.from_documents(docs, self.embeddings)
        self._set_retriever()
        self.vector_store.save_local(os.path.join(INDEX_DIR, video_id))
        self.vector_store_cache[video_id] = self.vector_store

    def _set_retriever(self):
        self.retriever = self.vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": 5,
                "fetch_k": 10
            }
        )

    def process_video(self, url:str):
        video_id = self.url_parser(url)

        if video_id in self.vector_store_cache:
            self.vector_store = self.vector_store_cache[video_id]
            self._set_retriever()
            return

        index_path = os.path.join(INDEX_DIR, video_id)
        if os.path.isdir(index_path):
            self.vector_store = FAISS.load_local(
                index_path, self.embeddings, allow_dangerous_deserialization=True
            )
            self.vector_store_cache[video_id] = self.vector_store
            self._set_retriever()
            return

        combined_transcript, vid_id = self.get_transcript(url)
        self.vectorize_transcript(combined_transcript, vid_id)

    def fetch_valid_chunks(self, query:str):

        valid_chunks = self.retriever.invoke(query)

        valid_chunks_list = [
            f"{i+1}. {chunk.page_content}"
            for i, chunk in enumerate(valid_chunks)
        ]

        return valid_chunks_list

    def _retriever_for(self, video_id:str):
        vector_store = self.vector_store_cache.get(video_id)
        if vector_store is None:
            raise ValueError(f"video_id '{video_id}' has not been indexed yet")
        return vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 5, "fetch_k": 10}
        )

    def fetch_valid_chunks_for(self, video_id:str, query:str):
        retriever = self._retriever_for(video_id)
        valid_chunks = retriever.invoke(query)
        return [
            f"{i+1}. {chunk.page_content}"
            for i, chunk in enumerate(valid_chunks)
        ]

    def _build_prompt(self, query:str, valid_chunks_list):
        prompt = PromptTemplate(
            template= "You are a helpful assistant. Answer the following query in a concide manner using the context available. In case of missing information, dont assume information that is not given in the context. Also take care of proper formatting. Query: {query}. \n Context: {valid_chunks_list}",
            input_variables=["query", "valid_chunks_list"]
        )
        return prompt.invoke({"query":query, "valid_chunks_list":valid_chunks_list})

    def get_response(self, query:str):

        valid_chunks_list = self.fetch_valid_chunks(query)
        final_prompt = self._build_prompt(query, valid_chunks_list)
        res = self.llm.invoke(final_prompt)
        return res.content[0]["text"]

    def get_response_stream(self, query:str):

        valid_chunks_list = self.fetch_valid_chunks(query)
        final_prompt = self._build_prompt(query, valid_chunks_list)

        yield from self._stream_llm(final_prompt)

    def _stream_llm(self, final_prompt):
        accumulated = ""
        for chunk in self.llm.stream(final_prompt):
            content = chunk.content
            if isinstance(content, str):
                text = content
            elif content and isinstance(content[0], dict):
                text = content[0].get("text", "")
            else:
                text = ""
            if text:
                accumulated += text
                yield accumulated

    def get_response_for(self, video_id:str, query:str):
        valid_chunks_list = self.fetch_valid_chunks_for(video_id, query)
        final_prompt = self._build_prompt(query, valid_chunks_list)
        res = self.llm.invoke(final_prompt)
        return res.content[0]["text"]

    def get_response_stream_for(self, video_id:str, query:str):
        valid_chunks_list = self.fetch_valid_chunks_for(video_id, query)
        final_prompt = self._build_prompt(query, valid_chunks_list)
        yield from self._stream_llm(final_prompt)
