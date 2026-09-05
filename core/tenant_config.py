from pydantic import BaseModel
from typing import List, Dict

class TenantConfig(BaseModel):
    tenant_id: str
    regions: List[str]
    db_adapter_choice: str
    field_masks_per_entity: Dict[str, List[str]]
    stampede_budgets_per_region: Dict[str, int]
