from firecrawl import Firecrawl
from pydantic import BaseModel, Field
from typing import List, Optional

# Initialize the Firecrawl client
app = Firecrawl(api_key=ENTER_KEY_HERE)

# 1. Define your Structured Schema
class NonprofitIntel(BaseModel):
    org_mission: str = Field(description="The core mission statement of the nonprofit.")
    current_payment_platform: str = Field(description="The payment processor found (e.g., GiveButter, PayPal, Stripe, Zelle).")
    donation_url: Optional[str] = Field(description="The direct link to the donation page.")
    detected_tech_keywords: List[str] = Field(description="Keywords found like 'Venmo', 'CC', or 'Monthly'.")
    has_recurring_donations: bool = Field(description="True if there is an explicit option for monthly giving.")
    outreach_priority: str = Field(description="Rate as 'High' (Zelle/Checks), 'Medium' (PayPal), or 'Low' (Modern).")

# 2. Run the Scrape using the /scrape endpoint logic
# Note: JSON mode costs 4 additional credits per page.
target_url = 'https://vric.org/' 

# 2. Run the Scrape
# The SDK returns a 'Document' object directly.
result = app.scrape(
    target_url,
    formats=[{
      "type": "json",
      "schema": NonprofitIntel.model_json_schema()
    }],
    only_main_content=True,
    timeout=120000
)

# 3. Access the data from the Document object
# Per the docs, the data object is returned directly. 
# We access 'json' as an attribute of 'result'.
if result:
    print("--- SUCCESS ---")
    print(result.json)
    
    # You can also access metadata if needed for your meeting
    # print(f"Site Title: {result.metadata['title']}")
else:
    print("No data returned.")