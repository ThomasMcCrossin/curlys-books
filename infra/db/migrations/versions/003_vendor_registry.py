"""add vendor registry

Revision ID: 003_vendor_registry
Revises: 001_initial_schema
Create Date: 2025-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_vendor_registry'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable fuzzy matching extension
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    # Create vendor registry table
    op.create_table(
        'vendor_registry',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),

        # Canonical vendor name (normalized)
        sa.Column('canonical_name', sa.Text, nullable=False, unique=True),

        # All possible name variations (for fuzzy matching)
        sa.Column('aliases', postgresql.ARRAY(sa.Text), nullable=False),

        # Vendor classification
        sa.Column('vendor_type', sa.Text, nullable=False),
        sa.Column('default_category', sa.Text),

        # Entity preferences
        sa.Column('typical_entity', sa.Text),

        # Receipt parsing metadata
        sa.Column('has_line_items', sa.Boolean, server_default='true'),
        sa.Column('has_skus', sa.Boolean, server_default='false'),
        sa.Column('receipt_format', sa.Text),

        # Usage statistics
        sa.Column('sample_count', sa.Integer, server_default='0'),
        sa.Column('annual_spend', sa.Numeric(10, 2)),
        sa.Column('last_transaction_date', sa.Date),

        # Timestamps
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )

    # Create indexes
    op.execute('CREATE INDEX idx_vendor_registry_aliases ON vendor_registry USING gin(aliases)')
    op.create_index('idx_vendor_registry_type', 'vendor_registry', ['vendor_type'])
    op.create_index('idx_vendor_registry_entity', 'vendor_registry', ['typical_entity'])
    op.create_index('idx_vendor_registry_canonical', 'vendor_registry', ['canonical_name'])

    # Create vendor normalization function
    op.execute("""
        CREATE OR REPLACE FUNCTION normalize_vendor_name(raw_name TEXT)
        RETURNS TEXT AS $$
        DECLARE
            match_record RECORD;
            best_match RECORD;
            max_similarity FLOAT := 0;
        BEGIN
            -- Clean input
            raw_name := UPPER(TRIM(raw_name));

            -- Try exact match first (fast path)
            FOR match_record IN
                SELECT canonical_name, unnest(aliases) as alias
                FROM vendor_registry
            LOOP
                IF UPPER(match_record.alias) = raw_name THEN
                    RETURN match_record.canonical_name;
                END IF;
            END LOOP;

            -- Try fuzzy match (similarity threshold: 0.6)
            FOR match_record IN
                SELECT DISTINCT
                    canonical_name,
                    MAX(similarity(raw_name, UPPER(unnest(aliases)))) as sim
                FROM vendor_registry
                GROUP BY canonical_name
                HAVING MAX(similarity(raw_name, UPPER(unnest(aliases)))) > 0.6
                ORDER BY sim DESC
                LIMIT 1
            LOOP
                RETURN match_record.canonical_name;
            END LOOP;

            -- No match found - return original (will create new vendor)
            RETURN raw_name;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE
    """)

    # Create update trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION update_vendor_registry_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    # Create trigger
    op.execute("""
        CREATE TRIGGER trigger_update_vendor_registry_timestamp
            BEFORE UPDATE ON vendor_registry
            FOR EACH ROW
            EXECUTE FUNCTION update_vendor_registry_timestamp()
    """)

    # Seed vendor data - CANTEEN Priority 1 Food Distributors
    op.execute("""
        INSERT INTO vendor_registry (canonical_name, aliases, vendor_type, default_category, typical_entity, has_line_items, has_skus, receipt_format, sample_count, annual_spend) VALUES
        ('GFS Canada', ARRAY['GFS', 'GORDON FOOD SERVICE', 'GORDON FOOD SVC', 'Gordon Food Service Canada', 'GFS CANADA INC'], 'food_distributor', 'COGS - Inventory', 'corp', true, true, 'gfs_invoice', 12, 40619.82),
        ('Capital Foodservice', ARRAY['CAPITAL', 'Capital Foods', 'Capital Food Service', 'CAPITAL PAPER', 'CAPITAL FOODSERVICE'], 'food_distributor', 'COGS - Inventory', 'corp', true, true, 'capital_invoice', 6, 8397.32),
        ('Pepsi Bottling', ARRAY['PEPSI', 'PEPSICO', 'Pepsi Cola', 'Pepsi Beverages', 'PEPSI BOTTLING'], 'beverage_distributor', 'COGS - Beverages', 'corp', true, true, 'pepsi_invoice', 7, 6244.62)
    """)

    # SHARED - Retail
    op.execute("""
        INSERT INTO vendor_registry (canonical_name, aliases, vendor_type, default_category, typical_entity, has_line_items, has_skus, receipt_format, sample_count, annual_spend) VALUES
        ('Costco Wholesale', ARRAY['COSTCO', 'COSTCO WHOLESALE', 'Costco Warehouse', 'COSTCO #', 'COSTCO WHSE'], 'retail_warehouse', 'COGS - Inventory', 'both', true, true, 'costco_receipt', 8, 47431.07),
        ('Atlantic Superstore', ARRAY['SUPERSTORE', 'ATLANTIC SUPERSTORE', 'LOBLAW', 'Superstore #', 'Real Canadian Superstore'], 'retail_grocery', 'COGS - Inventory', 'corp', true, true, 'superstore_receipt', 4, 8376.08),
        ('Pharmasave', ARRAY['PHARMASAVE', 'Pharmasave Drug Mart', 'Pharmasave Pharmacy'], 'pharmacy_retail', 'COGS - Inventory', 'both', true, false, 'pharmasave_receipt', 1, 3241.40)
    """)

    # SPORTS & SUPPLEMENTS - Priority 1 Distributors
    op.execute("""
        INSERT INTO vendor_registry (canonical_name, aliases, vendor_type, default_category, typical_entity, has_line_items, has_skus, receipt_format, sample_count, annual_spend) VALUES
        ('Grosnor Distribution', ARRAY['GROSNOR', 'Grosnor Distribution Ajax Inc.', 'Grosnor Distribution Inc', 'GROSNOR AJAX'], 'collectibles_distributor', 'COGS - Collectibles', 'soleprop', true, true, 'grosnor_invoice', 2, 65425.36),
        ('Peak Performance Products', ARRAY['PEAK', 'Peak Performance Products Inc.', 'Peak Performance', 'PEAK PERFORMANCE INC'], 'supplement_distributor', 'COGS - Supplements', 'soleprop', true, true, 'peak_invoice', 3, 21413.60),
        ('Fit Foods', ARRAY['FIT FOODS', 'Fit Foods Inc', 'FitFoods'], 'supplement_distributor', 'COGS - Supplements', 'soleprop', true, true, 'fitfoods_invoice', 2, 19812.78),
        ('Believe Supplements', ARRAY['BELIEVE', 'Believe Supplements', 'Believe Supplement', 'BELIEVE SUPP'], 'supplement_distributor', 'COGS - Supplements', 'soleprop', true, true, 'believe_invoice', 3, 10551.56)
    """)

    # SPORTS SUPPLEMENTS - Priority 2 Distributors
    op.execute("""
        INSERT INTO vendor_registry (canonical_name, aliases, vendor_type, default_category, typical_entity, has_line_items, has_skus, receipt_format, sample_count, annual_spend) VALUES
        ('Supplement Facts', ARRAY['SUPPLEMENT FACTS', 'SupplementFacts', 'Supplement Facts Distribution'], 'supplement_distributor', 'COGS - Supplements', 'soleprop', true, true, 'suppfacts_invoice', 4, 8878.43),
        ('Purity Life', ARRAY['PURITY LIFE', 'Purity Life Health Products', 'PurityLife'], 'supplement_distributor', 'COGS - Supplements', 'soleprop', true, true, 'puritylife_invoice', 4, 5073.46),
        ('Yummy Sports', ARRAY['YUMMY SPORTS', 'Yummy Sports Inc', 'YummySports'], 'supplement_distributor', 'COGS - Supplements', 'soleprop', true, true, 'yummy_invoice', 4, 3726.74),
        ('Isweet', ARRAY['ISWEET', 'I-Sweet', 'Isweet Distribution'], 'candy_distributor', 'COGS - Candy', 'soleprop', true, true, 'isweet_invoice', 2, 2256.59),
        ('Pacific Candy', ARRAY['PACIFIC CANDY', 'Pacific Candy Co', 'Pacific Candy Company'], 'candy_distributor', 'COGS - Candy', 'soleprop', true, true, 'pacific_invoice', 0, 6007.15),
        ('JJ''s Candy Distribution', ARRAY['JJ''S CANDY', 'JJs Candy', 'JJ Candy Distribution'], 'candy_distributor', 'COGS - Candy', 'soleprop', true, true, 'jjcandy_invoice', 0, 3820.38)
    """)

    # ADDITIONAL COMMON VENDORS
    op.execute("""
        INSERT INTO vendor_registry (canonical_name, aliases, vendor_type, default_category, typical_entity, has_line_items, has_skus, receipt_format, sample_count, annual_spend) VALUES
        ('Amazon', ARRAY['AMAZON', 'Amazon.ca', 'Amazon.com', 'AMZN', 'AMZ'], 'ecommerce', 'Operating Expenses', 'both', true, true, 'amazon_receipt', 5, 1875.57),
        ('NS Power', ARRAY['NS POWER', 'Nova Scotia Power', 'NSPower'], 'utility', 'Operating Expenses - Utilities', 'soleprop', false, false, 'nspower_bill', 2, 1757.86),
        ('Shopify', ARRAY['SHOPIFY', 'Shopify Inc', 'Shopify Payments'], 'saas_service', 'Operating Expenses - Software', 'both', false, false, 'shopify_invoice', 0, 7983.18),
        ('Bell Aliant', ARRAY['BELL ALIANT', 'Bell', 'Bell Canada', 'BELL'], 'utility', 'Operating Expenses - Telecom', 'both', false, false, 'bell_bill', 0, 1522.92),
        ('Walmart', ARRAY['WALMART', 'Wal-Mart', 'WALMART SUPERCENTER'], 'retail_grocery', 'COGS - Inventory', 'both', true, true, 'walmart_receipt', 0, 2975.36),
        ('Dollarama', ARRAY['DOLLARAMA', 'DOLLARAMA INC'], 'retail_discount', 'COGS - Inventory', 'corp', true, false, 'dollarama_receipt', 0, 2450.44)
    """)


def downgrade() -> None:
    # Drop trigger
    op.execute('DROP TRIGGER IF EXISTS trigger_update_vendor_registry_timestamp ON vendor_registry')

    # Drop functions
    op.execute('DROP FUNCTION IF EXISTS update_vendor_registry_timestamp()')
    op.execute('DROP FUNCTION IF EXISTS normalize_vendor_name(TEXT)')

    # Drop indexes (table drop will handle this, but explicit for clarity)
    op.drop_index('idx_vendor_registry_canonical', table_name='vendor_registry')
    op.drop_index('idx_vendor_registry_entity', table_name='vendor_registry')
    op.drop_index('idx_vendor_registry_type', table_name='vendor_registry')
    op.execute('DROP INDEX IF EXISTS idx_vendor_registry_aliases')

    # Drop table
    op.drop_table('vendor_registry')

    # Drop extension (optional - may be used by other features)
    # op.execute('DROP EXTENSION IF EXISTS pg_trgm')
