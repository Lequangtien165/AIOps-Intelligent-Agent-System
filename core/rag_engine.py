# rag_engine.py
import os
import logging
import re
import redis
from datetime import datetime, timedelta
from typing import Union, Any, Dict, Optional
import chromadb
from chromadb.utils import embedding_functions
from chromadb import Where
import json

logger = logging.getLogger(__name__)


class RAGEngine:
    def __init__(self, db_path="./vector_db"):
        self.client = chromadb.PersistentClient(path=db_path)

        # FIX #7: Khởi tạo embedding_fn bên trong class thay vì global
        # để tránh lỗi import-time khi thiếu dependency
        self._embedding_fn = embedding_functions.DefaultEmbeddingFunction()

        self.collection = self.client.get_or_create_collection(
            name="ops_runbooks",
            embedding_function=self._embedding_fn  # type: ignore
        )
        
        # Initialize caching
        self._init_cache()
        self._ingest_initial_data()

    def _init_cache(self):
        """Initialize Redis cache for query results"""
        try:
            self.redis_host = os.getenv("REDIS_HOST", "localhost")
            self.redis_port = int(os.getenv("REDIS_PORT", "6379"))
            self.redis_db = int(os.getenv("REDIS_DB", "0"))
            self.cache_ttl = int(os.getenv("QUERY_CACHE_TTL", "3600"))
            
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True,
                socket_timeout=5,
            )
            self.redis_client.ping()
            self.cache_enabled = True
            logger.info("✅ RAG Engine caching initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize cache: {e}")
            self.cache_enabled = False
            self.redis_client = None

    def _get_cache_key(self, query: str, query_type: str = "runbook") -> str:
        """Generate cache key for query results"""
        query_hash = hash(query.lower()) % 10000000
        return f"rag:{query_type}:{query_hash}"

    def _ingest_initial_data(self):
        kb_path = os.path.join(os.path.dirname(__file__), "..", "config", "knowledge_base")
        if not os.path.exists(kb_path):
            logger.warning(f"KB path not found: {kb_path}")
            return
        
        batch_ids = []
        batch_docs = []
        batch_meta = []
        batch_size = int(os.getenv("VECTOR_DB_BATCH_SIZE", "100"))
        
        for filename in os.listdir(kb_path):
            if filename.endswith(".md"):
                file_path = os.path.join(kb_path, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                batch_ids.append(filename)
                batch_docs.append(content)
                batch_meta.append({"source": filename})
                
                if len(batch_ids) >= batch_size:
                    self.collection.upsert(
                        ids=batch_ids,
                        documents=batch_docs,
                        metadatas=batch_meta
                    )
                    batch_ids, batch_docs, batch_meta = [], [], []
        
        # Insert remaining
        if batch_ids:
            self.collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_meta
            )
        
        logger.info(f"✅ Đã nạp tri thức từ {kb_path}")

    def save_incident(
        self,
        alert_name: str,
        description: str,
        ai_analysis: str,
        resolution: str,
        outcome: str
    ):
        doc_id = f"incident_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{alert_name}"
        document = (
            f"# Incident: {alert_name}\n"
            f"Mô tả: {description}\n\n"
            f"## AI Phân tích: {ai_analysis}\n\n"
            f"## Hành động đã thực hiện: {resolution}\n\n"
            f"## Kết quả: {outcome}\n"
        )
        self.collection.upsert(
            ids=[doc_id],
            documents=[document],
            metadatas=[{
                "source": "incident_history",
                "alert_name": alert_name,
                "timestamp": datetime.now().isoformat(),
                "outcome": outcome
            }]
        )
        
        # Invalidate cache for this alert
        if self.cache_enabled and self.redis_client:
            try:
                cache_key = self._get_cache_key(description, "runbook")
                self.redis_client.delete(cache_key)
            except Exception as e:
                logger.warning(f"Cache invalidation failed: {e}")
        
        logger.info(f"✅ Đã lưu incident '{alert_name}' vào RAG DB (outcome={outcome})")

    def query_runbook(self, alert_description: str) -> str:
        try:
            # Check cache first
            if self.cache_enabled and self.redis_client:
                try:
                    cache_key = self._get_cache_key(alert_description, "runbook")
                    cached_result = self.redis_client.get(cache_key)
                    if cached_result:
                        logger.info(f"✅ Cache hit for query")
                        return json.loads(cached_result)
                except Exception as e:
                    logger.warning(f"Cache read failed: {e}")
            
            total_count = self.collection.count()
            if total_count == 0:
                return "Kho tri thức đang trống."

            keywords = set(re.findall(r'\w+', alert_description.lower()))

            def hybrid_retrieve(where_clause: Where, n: int = 3) -> str:
                results = None
                try:
                    results = self.collection.query(
                        query_texts=[alert_description],
                        n_results=min(n, total_count),
                        where=where_clause
                    )
                except Exception as e:
                    logger.warning(f"RAG query failed ({e}), retrying with n=1")
                    try:
                        results = self.collection.query(
                            query_texts=[alert_description],
                            n_results=1,
                            where=where_clause
                        )
                    except Exception as e2:
                        logger.error(f"RAG fallback query also failed: {e2}")
                        return "Không tìm thấy thông tin phù hợp."

                if results is None:
                    return "Không tìm thấy thông tin phù hợp."
                
                docs = (results.get("documents") or [[]])[0]
                if not docs:
                    return "Không tìm thấy thông tin phù hợp."

                scored_docs = []
                for doc in docs:
                    score = sum(1 for kw in keywords if kw in doc.lower())
                    scored_docs.append((score, doc))

                scored_docs.sort(key=lambda x: x[0], reverse=True)
                return scored_docs[0][1]

            # Create Where dict đúng chuẩn ChromaDB
            runbook_filter: Where = {"source": {"$ne": "incident_history"}}
            history_filter: Where = {"source": {"$eq": "incident_history"}}

            runbook_text = hybrid_retrieve(runbook_filter)
            history_text = hybrid_retrieve(history_filter)

            result = f"## Quy trình chuẩn:\n{runbook_text}\n\n## Incident tương tự trước đây:\n{history_text}"
            
            # Cache the result
            if self.cache_enabled and self.redis_client:
                try:
                    cache_key = self._get_cache_key(alert_description, "runbook")
                    self.redis_client.setex(
                        cache_key,
                        self.cache_ttl,
                        json.dumps(result)
                    )
                except Exception as e:
                    logger.warning(f"Cache write failed: {e}")
            
            return result

        except Exception as e:
            logger.error(f"RAG Query Error: {e}")
            return "Lỗi khi truy xuất kho tri thức."


_rag_instance = None

def get_rag_instance() -> RAGEngine | None:
    global _rag_instance
    if _rag_instance is None:
        try:
            db_path = os.getenv("VECTOR_DB_PATH", "./vector_db")
            _rag_instance = RAGEngine(db_path=db_path)
            logger.info("✅ RAG Engine initialized successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize RAG Engine: {e}")
            return None
    return _rag_instance