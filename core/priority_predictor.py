"""
Priority Predictor
==================
Predicts application priority using heuristic scoring and an optional
lightweight ML model trained on usage history.
"""

import os
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple

from core.config import Config
from core.usage_tracker import UsageTracker
from utils.logger import get_logger

logger = get_logger()


class PriorityLevel(Enum):
    """Priority levels for application scheduling."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PriorityPredictor:
    """Predicts per-app priority from usage history and an optional ML model."""

    def __init__(
        self,
        config: Config = None,
        tracker: UsageTracker = None,
    ):
        self._config = config or Config()
        self._tracker = tracker or UsageTracker(self._config)
        self._model = None
        self._model_trained: bool = False
        self._last_train_time: float = 0.0
        self._cache: Dict[str, PriorityLevel] = {}

    # ── Heuristic scoring ────────────────────────────────────────────────

    def heuristic_score(self, app_stats: dict) -> PriorityLevel:
        """Score an application based on usage statistics.

        Factors:
        - Session count (frequency)
        - Foreground ratio (user engagement)
        - Average CPU/memory (resource demand)
        - Total duration (time invested)
        """
        session_count = app_stats.get("session_count", 0)
        fg_ratio = app_stats.get("foreground_ratio", 0.0)
        avg_cpu = app_stats.get("avg_cpu", 0.0)
        avg_mem = app_stats.get("avg_mem", 0.0)
        total_duration = app_stats.get("total_duration", 0.0)

        score = 0.0

        # Frequency score (0-30)
        score += min(session_count * 2, 30)

        # Foreground engagement (0-30)
        score += fg_ratio * 30

        # Resource demand (0-20)
        resource_score = min((avg_cpu + avg_mem / 100) * 2, 20)
        score += resource_score

        # Duration score (0-20) — log scale
        import math
        if total_duration > 0:
            score += min(math.log(total_duration + 1) * 3, 20)

        # Classify
        if score >= 50:
            return PriorityLevel.HIGH
        elif score >= 25:
            return PriorityLevel.MEDIUM
        else:
            return PriorityLevel.LOW

    # ── ML model ─────────────────────────────────────────────────────────

    def _should_train(self) -> bool:
        """Check if the ML model should be (re)trained."""
        total = self._tracker.get_total_events()
        if total < self._config.min_learning_samples:
            return False

        hours_since = (time.time() - self._last_train_time) / 3600
        if self._model_trained and hours_since < self._config.retrain_interval_hours:
            return False

        return True

    def train_model(self) -> bool:
        """Train a RandomForestClassifier on usage history.

        Returns True if training succeeded.
        """
        try:
            from sklearn.ensemble import RandomForestClassifier
            import joblib
            import numpy as np

            stats = self._tracker.get_all_app_stats()
            if len(stats) < self._config.min_learning_samples:
                logger.debug("Not enough data for ML training")
                return False

            # Build feature matrix
            X = []
            y = []
            for s in stats:
                features = [
                    s.get("session_count", 0),
                    s.get("avg_cpu", 0.0),
                    s.get("avg_mem", 0.0),
                    s.get("avg_gpu", 0.0),
                    s.get("total_duration", 0.0),
                    s.get("foreground_ratio", 0.0),
                ]
                X.append(features)

                # Label from heuristic (used as ground truth for bootstrapping)
                label = self.heuristic_score(s).value
                y.append(label)

            X = np.array(X)
            y = np.array(y)

            # Train
            model = RandomForestClassifier(
                n_estimators=50,
                max_depth=5,
                random_state=42,
            )
            model.fit(X, y)

            # Save model
            model_path = self._config.model_path
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            joblib.dump(model, model_path)

            self._model = model
            self._model_trained = True
            self._last_train_time = time.time()
            logger.info(f"ML priority model trained on {len(X)} apps, saved to {model_path}")
            return True

        except ImportError:
            logger.warning("scikit-learn not available — using heuristic only")
            return False
        except Exception as e:
            logger.error(f"ML training failed: {e}")
            return False

    def load_model(self) -> bool:
        """Load a previously trained model from disk."""
        try:
            import joblib
            model_path = self._config.model_path
            if os.path.exists(model_path):
                self._model = joblib.load(model_path)
                self._model_trained = True
                logger.info(f"Loaded priority model from {model_path}")
                return True
        except Exception as e:
            logger.debug(f"Could not load model: {e}")
        return False

    # ── Prediction ───────────────────────────────────────────────────────

    def predict(self, app_name: str) -> PriorityLevel:
        """Predict the priority level for an application.

        Uses ML model if trained, otherwise falls back to heuristic scoring.
        Results are cached per scan cycle.
        """
        if app_name in self._cache:
            return self._cache[app_name]

        # Try ML prediction first
        if self._model_trained and self._model is not None:
            prediction = self._predict_ml(app_name)
            if prediction is not None:
                self._cache[app_name] = prediction
                return prediction

        # Fallback to heuristic
        history = self._tracker.get_app_history(app_name, limit=50)
        if not history:
            priority = PriorityLevel.LOW
        else:
            # Compute stats from history
            stats = {
                "session_count": len(history),
                "avg_cpu": sum(h["cpu_avg"] for h in history) / len(history),
                "avg_mem": sum(h["mem_avg"] for h in history) / len(history),
                "foreground_ratio": sum(h["was_foreground"] for h in history) / len(history),
                "total_duration": sum(h["duration_seconds"] for h in history),
            }
            priority = self.heuristic_score(stats)

        self._cache[app_name] = priority
        return priority

    def _predict_ml(self, app_name: str) -> Optional[PriorityLevel]:
        """Use the trained ML model for prediction."""
        try:
            import numpy as np

            stats_list = self._tracker.get_app_history(app_name, limit=50)
            if not stats_list:
                return None

            features = np.array([[
                len(stats_list),
                sum(h["cpu_avg"] for h in stats_list) / len(stats_list),
                sum(h["mem_avg"] for h in stats_list) / len(stats_list),
                sum(h.get("gpu_avg", 0) for h in stats_list) / len(stats_list),
                sum(h["duration_seconds"] for h in stats_list),
                sum(h["was_foreground"] for h in stats_list) / len(stats_list),
            ]])

            prediction = self._model.predict(features)[0]
            return PriorityLevel(prediction)
        except Exception:
            return None

    def clear_cache(self) -> None:
        """Clear the prediction cache (call at the start of each scan cycle)."""
        self._cache.clear()

    def maybe_retrain(self) -> None:
        """Check if retraining is needed and train if so."""
        if self._should_train():
            self.train_model()

    def get_all_predictions(self) -> Dict[str, str]:
        """Return the current cache of predictions."""
        return {k: v.value for k, v in self._cache.items()}
