"""add product mappings and receipt line items

Revision ID: 004_product_mappings
Revises: 003_vendor_registry
Create Date: 2025-01-15 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_product_mappings'
down_revision = '003_vendor_registry'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create product_mappings table in shared schema (cross-entity SKU cache)
    op.create_table(
        'product_mappings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),

        # Vendor + SKU identification
        sa.Column('vendor_canonical', sa.Text, nullable=False, comment='Canonical vendor name from vendor_registry'),
        sa.Column('sku', sa.Text, nullable=False, comment='Vendor SKU code'),
        sa.Column('description_normalized', sa.Text, comment='Cleaned product description'),

        # Categorization (user-approved)
        sa.Column('account_code', sa.Text, nullable=False, comment='Chart of accounts code'),
        sa.Column('product_category', sa.Text, comment='Product classification (beverages_pop, etc)'),

        # Learning metadata
        sa.Column('times_seen', sa.Integer, nullable=False, server_default='1', comment='How many times this SKU has appeared'),
        sa.Column('user_confidence', sa.Numeric(3, 2), comment='User confidence rating 0.00-1.00'),
        sa.Column('last_seen', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), comment='Last receipt with this SKU'),

        # Fast lookup
        sa.Column('lookup_hash', sa.Text, nullable=False, unique=True, comment='hash(vendor_canonical || sku)'),

        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema='shared'
    )

    # Index for fast SKU lookups
    op.create_index('idx_product_mappings_lookup', 'product_mappings', ['lookup_hash'], schema='shared')
    op.create_index('idx_product_mappings_vendor_sku', 'product_mappings', ['vendor_canonical', 'sku'], schema='shared')

    # Create receipt_line_items tables in both entity schemas
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.create_table(
            'receipt_line_items',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),

            # Receipt reference
            sa.Column('receipt_id', postgresql.UUID(as_uuid=True), nullable=False, comment='FK to receipts table'),

            # Extracted data from parser
            sa.Column('line_number', sa.Integer, nullable=False, comment='Line order on receipt'),
            sa.Column('sku', sa.Text, comment='Vendor SKU code (if available)'),
            sa.Column('description', sa.Text, nullable=False, comment='Item description from receipt'),
            sa.Column('quantity', sa.Numeric(10, 2), nullable=False, server_default='1.00'),
            sa.Column('unit_price', sa.Numeric(10, 2), comment='Price per unit'),
            sa.Column('line_total', sa.Numeric(10, 2), nullable=False, comment='Total for this line'),

            # Categorization (from cache or AI)
            sa.Column('account_code', sa.Text, comment='Accounting category'),
            sa.Column('product_category', sa.Text, comment='Product classification'),
            sa.Column('confidence_score', sa.Numeric(3, 2), comment='AI/cache confidence 0.00-1.00'),
            sa.Column('categorization_source', sa.Text, comment='cached, ai_suggested, user_override'),

            # Review workflow
            sa.Column('requires_review', sa.Boolean, nullable=False, server_default='true', comment='Needs manual review'),
            sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True), comment='When line was approved'),
            sa.Column('reviewed_by', sa.Text, comment='User who approved'),

            # AI cost tracking
            sa.Column('ai_cost', sa.Numeric(10, 6), comment='Cost in USD for AI categorization'),

            sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
            schema=schema_name
        )

        # Foreign key to receipts in same schema (will be added later when receipts table exists)
        # NOTE: Skipping FK constraint for now - receipts table created by init.sql, not migrations yet
        # op.create_foreign_key(
        #     f'fk_{schema_name}_receipt_line_items_receipt',
        #     'receipt_line_items', 'receipts',
        #     ['receipt_id'], ['id'],
        #     source_schema=schema_name,
        #     referent_schema=schema_name,
        #     ondelete='CASCADE'
        # )

        # Indexes for common queries
        op.create_index(f'idx_{schema_name}_receipt_line_items_receipt', 'receipt_line_items', ['receipt_id'], schema=schema_name)
        op.create_index(f'idx_{schema_name}_receipt_line_items_sku', 'receipt_line_items', ['sku'], schema=schema_name)
        op.create_index(f'idx_{schema_name}_receipt_line_items_review', 'receipt_line_items', ['requires_review'], schema=schema_name)

    # Add lookup_hash generation function in shared schema
    op.execute("""
        CREATE OR REPLACE FUNCTION shared.generate_product_lookup_hash(vendor TEXT, sku TEXT)
        RETURNS TEXT AS $$
        BEGIN
            RETURN encode(sha256((vendor || '||' || sku)::bytea), 'hex');
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
    """)

    # Add trigger to auto-update lookup_hash
    op.execute("""
        CREATE OR REPLACE FUNCTION shared.update_product_mapping_hash()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.lookup_hash := shared.generate_product_lookup_hash(NEW.vendor_canonical, NEW.sku);
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_product_mapping_hash
        BEFORE INSERT OR UPDATE ON shared.product_mappings
        FOR EACH ROW
        EXECUTE FUNCTION shared.update_product_mapping_hash();
    """)


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS trg_product_mapping_hash ON shared.product_mappings')
    op.execute('DROP FUNCTION IF EXISTS shared.update_product_mapping_hash()')
    op.execute('DROP FUNCTION IF EXISTS shared.generate_product_lookup_hash(TEXT, TEXT)')

    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.drop_index(f'idx_{schema_name}_receipt_line_items_review', 'receipt_line_items', schema=schema_name)
        op.drop_index(f'idx_{schema_name}_receipt_line_items_sku', 'receipt_line_items', schema=schema_name)
        op.drop_index(f'idx_{schema_name}_receipt_line_items_receipt', 'receipt_line_items', schema=schema_name)
        # op.drop_constraint(f'fk_{schema_name}_receipt_line_items_receipt', 'receipt_line_items', schema=schema_name, type_='foreignkey')
        op.drop_table('receipt_line_items', schema=schema_name)

    op.drop_index('idx_product_mappings_vendor_sku', 'product_mappings', schema='shared')
    op.drop_index('idx_product_mappings_lookup', 'product_mappings', schema='shared')
    op.drop_table('product_mappings', schema='shared')
