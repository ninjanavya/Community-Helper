from pydantic import BaseModel, Field
from typing import List

class IncidentIntelligenceReport(BaseModel):
    incident_type: str = Field(description="The classified type of the civic incident.")
    severity: str = Field(description="The severity level of the incident (e.g., Low, Medium, High).")
    priority: str = Field(description="The action priority level (e.g., Low, Moderate, High, Critical).")
    confidence: float = Field(description="Percentage score of the model's confidence in the classification.")
    risk_level: str = Field(description="Estimated risk level posed to the community (e.g., Low, Medium, High).")
    summary: str = Field(description="A concise summary explaining the incident details.")
    department: str = Field(description="The municipal department suggested to handle this incident.")
    estimated_response: str = Field(description="Estimated time frame for response/resolution.")
    suggested_actions: List[str] = Field(description="List of suggested actions/steps to take for resolution.")
    reasoning: List[str] = Field(description="Detailed reasons explaining why the AI made these recommendations and assigned this priority.")

class ImageValidationResponse(BaseModel):
    is_valid: bool = Field(description="True if the image contains public infrastructure/location, an identifiable civic issue, matches the description, and has enough confidence.")
    reason: str = Field(description="Detailed reason explaining why the validation failed or succeeded.")
    confidence: float = Field(description="Confidence percentage (0-100) of this validation decision.")
    recommendation: str = Field(description="Helpful instructions advising the citizen on what type of image to upload if validation fails.")
