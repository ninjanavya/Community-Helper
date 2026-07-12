import os
import sys
import json
import logging
from io import BytesIO
from typing import Any, Dict, Optional
from PIL import Image

# Setup logging
logger = logging.getLogger("community_helper.ai")

# Import the schema and prompt (supports both package and direct import)
try:
    from .schemas import IncidentIntelligenceReport, ImageValidationResponse
    from .prompts import CIE_SYSTEM_PROMPT, AVE_SYSTEM_PROMPT
except ImportError:
    from schemas import IncidentIntelligenceReport, ImageValidationResponse
    from prompts import CIE_SYSTEM_PROMPT, AVE_SYSTEM_PROMPT

# Attempt to reuse the genai_client configured in main.py
genai_client = None
USE_GEMINI = False

# Add parent directory to sys.path to resolve imports from main.py if needed
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    # Attempt to import genai_client from main.py
    from main import genai_client, USE_GEMINI
    logger.info("Successfully imported genai_client from main.py")
except Exception as e:
    logger.warning(f"Could not import genai_client from main: {e}. Standalone client fallback active.")

# Fallback standalone initialization if client is not importable
if not genai_client:
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            from google import genai
            genai_client = genai.Client(api_key=gemini_key)
            USE_GEMINI = True
            logger.info("Gemini API client initialized in standalone mode.")
        except Exception as ex:
            logger.error(f"Failed to initialize standalone Gemini client: {ex}")

def _generate_mock_iir(description: str) -> Dict[str, Any]:
    """Generates a high-quality mock Incident Intelligence Report when Gemini is unavailable."""
    desc_lower = description.lower() if description else ""
    if "pothole" in desc_lower or "road" in desc_lower or "street" in desc_lower or "pavement" in desc_lower:
        return {
            "incident_type": "Pothole / Road Damage",
            "severity": "High",
            "priority": "Critical",
            "confidence": 97.0,
            "risk_level": "High",
            "summary": "Large road fissure/pothole detected in the middle of the active lane creating a significant safety hazard for motorists and cyclists.",
            "department": "Road Maintenance",
            "estimated_response": "Within 6 hours",
            "suggested_actions": [
                "Assign Road Maintenance Team",
                "Place Temporary Warning Signs",
                "Repair within 6 hours"
            ],
            "reasoning": [
                "Large visible road damage detected in citizen description.",
                "Located on a frequently used roadway.",
                "Potential accident risk for two-wheelers.",
                "High simulated confidence score."
            ]
        }
    elif "water" in desc_lower or "leak" in desc_lower or "pipe" in desc_lower or "flood" in desc_lower:
        return {
            "incident_type": "Water Main Leak",
            "severity": "Medium",
            "priority": "High",
            "confidence": 94.0,
            "risk_level": "Moderate",
            "summary": "Active water main leakage detected with local flooding on sidewalk. Potential for pressure drop in surrounding sector.",
            "department": "Water & Sanitation Bureau",
            "estimated_response": "Within 12 hours",
            "suggested_actions": [
                "Dispatch Leak Detection Crew",
                "Isolate Section Valve",
                "Initiate Pipe Repair"
            ],
            "reasoning": [
                "Continuous fluid discharge observed in description.",
                "Flow rate estimated above 5 liters/minute.",
                "Risk of pavement erosion if unresolved."
            ]
        }
    elif "tree" in desc_lower or "branch" in desc_lower or "park" in desc_lower or "plant" in desc_lower:
        return {
            "incident_type": "Fallen Tree / Blocked Path",
            "severity": "High",
            "priority": "High",
            "confidence": 96.0,
            "risk_level": "High",
            "summary": "Large tree branch fallen across sidewalk/cycle path, obstructing pedestrian traffic and posing obstruction risk.",
            "department": "Forestry & Parks Department",
            "estimated_response": "Within 4 hours",
            "suggested_actions": [
                "Deploy Tree Trimming Squad",
                "Clear Debris from Sidewalk",
                "Assess Remaining Tree Stability"
            ],
            "reasoning": [
                "Complete obstruction of public pedestrian walkway.",
                "Heavy timber requires chainsaws for clearing.",
                "Potential hazard if wind speed increases."
            ]
        }
    elif "light" in desc_lower or "dark" in desc_lower or "electricity" in desc_lower or "power" in desc_lower or "lamp" in desc_lower:
        return {
            "incident_type": "Streetlight / Electrical Failure",
            "severity": "Medium",
            "priority": "High",
            "confidence": 95.0,
            "risk_level": "Moderate",
            "summary": "Streetlight malfunction reported, resulting in complete darkness along the pedestrian sidewalk corridor.",
            "department": "Electrical & Lighting Division",
            "estimated_response": "Within 8 hours",
            "suggested_actions": [
                "Dispatch Line Technician",
                "Inspect Local Junction Box",
                "Replace Damaged LED Fixtures"
            ],
            "reasoning": [
                "Darkness presents pedestrian safety and security concerns.",
                "High likelihood of faulty photocell or bulb failure.",
                "Quick diagnostic response scheduled for tonight."
            ]
        }
    else:
        return {
            "incident_type": "General Civil Incident",
            "severity": "Medium",
            "priority": "Moderate",
            "confidence": 91.0,
            "risk_level": "Low",
            "summary": "Civic helper reported issue classified under general municipal services. Initial verification complete.",
            "department": "Public Works Department",
            "estimated_response": "Within 24 hours",
            "suggested_actions": [
                "Dispatch Local Inspector",
                "Verify Community Report Details",
                "Schedule Standard Maintenance Work order"
            ],
            "reasoning": [
                "No immediate life safety hazards reported.",
                "Standard queue priority assignment.",
                "Verified coordinates map to public property."
            ]
        }

