"""
Health monitoring for Argus workers

Provides health check and statistics for the Celery worker system
"""

import logging
import os
import psutil
from datetime import datetime
from celery import Celery
from celery_app import app

logger = logging.getLogger(__name__)


def get_worker_health():
    """Get worker health status"""
    inspector = app.control.inspect()
    
    try:
        # Get active tasks
        active = inspector.active()
        stats = inspector.stats()
        registered = inspector.registered()
        
        return {
            "status": "healthy",
            "active_tasks": active or {},
            "stats": stats or {},
            "registered_tasks": registered or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Worker health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


def get_worker_stats():
    """Get worker statistics"""
    try:
        inspector = app.control.inspect()
        
        # Get all stats
        stats = inspector.stats()
        
        # Get active
        active = inspector.active()
        
        # Get reserved (queued)
        reserved = inspector.reserved()
        
        # Get process info
        process_info = {
            "pid": os.getpid(),
            "cpu_percent": psutil.cpu_percent(),
            "memory_mb": psutil.Process().memory_info().rss / 1024 / 1024,
            "num_threads": psutil.Process().num_threads(),
        }
        
        return {
            "workers": stats or {},
            "active_tasks": active or {},
            "queued_tasks": reserved or {},
            "process": process_info,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Worker stats failed: {e}")
        return {"error": str(e)}


def get_queue_status():
    """Get queue status"""
    try:
        with app.connection_or_acquire() as conn:
            # Get queue lengths
            queue_names = ["recon", "scan", "analyze", "report", "repo_scan"]
            queue_info = {}
            
            for queue_name in queue_names:
                try:
                    queue = app.Queue(queue_name, connection=conn)
                    queue_info[queue_name] = queue.size()
                except Exception:
                    queue_info[queue_name] = 0
            
            return {"queues": queue_info}
    except Exception as e:
        logger.error(f"Queue status failed: {e}")
        return {"error": str(e)}


def check_worker_availability():
    """Check if workers are available"""
    inspector = app.control.inspect()
    
    try:
        stats = inspector.stats()
        if not stats:
            return {"available": False, "workers": 0}
        
        return {
            "available": True,
            "workers": len(stats),
            "worker_names": list(stats.keys()),
        }
    except Exception:
        return {"available": False, "workers": 0}