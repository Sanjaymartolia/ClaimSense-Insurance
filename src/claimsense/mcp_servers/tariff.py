import csv
import os
from pathlib import Path
from pydantic import BaseModel
from fastmcp import FastMCP

# 1. Pydantic Models for Structured Output
class TariffResult(BaseModel):
    procedure: str
    tier: int
    expected_min: int
    expected_max: int

class ComparisonResult(BaseModel):
    procedure: str
    tier: int
    billed_amount: int
    expected_min: int
    expected_max: int
    is_outlier: bool

class ToolError(BaseModel):
    error: str
    retryable: bool = False

# 2. Data Loading Function
def load_tariff_data() -> dict:
    """Loads the synthetic tariff data from the CSV file."""
    # Construct path relative to the project root assuming script runs from root
    # Adjust this path if your working directory differs when running the server
    project_root = Path(__file__).resolve().parents[3] 
    csv_path = project_root / "data" / "tariffs" / "synthetic_tariffs.csv"
    
    tariff_db = {}
    try:
        with open(csv_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                proc = row['procedure'].strip().lower()
                tier = int(row['tier'])
                min_cost = int(row['min_cost'])
                max_cost = int(row['max_cost'])
                
                if proc not in tariff_db:
                    tariff_db[proc] = {}
                tariff_db[proc][tier] = {"min": min_cost, "max": max_cost}
    except FileNotFoundError:
        print(f"Warning: Tariff CSV not found at {csv_path}. Using empty database.")
    except Exception as e:
        print(f"Error loading tariff data: {e}")
        
    return tariff_db

# Load the database once when the server starts
TARIFF_DB = load_tariff_data()

# 3. The FastMCP Server
mcp = FastMCP("tariff")

@mcp.tool()
def get_procedure_tariff(procedure: str, tier: int) -> TariffResult | ToolError:
    """[read] Get expected cost range for a procedure in a specific city tier."""
    proc_lower = procedure.lower()
    if proc_lower not in TARIFF_DB:
        return ToolError(error=f"Procedure '{procedure}' not found in tariff database.")
    if tier not in TARIFF_DB.get(proc_lower, {}):
        return ToolError(error=f"Tier {tier} not found for procedure '{procedure}'.")
    
    data = TARIFF_DB[proc_lower][tier]
    return TariffResult(
        procedure=proc_lower,
        tier=tier,
        expected_min=data["min"],
        expected_max=data["max"]
    )

@mcp.tool()
def compare_bill_with_tariff(procedure: str, tier: int, billed_amount: int) -> ComparisonResult | ToolError:
    """[read] Compare a billed amount against the expected tariff range."""
    tariff_result = get_procedure_tariff(procedure, tier)
    
    if isinstance(tariff_result, ToolError):
        return tariff_result
        
    is_outlier = billed_amount > tariff_result.expected_max or billed_amount < tariff_result.expected_min
    
    return ComparisonResult(
        procedure=tariff_result.procedure,
        tier=tariff_result.tier,
        billed_amount=billed_amount,
        expected_min=tariff_result.expected_min,
        expected_max=tariff_result.expected_max,
        is_outlier=is_outlier
    )

if __name__ == "__main__":
    mcp.run()
