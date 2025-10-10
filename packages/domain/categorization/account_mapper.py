"""
Account Mapper - Rule-based mapping from AI product categories to GL accounts

Stage 2 of categorization: Once AI recognizes the product type, this module
maps it to the appropriate GL account using deterministic rules.

NO AI CALLS - Pure rule-based logic.

Uses expanded Chart of Accounts with granular sub-accounts for better analytics:
- 5000-5009: Food COGS (hot dogs, sandwiches, pizza, frozen, etc.)
- 5010-5019: Beverage COGS (soda, water, energy, sports drinks, etc.)
- 5020-5029: Supplements COGS (protein, vitamins, pre-workout, etc.)
- 5030-5039: Retail Goods COGS (snacks, candy, accessories, apparel, etc.)
- 5200-5209: Packaging & Supplies (containers, bags, cleaning, paper, etc.)

Tax reporting: Parent accounts (5000, 5010, 5020, 5030) roll up all children
for GIFI/T2125 compliance.
"""
from decimal import Decimal
from enum import Enum
from typing import Optional

import structlog

from packages.domain.categorization.schemas import AccountMapping

logger = structlog.get_logger()


class ProductCategory(str, Enum):
    """
    Product categories recognized by AI (Stage 1).

    These are detailed categories for AI training and analytics.
    Multiple categories can map to the same GL account.
    """
    # === FOOD (5000-5009, 5099) ===
    FOOD_HOTDOG = "food_hotdog"
    FOOD_SANDWICH = "food_sandwich"
    FOOD_PIZZA = "food_pizza"
    FOOD_FROZEN = "food_frozen"
    FOOD_BAKERY = "food_bakery"
    FOOD_DAIRY = "food_dairy"
    FOOD_MEAT = "food_meat"
    FOOD_PRODUCE = "food_produce"
    FOOD_OIL = "food_oil"  # Cooking oils and fats
    FOOD_CONDIMENT = "food_condiment"
    FOOD_PANTRY = "food_pantry"
    FOOD_OTHER = "food_other"

    # === BEVERAGE (5010-5019) ===
    BEVERAGE_SODA = "beverage_soda"
    BEVERAGE_WATER = "beverage_water"
    BEVERAGE_ENERGY = "beverage_energy"
    BEVERAGE_SPORTS = "beverage_sports"
    BEVERAGE_JUICE = "beverage_juice"
    BEVERAGE_COFFEE = "beverage_coffee"
    BEVERAGE_TEA = "beverage_tea"
    BEVERAGE_MILK = "beverage_milk"
    BEVERAGE_ALCOHOL = "beverage_alcohol"
    BEVERAGE_OTHER = "beverage_other"

    # === SUPPLEMENTS (5020-5029) ===
    SUPPLEMENT_PROTEIN = "supplement_protein"
    SUPPLEMENT_VITAMIN = "supplement_vitamin"
    SUPPLEMENT_PREWORKOUT = "supplement_preworkout"
    SUPPLEMENT_RECOVERY = "supplement_recovery"
    SUPPLEMENT_SPORTS_NUTRITION = "supplement_sports_nutrition"
    SUPPLEMENT_OTHER = "supplement_other"

    # === RETAIL GOODS (5030-5039) ===
    RETAIL_SNACK = "retail_snack"
    RETAIL_CANDY = "retail_candy"
    RETAIL_HEALTH = "retail_health"
    RETAIL_ACCESSORY = "retail_accessory"
    RETAIL_APPAREL = "retail_apparel"
    RETAIL_OTHER = "retail_other"

    # === FREIGHT (5100) ===
    FREIGHT = "freight"

    # === PACKAGING & SUPPLIES (5200-5209) ===
    PACKAGING_CONTAINER = "packaging_container"
    PACKAGING_BAG = "packaging_bag"
    PACKAGING_UTENSIL = "packaging_utensil"
    SUPPLY_CLEANING = "supply_cleaning"
    SUPPLY_PAPER = "supply_paper"
    SUPPLY_KITCHEN = "supply_kitchen"
    SUPPLY_OTHER = "supply_other"

    # === OFFICE SUPPLIES (6600) ===
    OFFICE_SUPPLY = "office_supply"

    # === REPAIRS & MAINTENANCE (6300) ===
    REPAIR_EQUIPMENT = "repair_equipment"
    REPAIR_BUILDING = "repair_building"
    MAINTENANCE = "maintenance"

    # === EQUIPMENT (1500 if ≥$2500, 6300 if <$2500) ===
    EQUIPMENT = "equipment"

    # === DEPOSITS (9000) ===
    DEPOSIT = "deposit"

    # === LICENSES (6800) ===
    LICENSE = "license"

    # === UNKNOWN (9100) ===
    UNKNOWN = "unknown"


