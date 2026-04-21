"""
Celery Autoscaling based on queue length

Monitors Celery queue depths and adjusts worker count dynamically.
Can be run as a standalone process or integrated into deployment.
"""

import logging
import os
import sys
import time
import subprocess
from typing import Dict, List, Optional
from dataclasses import dataclass

import redis
from celery.app.control import Control

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from celery_app import app

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


@dataclass
class AutoscaleConfig:
    """Configuration for autoscaling behavior"""
    min_workers: int = 2
    max_workers: int = 20
    target_queue_depth: int = 10  # Ideal queue depth per worker
    scale_up_threshold: float = 1.5  # Scale up when queue/depth > this
    scale_down_threshold: float = 0.3  # Scale down when queue/depth < this
    scale_up_cooldown: int = 60  # Seconds between scale-up events
    scale_down_cooldown: int = 300  # Seconds between scale-down events
    queues: List[str] = None
    
    def __post_init__(self):
        if self.queues is None:
            self.queues = ["celery", "recon", "scan", "analyze", "report", "repo_scan"]


class CeleryAutoscale:
    """
    Autoscaler for Celery workers based on queue metrics.
    
    Monitors Redis queues and adjusts worker pool size.
    """
    
    def __init__(self, config: Optional[AutoscaleConfig] = None):
        self.config = config or AutoscaleConfig()
        self.redis_client = redis.from_url(REDIS_URL)
        self.control = Control(app)
        self.last_scale_up = 0
        self.last_scale_down = 0
        self.current_workers = self.config.min_workers
    
    def get_queue_depths(self) -> Dict[str, int]:
        """Get current depth of all monitored queues"""
        depths = {}
        for queue in self.config.queues:
            try:
                # Celery uses Redis lists for queues
                length = self.redis_client.llen(queue)
                depths[queue] = length
            except Exception as e:
                logger.warning(f"Failed to get depth for queue {queue}: {e}")
                depths[queue] = 0
        return depths
    
    def get_active_worker_count(self) -> int:
        """Get number of currently active workers"""
        try:
            stats = self.control.inspect().stats()
            if stats:
                return len(stats)
            return self.current_workers
        except Exception as e:
            logger.warning(f"Failed to get worker count: {e}")
            return self.current_workers
    
    def calculate_target_workers(self, queue_depths: Dict[str, int]) -> int:
        """
        Calculate optimal worker count based on queue depths.
        
        Args:
            queue_depths: Dictionary of queue names to depths
            
        Returns:
            Target number of workers
        """
        total_depth = sum(queue_depths.values())
        
        if total_depth == 0:
            return self.config.min_workers
        
        # Calculate workers needed based on target depth per worker
        target = max(
            self.config.min_workers,
            min(
                self.config.max_workers,
                int(total_depth / self.config.target_queue_depth) + 1
            )
        )
        
        return target
    
    def scale_workers(self, target_count: int):
        """
        Scale worker pool to target count.
        
        In production, this would use Kubernetes HPA, ECS, or systemd.
        For now, it logs the recommendation.
        """
        current = self.get_active_worker_count()
        
        if target_count > current:
            # Check cooldown
            if time.time() - self.last_scale_up < self.config.scale_up_cooldown:
                logger.info("Scale up cooldown active, skipping")
                return
            
            logger.info(f"Scaling UP: {current} -> {target_count} workers")
            self._start_workers(target_count - current)
            self.last_scale_up = time.time()
            
        elif target_count < current:
            # Check cooldown
            if time.time() - self.last_scale_down < self.config.scale_down_cooldown:
                logger.info("Scale down cooldown active, skipping")
                return
            
            logger.info(f"Scaling DOWN: {current} -> {target_count} workers")
            self._stop_workers(current - target_count)
            self.last_scale_down = time.time()
        
        self.current_workers = target_count
    
    def _start_workers(self, count: int):
        """Start additional worker processes"""
        for i in range(count):
            try:
                # Spawn new worker process
                cmd = [
                    sys.executable, "-m", "celery",
                    "-A", "celery_app", "worker",
                    "--loglevel=info",
                    "--concurrency=4",
                    "-Q", ",".join(self.config.queues)
                ]
                subprocess.Popen(
                    cmd,
                    cwd=PROJECT_ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"Started worker {i+1}/{count}")
            except Exception as e:
                logger.error(f"Failed to start worker: {e}")
    
    def _stop_workers(self, count: int):
        """Signal workers to stop after current task"""
        try:
            # Use Celery control to gracefully shutdown workers
            self.control.shutdown(destination=[f"celery@{os.uname().nodename}"])
            logger.info(f"Sent shutdown signal to {count} workers")
        except Exception as e:
            logger.error(f"Failed to stop workers: {e}")
    
    def run(self, interval: int = 30):
        """
        Run autoscaling loop.
        
        Args:
            interval: Seconds between checks
        """
        logger.info(
            f"Starting Celery autoscaling loop (min={self.config.min_workers}, "
            f"max={self.config.max_workers}, interval={interval}s)"
        )
        
        while True:
            try:
                depths = self.get_queue_depths()
                target = self.calculate_target_workers(depths)
                
                logger.debug(f"Queue depths: {depths}, target workers: {target}")
                
                self.scale_workers(target)
                
            except Exception as e:
                logger.error(f"Error in autoscaling loop: {e}")
            
            time.sleep(interval)


def main():
    """CLI entry point for autoscaling"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Celery Autoscaling")
    parser.add_argument("--min-workers", type=int, default=2)
    parser.add_argument("--max-workers", type=int, default=20)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--target-depth", type=int, default=10)
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    
    config = AutoscaleConfig(
        min_workers=args.min_workers,
        max_workers=args.max_workers,
        target_queue_depth=args.target_depth
    )
    
    scaler = CeleryAutoscale(config)
    scaler.run(interval=args.interval)


if __name__ == "__main__":
    main()
