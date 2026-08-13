from pydantic import BaseModel
from typing import List


class PlannerDecision(BaseModel):
    next_node: str