class AccountMapper:
    """
    Maps product categories to GL accounts using deterministic rules.

    Uses expanded chart_of_accounts.csv with granular sub-accounts.
    """

    # Capitalization threshold for equipment
    CAPITALIZATION_THRESHOLD = Decimal("2500.00")

    # === CATEGORY → GL ACCOUNT MAPPING ===
    CATEGORY_MAP = {
        # FOOD → Granular sub-accounts
        ProductCategory.FOOD_HOTDOG: "5001",
        ProductCategory.FOOD_SANDWICH: "5002",
        ProductCategory.FOOD_PIZZA: "5003",
        ProductCategory.FOOD_FROZEN: "5004",
        ProductCategory.FOOD_BAKERY: "5005",
        ProductCategory.FOOD_DAIRY: "5006",
        ProductCategory.FOOD_MEAT: "5007",
        ProductCategory.FOOD_PRODUCE: "5008",
        ProductCategory.FOOD_OIL: "5009",  # Cooking oils and fats
        ProductCategory.FOOD_CONDIMENT: "5099",
        ProductCategory.FOOD_PANTRY: "5099",
        ProductCategory.FOOD_OTHER: "5099",

        # BEVERAGE → Granular sub-accounts
        ProductCategory.BEVERAGE_SODA: "5011",
        ProductCategory.BEVERAGE_WATER: "5012",
        ProductCategory.BEVERAGE_ENERGY: "5013",
        ProductCategory.BEVERAGE_SPORTS: "5014",
        ProductCategory.BEVERAGE_JUICE: "5015",
        ProductCategory.BEVERAGE_COFFEE: "5016",
        ProductCategory.BEVERAGE_TEA: "5016",
        ProductCategory.BEVERAGE_MILK: "5017",
        ProductCategory.BEVERAGE_ALCOHOL: "5018",
        ProductCategory.BEVERAGE_OTHER: "5019",

        # SUPPLEMENTS → Granular sub-accounts
        ProductCategory.SUPPLEMENT_PROTEIN: "5021",
        ProductCategory.SUPPLEMENT_VITAMIN: "5022",
        ProductCategory.SUPPLEMENT_PREWORKOUT: "5023",
        ProductCategory.SUPPLEMENT_RECOVERY: "5024",
        ProductCategory.SUPPLEMENT_SPORTS_NUTRITION: "5025",
        ProductCategory.SUPPLEMENT_OTHER: "5029",

        # RETAIL GOODS → Granular sub-accounts
        ProductCategory.RETAIL_SNACK: "5031",
        ProductCategory.RETAIL_CANDY: "5032",
        ProductCategory.RETAIL_HEALTH: "5033",
        ProductCategory.RETAIL_ACCESSORY: "5034",
        ProductCategory.RETAIL_APPAREL: "5035",
        ProductCategory.RETAIL_OTHER: "5039",

        # FREIGHT
        ProductCategory.FREIGHT: "5100",

        # PACKAGING & SUPPLIES → Granular sub-accounts
        ProductCategory.PACKAGING_CONTAINER: "5201",
        ProductCategory.PACKAGING_BAG: "5202",
        ProductCategory.PACKAGING_UTENSIL: "5203",
        ProductCategory.SUPPLY_CLEANING: "5204",
        ProductCategory.SUPPLY_PAPER: "5205",
        ProductCategory.SUPPLY_KITCHEN: "5206",
        ProductCategory.SUPPLY_OTHER: "5209",

        # OTHER EXPENSE ACCOUNTS
        ProductCategory.OFFICE_SUPPLY: "6600",
        ProductCategory.REPAIR_EQUIPMENT: "6300",
        ProductCategory.REPAIR_BUILDING: "6300",
        ProductCategory.MAINTENANCE: "6300",
        ProductCategory.EQUIPMENT: "6300",  # Default to expense (overridden if ≥$2500)
        ProductCategory.DEPOSIT: "9000",
        ProductCategory.LICENSE: "6800",
        ProductCategory.UNKNOWN: "9100",
    }

    # Account names (for reference)
    ACCOUNT_NAMES = {
        "5001": "COGS - Food - Hot Dogs",
        "5002": "COGS - Food - Sandwiches",
        "5003": "COGS - Food - Pizza",
        "5004": "COGS - Food - Frozen",
        "5005": "COGS - Food - Bakery",
        "5006": "COGS - Food - Dairy",
        "5007": "COGS - Food - Meat/Deli",
        "5008": "COGS - Food - Produce",
        "5009": "COGS - Food - Cooking Oil/Fats",
        "5099": "COGS - Food - Other",
        "5011": "COGS - Beverage - Soda",
        "5012": "COGS - Beverage - Water",
        "5013": "COGS - Beverage - Energy Drinks",
        "5014": "COGS - Beverage - Sports Drinks",
        "5015": "COGS - Beverage - Juice",
        "5016": "COGS - Beverage - Coffee/Tea",
        "5017": "COGS - Beverage - Milk Products",
        "5018": "COGS - Beverage - Alcohol",
        "5019": "COGS - Beverage - Other",
        "5021": "COGS - Supplements - Protein",
        "5022": "COGS - Supplements - Vitamins",
        "5023": "COGS - Supplements - Pre-Workout",
        "5024": "COGS - Supplements - Recovery",
        "5025": "COGS - Supplements - Sports Nutrition",
        "5029": "COGS - Supplements - Other",
        "5031": "COGS - Retail - Snacks/Chips",
        "5032": "COGS - Retail - Candy/Chocolate",
        "5033": "COGS - Retail - Health Products",
        "5034": "COGS - Retail - Accessories",
        "5035": "COGS - Retail - Apparel",
        "5039": "COGS - Retail - Other",
        "5100": "Freight In",
        "5201": "Packaging - Containers/Cups",
        "5202": "Packaging - Bags/Wrapping",
        "5203": "Packaging - Utensils/Straws",
        "5204": "Supplies - Cleaning",
        "5205": "Supplies - Paper Products",
        "5206": "Supplies - Kitchen",
        "5209": "Supplies - Other",
        "6300": "Repairs & Maintenance",
        "6600": "Office Supplies",
        "6800": "Licenses & Permits",
        "9000": "Deposits - Bottle/Container",
        "9100": "Pending Receipt - No ITC",
        "1500": "Equipment & Fixtures",
    }

    def map_to_account(
        self,
        product_category: str,
        line_total: Optional[Decimal] = None,
    ) -> AccountMapping:
        """
        Map product category to GL account code.

        Args:
            product_category: Category from AI recognition
            line_total: Line total (for equipment capitalization check)

        Returns:
            AccountMapping with account code and metadata
        """
        try:
            category_enum = ProductCategory(product_category)
        except ValueError:
            logger.warning("unknown_product_category",
                          category=product_category,
                          message="Category not in enum, treating as UNKNOWN")
            category_enum = ProductCategory.UNKNOWN

        # Get account code from map
        account_code = self.CATEGORY_MAP.get(category_enum)

        if not account_code:
            logger.error("missing_category_mapping",
                        category=category_enum.value,
                        message="Category exists but no mapping defined - using 9100")
            account_code = "9100"

        # Special handling: Equipment capitalization
        requires_review = False
        if category_enum == ProductCategory.EQUIPMENT:
            if line_total and line_total >= self.CAPITALIZATION_THRESHOLD:
                # Capitalize as fixed asset
                account_code = "1500"
                requires_review = True
                logger.info("equipment_capitalized",
                           amount=float(line_total),
                           threshold=float(self.CAPITALIZATION_THRESHOLD))
            else:
                # Expense as repair/maintenance
                account_code = "6300"

        # Unknown categories always require review
        if category_enum == ProductCategory.UNKNOWN:
            requires_review = True

        # Get account name
        account_name = self.ACCOUNT_NAMES.get(account_code, "Unknown Account")

        return AccountMapping(
            account_code=account_code,
            account_name=account_name,
            confidence=1.0 if not requires_review else 0.5,
            requires_review=requires_review,
            mapping_rule=f"{category_enum.value} → {account_code}"
        )

    def get_account_name(self, account_code: str) -> Optional[str]:
        """Get human-readable account name for account code."""
        return self.ACCOUNT_NAMES.get(account_code)

    def list_categories(self) -> list[dict]:
        """
        List all product categories and their GL account mappings.

        Returns:
            List of category mappings for documentation
        """
        result = []
        for category in ProductCategory:
            account_code = self.CATEGORY_MAP.get(category)
            if account_code:
                account_name = self.ACCOUNT_NAMES.get(account_code, "Unknown")
                result.append({
                    "category": category.value,
                    "account_code": account_code,
                    "account_name": account_name
                })
        return result


# Singleton instance
account_mapper = AccountMapper()