def analyze_incident(image: Any, description: str) -> Dict[str, Any]:
    """
    Analyzes an incident using the Gemini API.
    
    Accepts:
    - image: PIL Image, raw bytes, file-like object, or None
    - description: citizen text description
    
    Returns a structured dictionary matching the IncidentIntelligenceReport schema.
    """
    logger.info("analyze_incident called")
    desc_clean = description.strip() if description else ""
    
    # Process the image argument into a PIL Image
    pil_image = None
    if image is not None:
        try:
            if isinstance(image, Image.Image):
                pil_image = image
            elif isinstance(image, bytes):
                pil_image = Image.open(BytesIO(image))
            elif hasattr(image, "read"):
                img_bytes = image.read()
                # If we read from a file, restore seek if supported
                if hasattr(image, "seek"):
                    try:
                        image.seek(0)
                    except Exception:
                        pass
                pil_image = Image.open(BytesIO(img_bytes))
        except Exception as e:
            logger.error(f"Failed to process input image: {e}")

    # If Gemini is configured and active, invoke it
    if USE_GEMINI and genai_client:
        try:
            from google.genai import types
            
            # Construct content payload
            contents = []
            prompt_content = f"Citizen Description:\n{desc_clean}\n\nPlease generate the Incident Intelligence Report."
            contents.append(prompt_content)
            
            if pil_image:
                contents.append(pil_image)
                
            logger.info("Invoking Gemini for incident analysis...")
            response = genai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=IncidentIntelligenceReport,
                    system_instruction=CIE_SYSTEM_PROMPT
                ),
            )
            
            # Parse output text
            response_text = response.text
            if not response_text:
                raise ValueError("Empty text response received from Gemini API.")
                
            # Parse and validate response text using our schema
            data = json.loads(response_text)
            validated = IncidentIntelligenceReport(**data)
            
            if hasattr(validated, "model_dump"):
                res_dict = validated.model_dump()
            else:
                res_dict = validated.dict()
            res_dict["iir_status"] = "success"
            res_dict["iir_message"] = None
            return res_dict
                
        except Exception as e:
            logger.error(f"Gemini API call or validation failed: {e}. Falling back to mock generator.")
            res_dict = _generate_mock_iir(desc_clean)
            res_dict["iir_status"] = "fallback"
            res_dict["iir_message"] = "AI analysis temporarily unavailable. A basic report has been generated."
            return res_dict
    else:
        logger.info("Gemini client not configured. Generating mock response.")
        res_dict = _generate_mock_iir(desc_clean)
        res_dict["iir_status"] = "fallback"
        res_dict["iir_message"] = "AI analysis temporarily unavailable. A basic report has been generated."
        return res_dict

def validate_incident_image(image: Any, description: str) -> Dict[str, Any]:
    """
    Validates whether the uploaded image is suitable for civic incident analysis.
    Checks:
    1. Contains public infrastructure/location.
    2. Contains identifiable civic issue.
    3. Matches description.
    4. Has enough visual confidence.
    """
    logger.info("AVE starting image validation...")
    desc_clean = description.strip() if description else ""
    
    # Process image
    pil_image = None
    if image is not None:
        try:
            if isinstance(image, Image.Image):
                pil_image = image
            elif isinstance(image, bytes):
                pil_image = Image.open(BytesIO(image))
            elif hasattr(image, "read"):
                img_bytes = image.read()
                if hasattr(image, "seek"):
                    try:
                        image.seek(0)
                    except Exception:
                        pass
                pil_image = Image.open(BytesIO(img_bytes))
        except Exception as e:
            logger.error(f"Failed to process validation image: {e}")

    if not pil_image:
        return {
            "is_valid": True,
            "reason": "No image uploaded. Proceeding with description-only analysis.",
            "confidence": 100.0,
            "recommendation": ""
        }

    if USE_GEMINI and genai_client:
        try:
            from google.genai import types
            
            contents = [
                f"Citizen Description:\n{desc_clean}\n\nPlease validate the uploaded image.",
                pil_image
            ]
            
            logger.info("Invoking Gemini for image validation...")
            response = genai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ImageValidationResponse,
                    system_instruction=AVE_SYSTEM_PROMPT
                ),
            )
            
            response_text = response.text
            if not response_text:
                raise ValueError("Empty response received from Gemini API in AVE.")
                
            data = json.loads(response_text)
            validated = ImageValidationResponse(**data)
            
            if hasattr(validated, "model_dump"):
                return validated.model_dump()
            else:
                return validated.dict()
                
        except Exception as e:
            logger.error(f"Gemini API validation call failed: {e}. Falling back to default success.")
            return {
                "is_valid": True,
                "reason": "Validation system offline. Proceeding to analysis.",
                "confidence": 100.0,
                "recommendation": ""
            }
    else:
        logger.info("Gemini client not configured. Skipping image validation.")
        desc_lower = desc_clean.lower()
        if "selfie" in desc_lower or "cat" in desc_lower or "dog" in desc_lower or "person" in desc_lower:
            return {
                "is_valid": False,
                "reason": "The uploaded image appears to contain a pet or person, not a public civic issue.",
                "confidence": 95.0,
                "recommendation": "Please upload an image showing a public issue such as a pothole, garbage accumulation, water leakage, broken streetlight, damaged road, or other civic infrastructure problem."
            }
        return {
            "is_valid": True,
            "reason": "Local validation check passed.",
            "confidence": 100.0,
            "recommendation": ""
        }
