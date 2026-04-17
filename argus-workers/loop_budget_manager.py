"""
Loop Budget Manager - Prevents infinite scanning loops
"""
from typing import Dict, Tuple, Optional


class LoopBudgetManager:
    """
    Enforces maximum cycles, depth, and cost limits to prevent infinite loops
    """
    
    def __init__(self, engagement_id: str, config: Optional[Dict] = None):
        """
        Initialize Loop Budget Manager
        
        Args:
            engagement_id: Engagement ID
            config: Configuration dictionary with max_cycles, max_depth, max_cost
        """
        self.engagement_id = engagement_id
        
        # Set defaults
        config = config or {}
        self.max_cycles = config.get("max_cycles", 5)
        self.max_depth = config.get("max_depth", 3)
        self.cost_limit = config.get("max_cost", 0.50)
        
        # Initialize current values
        self.current_cycles = 0
        self.current_depth = 0
        self.current_cost = 0.0
    
    def can_continue(self, action: Dict) -> Tuple[bool, str]:
        """
        Check if action is within budget
        
        Args:
            action: Action dictionary with type and estimated cost
            
        Returns:
            Tuple of (can_continue, reason)
        """
        action_type = action.get("type")
        estimated_cost = action.get("estimated_cost", 0.05)
        
        # Check cycles for recon_expand actions
        if action_type == "recon_expand":
            if self.current_cycles >= self.max_cycles:
                return False, "cycles_exceeded"
        
        # Check depth for deep_scan actions
        if action_type == "deep_scan":
            if self.current_depth >= self.max_depth:
                return False, "depth_exceeded"
        
        # Check cost limit
        if self.current_cost + estimated_cost > self.cost_limit:
            return False, "cost_limit_exceeded"
        
        return True, "within_budget"
    
    def consume(self, action: Dict):
        """
        Consume budget for executed action
        
        Args:
            action: Action dictionary with type and actual cost
        """
        action_type = action.get("type")
        actual_cost = action.get("actual_cost", 0.05)
        
        # Increment appropriate counter
        if action_type == "recon_expand":
            self.current_cycles += 1
        elif action_type == "deep_scan":
            self.current_depth += 1
        
        # Add to current cost
        self.current_cost += actual_cost
    
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
            "cost": {
                "current": self.current_cost,
                "limit": self.cost_limit,
                "remaining": self.cost_limit - self.current_cost,
            },
        }
    
    def reset(self):
        """Reset current values to zero"""
        self.current_cycles = 0
        self.current_depth = 0
        self.current_cost = 0.0
    
    def load_from_db(self, db_data: Dict):
        """
        Load current state from database
        
        Args:
            db_data: Database record with current values
        """
        self.current_cycles = db_data.get("current_cycles", 0)
        self.current_depth = db_data.get("current_depth", 0)
        self.current_cost = db_data.get("current_cost", 0.0)
    
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
            "max_cost": self.cost_limit,
            "current_cycles": self.current_cycles,
            "current_depth": self.current_depth,
            "current_cost": self.current_cost,
        }
