import logging
import time
import psutil
import threading
import numpy as np
from typing import Dict, Any, Optional, List, Deque, Tuple
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)


class MonitoringManager:
    def __init__(self):
        self._metrics_lock = threading.Lock()

        # 1. Performance Metrics améliorées
        self._performance_metrics: Dict[str, Any] = {
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_profit": Decimal("0"),
            "max_drawdown": Decimal("0"),
            "avg_trade_duration": 0.0,
            "best_trade": Decimal("0"),
            "worst_trade": Decimal("0"),
            "avg_profit_per_trade": Decimal("0"),
            "sharpe_ratio": 0.0,
            "equity_curve": [],
        }

        # 2. System Metrics étendues
        self._system_metrics: Dict[str, Any] = {
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "disk_usage": 0.0,
            "network_latency": 0.0,
            "memory_available": 0,
            "swap_usage": 0.0,
            "network_io": {"bytes_sent": 0, "bytes_recv": 0},
            "process_threads": 0,
            "system_uptime": 0,
            "bot_uptime": time.time(),
        }

        # 3. Trading Metrics en temps réel
        self._realtime_metrics: Dict[str, Any] = {
            "orders_per_minute": 0.0,
            "api_calls_per_minute": 0.0,
            "websocket_reconnects": 0,
            "last_order_latency": 0.0,
            "average_order_latency": 0.0,
            "order_queue_size": 0,
            "last_signal_time": None,
            "signals_per_hour": 0.0,
            "current_position_duration": 0,
            "last_error_time": None,
            "error_count": 0,
        }

        # Historiques pour calculs
        self._latency_history: Deque[float] = deque(maxlen=1000)
        self._profit_history: Deque[Tuple[float, Decimal]] = deque(
            maxlen=1000
        )  # (timestamp, profit)
        self._api_calls_history: Deque[float] = deque(
            maxlen=60
        )  # Pour calculer calls/minute
        self._error_history: Deque[Tuple[float, str]] = deque(
            maxlen=100
        )  # (timestamp, error_message)

        # Démarrer les threads de monitoring
        self._start_system_monitoring()
        self._start_performance_monitoring()

    def _start_system_monitoring(self):
        """Démarre le monitoring système."""

        def monitor_system():
            while True:
                try:
                    with self._metrics_lock:
                        # CPU et Charge système
                        self._system_metrics["cpu_usage"] = psutil.cpu_percent(
                            interval=1
                        )
                        self._system_metrics["process_threads"] = len(
                            psutil.Process().threads()
                        )

                        # Mémoire
                        mem = psutil.virtual_memory()
                        self._system_metrics["memory_usage"] = mem.percent
                        self._system_metrics["memory_available"] = mem.available

                        # Swap
                        swap = psutil.swap_memory()
                        self._system_metrics["swap_usage"] = swap.percent

                        # Disque
                        disk = psutil.disk_usage("/")
                        self._system_metrics["disk_usage"] = disk.percent

                        # Réseau
                        net_io = psutil.net_io_counters()
                        self._system_metrics["network_io"] = {
                            "bytes_sent": net_io.bytes_sent,
                            "bytes_recv": net_io.bytes_recv,
                        }

                        # Uptime
                        self._system_metrics["system_uptime"] = (
                            time.time() - psutil.boot_time()
                        )

                    time.sleep(5)
                except Exception as e:
                    logger.error(f"Erreur monitoring système: {e}")
                    time.sleep(5)

        thread = threading.Thread(target=monitor_system, daemon=True)
        thread.start()

    def _start_performance_monitoring(self):
        """Démarre le monitoring des performances."""

        def monitor_performance():
            while True:
                try:
                    with self._metrics_lock:
                        if self._profit_history:
                            # Calculer Sharpe Ratio
                            returns = [profit for _, profit in self._profit_history]
                            if returns:
                                returns_arr = np.array([float(r) for r in returns])
                                if len(returns_arr) > 1:
                                    self._performance_metrics["sharpe_ratio"] = np.sqrt(
                                        252
                                    ) * (
                                        returns_arr.mean() / returns_arr.std()
                                        if returns_arr.std() != 0
                                        else 0
                                    )

                        # Mettre à jour les statistiques d'ordres par minute
                        now = time.time()
                        recent_calls = [
                            t for t in self._api_calls_history if now - t <= 60
                        ]
                        self._realtime_metrics["orders_per_minute"] = len(recent_calls)

                    time.sleep(60)  # Mise à jour toutes les minutes
                except Exception as e:
                    logger.error(f"Erreur monitoring performance: {e}")
                    time.sleep(60)

        thread = threading.Thread(target=monitor_performance, daemon=True)
        thread.start()

    def update_latency(self, latency_ms: float):
        """Met à jour les métriques de latence."""
        with self._metrics_lock:
            self._latency_history.append(latency_ms)
            self._realtime_metrics["network_latency"] = sum(
                self._latency_history
            ) / len(self._latency_history)

    def record_order_latency(self, latency_ms: float):
        """Enregistre la latence d'un ordre."""
        with self._metrics_lock:
            self._realtime_metrics["last_order_latency"] = latency_ms
            # Mise à jour moyenne mobile
            alpha = 0.1  # Facteur de lissage
            current_avg = self._realtime_metrics["average_order_latency"]
            self._realtime_metrics["average_order_latency"] = (alpha * latency_ms) + (
                (1 - alpha) * current_avg
            )

    def update_performance_metrics(self, new_metrics: Dict[str, Any]):
        """Met à jour les métriques de performance."""
        with self._metrics_lock:
            self._performance_metrics.update(new_metrics)

    def increment_websocket_reconnects(self):
        """Incrémente le compteur de reconnexions websocket."""
        with self._metrics_lock:
            self._realtime_metrics["websocket_reconnects"] += 1

    def record_error(self, error_message: str):
        """Records an error with timestamp for tracking."""
        with self._metrics_lock:
            # Add error to history with current timestamp
            self._error_history.append((time.time(), error_message))
            # Update error metrics
            self._realtime_metrics["error_count"] += 1
            self._realtime_metrics["last_error_time"] = time.time()
            # Maintain max size of error history
            maxlen = self._error_history.maxlen
            if maxlen is not None and len(self._error_history) > maxlen:
                self._error_history.popleft()

            logger.warning(f"Error recorded: {error_message}")

    def get_recent_errors(self, limit: int = 10) -> List[Tuple[float, str]]:
        """Returns the most recent errors with their timestamps."""
        with self._metrics_lock:
            # Return copy of most recent errors up to limit
            recent_errors = list(self._error_history)[-limit:]
            return recent_errors

    def get_error_count(self) -> int:
        """Returns the total number of errors recorded."""
        with self._metrics_lock:
            return self._realtime_metrics["error_count"]

    def get_last_error_time(self) -> Optional[float]:
        """Returns the timestamp of the last recorded error."""
        with self._metrics_lock:
            return self._realtime_metrics.get("last_error_time")

    def reset_error_count(self):
        """Resets the error counter to zero."""
        with self._metrics_lock:
            self._realtime_metrics["error_count"] = 0
            logger.info("Error count reset to 0")

    def get_all_metrics(self) -> Dict[str, Any]:
        """Retourne toutes les métriques actuelles."""
        with self._metrics_lock:
            return {
                "performance": self._performance_metrics.copy(),
                "system": self._system_metrics.copy(),
                "realtime": self._realtime_metrics.copy(),
                "timestamp": datetime.now(timezone.utc).timestamp(),
            }


# Singleton instance
monitoring_manager = MonitoringManager()

__all__ = ["monitoring_manager"]
