"""
Loop Budget Manager - Prevents infinite scanning loops
"""
from typing import Dict, Tuple, Optional


class LoopBudgetManager:
    """
    Enforces maximum cycles and depth limits to prevent infinite loops
    """
    
    def __init__(self, engagement_id: str, config: Optional[Dict] = None):
        """
        Initialize Loop Budget Manager
        
        Args:
            engagement_id: Engagement ID
            config: Configuration dictionary with max_cycles, max_depth
        """
        self.engagement_id = engagement_id
        
        # Set defaults
        config = config or {}
        self.max_cycles = config.get("max_cycles", 5)
        self.max_depth = config.get("max_depth", 3)
        
        # Initialize current values
        self.current_cycles = 0
        self.current_depth = 0
    
    def can_continue(self, action: Dict) -> Tuple[bool, str]:
        """
        Check if action is within budget
        
        Args:
            action: Action dictionary with type
            
        Returns:
            Tuple of (can_continue, reason)
        """
        action_type = action.get("type")
        
        # Check cycles for recon_expand actions
        if action_type == "recon_expand":
            if self.current_cycles >= self.max_cycles:
                return False, "cycles_exceeded"
        
        # Check depth for deep_scan actions
        if action_type == "deep_scan":
            if self.current_depth >= self.max_depth:
                return False, "depth_exceeded"
        
        return True, "within_budget"
    
    def consume(self, action: Dict):
        """
        Consume budget for executed action
        
        Args:
            action: Action dictionary with type
        """
        action_type = action.get("type")
        
        # Increment appropriate counter
        if action_type == "recon_expand":
            self.current_cycles += 1
        elif action_type == "deep_scan":
            self.current_depth += 1
    
    def get_status(self) -> Dict:
        """
        Get current budget status
        
        Returns:
            Dictionary with current vs. maximum values
        """
        return {
            "engagement_id": self.engagement_id,
            "cycles": {
                "current": self.current_cycles,
                "max": self.max_cycles,
                "remaining": self.max_cycles - self.current_cycles,
            },
            "depth": {
                "current": self.current_depth,
                "max": self.max_depth,
                "remaining": self.max_depth - self.current_depth,
            },
        }
    
    def reset(self):
        """Reset current values to zero"""
        self.current_cycles = 0
        self.current_depth = 0
    
    def load_from_db(self, db_data: Dict):
        """
        Load current state from database
        
        Args:
            db_data: Database record with current values
        """
        self.current_cycles = db_data.get("current_cycles", 0)
        self.current_depth = db_data.get("current_depth", 0)
    
    def to_dict(self) -> Dict:
        """
        Convert to dictionary for database storage
        
        Returns:
            Dictionary with all budget values
        """
        return {
            "engagement_id": self.engagement_id,
            "max_cycles": self.max_cycles,
            "max_depth": self.max_depth,
            "current_cycles": self.current_cycles,
            "current_depth": self.current_depth,
        }
