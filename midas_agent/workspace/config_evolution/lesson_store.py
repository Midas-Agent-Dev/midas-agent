"""ExpeL-style lesson store — persists failure lessons with embedding-based retrieval.

Stores concrete failure analyses as-is (no generalization). At merge time,
retrieves similar lessons by issue embedding and injects them into step prompts.
Importance voting prunes unhelpful lessons over time.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class Lesson:
    lesson_id: str
    issue_id: str
    issue_summary: str
    step_id: str
    mistake: str
    lesson: str
    patch: str
    importance: int = 2
    embedding: list[float] = field(default_factory=list)


class LessonStore:
    """Persistent lesson store with embedding-based retrieval and importance voting."""

    def __init__(self, store_path: str, top_k: int = 3) -> None:
        self._store_path = store_path
        self._top_k = top_k
        self._lessons: list[Lesson] = []
        self._embedder: Callable | None = None
        self._embedder_initialized = False

        if os.path.isfile(store_path):
            self.load()

    def __len__(self) -> int:
        return len(self._lessons)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _get_embedder(self) -> Callable:
        """Lazy-init the embedding function."""
        if self._embedder is not None:
            return self._embedder

        self._embedder_initialized = True

        # Try sentence-transformers first
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-mpnet-base-v2")
            self._embedder = lambda text: model.encode(text, show_progress_bar=False).tolist()
            logger.info("LessonStore: using sentence-transformers embedder")
            return self._embedder
        except ImportError:
            pass

        # Fallback: TF-IDF with sklearn
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._tfidf = TfidfVectorizer(max_features=768)
            self._tfidf_fitted = False

            def tfidf_embed(text: str) -> list[float]:
                corpus = [l.issue_summary for l in self._lessons] + [text]
                matrix = self._tfidf.fit_transform(corpus)
                return matrix[-1].toarray()[0].tolist()

            self._embedder = tfidf_embed
            logger.info("LessonStore: using TF-IDF fallback embedder")
            return self._embedder
        except ImportError:
            pass

        # Last resort: bag of words
        def bow_embed(text: str) -> list[float]:
            words = set(text.lower().split())
            # Create a simple hash-based vector
            vec = [0.0] * 256
            for w in words:
                idx = hash(w) % 256
                vec[idx] += 1.0
            # Normalize
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                vec = [v / norm for v in vec]
            return vec

        self._embedder = bow_embed
        logger.info("LessonStore: using bag-of-words fallback embedder")
        return self._embedder

    def _embed(self, text: str) -> list[float]:
        embedder = self._get_embedder()
        return embedder(text)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def add_lesson(
        self,
        issue_id: str,
        issue_summary: str,
        step_id: str,
        mistake: str,
        lesson: str,
        patch: str,
    ) -> str:
        """Add a lesson from a failure analysis. Returns lesson_id."""
        lesson_id = uuid.uuid4().hex[:12]
        embedding = self._embed(issue_summary)

        new_lesson = Lesson(
            lesson_id=lesson_id,
            issue_id=issue_id,
            issue_summary=issue_summary[:500],
            step_id=step_id,
            mistake=mistake,
            lesson=lesson,
            patch=patch[:2000],
            importance=2,
            embedding=embedding,
        )
        self._lessons.append(new_lesson)
        self.save()

        logger.info(
            "LessonStore: added lesson %s (importance=%d, total=%d)",
            lesson_id, new_lesson.importance, len(self._lessons),
        )
        return lesson_id

    def retrieve(self, query_text: str, k: int | None = None) -> list[Lesson]:
        """Retrieve top-k lessons most similar to query_text.

        Only returns lessons with importance > 0.
        """
        k = k or self._top_k
        if not self._lessons:
            return []

        # Filter to positive-importance lessons
        active = [l for l in self._lessons if l.importance > 0]
        if not active:
            return []

        query_emb = self._embed(query_text)

        # Score by cosine similarity
        scored = []
        for lesson in active:
            if not lesson.embedding:
                lesson.embedding = self._embed(lesson.issue_summary)
            sim = self._cosine_similarity(query_emb, lesson.embedding)
            scored.append((sim, lesson))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [lesson for _, lesson in scored[:k]]

        if results:
            logger.info(
                "LessonStore: retrieved %d lessons (top sim=%.3f)",
                len(results), scored[0][0] if scored else 0,
            )
        return results

    def vote(self, lesson_ids: list[str], upvote: bool) -> None:
        """Upvote or downvote lessons. Prune at importance <= -4."""
        if not lesson_ids:
            return

        delta = 1 if upvote else -1
        pruned = []

        for lesson in self._lessons:
            if lesson.lesson_id in lesson_ids:
                lesson.importance += delta
                logger.info(
                    "LessonStore: %s lesson %s (importance=%d)",
                    "upvoted" if upvote else "downvoted",
                    lesson.lesson_id, lesson.importance,
                )
                if lesson.importance <= -4:
                    pruned.append(lesson.lesson_id)

        if pruned:
            self._lessons = [l for l in self._lessons if l.lesson_id not in pruned]
            logger.info("LessonStore: pruned %d lessons (importance <= -4)", len(pruned))

        self.save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Write all lessons to disk as JSON."""
        os.makedirs(os.path.dirname(self._store_path), exist_ok=True)
        data = [asdict(l) for l in self._lessons]
        tmp = self._store_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._store_path)

    def load(self) -> None:
        """Load lessons from disk."""
        try:
            with open(self._store_path) as f:
                data = json.load(f)
            self._lessons = [
                Lesson(**{k: v for k, v in item.items() if k in Lesson.__dataclass_fields__})
                for item in data
            ]
            logger.info("LessonStore: loaded %d lessons from %s", len(self._lessons), self._store_path)
        except Exception as e:
            logger.warning("LessonStore: failed to load from %s: %s", self._store_path, e)
            self._lessons = []
