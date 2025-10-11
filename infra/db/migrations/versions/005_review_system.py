"""add review system views and tables

Revision ID: 005_review_system
Revises: 004_product_mappings
Create Date: 2025-10-10 09:00:00.000000

Generic review queue system for human-in-the-loop approval workflow.
Supports receipt line items, reimbursement batches, bank matches, tax alerts, etc.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005_review_system'
down_revision = '004_product_mappings'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create review_type enum in shared schema (if not exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE shared.review_type AS ENUM (
                'receipt_line_item',
                'reimbursement_batch',
                'bank_match',
                'tax_alert',
                'vendor_duplicate',
                'manual_entry'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create review_status enum in shared schema (if not exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE shared.review_status AS ENUM (
                'pending',
                'needs_info',
                'approved',
                'rejected',
                'posted',
                'snoozed'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create review_activity table in shared schema (audit trail)
    op.execute("""
        CREATE TABLE IF NOT EXISTS shared.review_activity (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            reviewable_id TEXT NOT NULL,
            reviewable_type shared.review_type NOT NULL,
            entity TEXT NOT NULL,
            action TEXT NOT NULL,
            performed_by TEXT,
            old_values JSONB,
            new_values JSONB,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Indexes for audit queries
    op.execute("CREATE INDEX IF NOT EXISTS idx_review_activity_reviewable ON shared.review_activity (reviewable_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_review_activity_type ON shared.review_activity (reviewable_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_review_activity_entity ON shared.review_activity (entity)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_review_activity_created ON shared.review_activity (created_at)")

    # Add review_status to receipt_line_items in both schemas
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        # Add status column (defaults to pending if requires_review=true)
        op.execute(f"""
            ALTER TABLE {schema_name}.receipt_line_items
            ADD COLUMN IF NOT EXISTS review_status shared.review_status DEFAULT 'pending'
        """)

        # Add reviewed_by and reviewed_at if they don't exist
        # (Migration 004 had these, but let's be safe)
        op.execute(f"""
            ALTER TABLE {schema_name}.receipt_line_items
            ADD COLUMN IF NOT EXISTS reviewed_by TEXT
        """)

        op.execute(f"""
            ALTER TABLE {schema_name}.receipt_line_items
            ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ
        """)

        # Create materialized view for receipt line items requiring review
        # This projects the native table into the generic Reviewable shape
        # NOTE: receipts table doesn't exist yet, so we use only receipt_line_items
        op.execute(f"""
            CREATE MATERIALIZED VIEW IF NOT EXISTS {schema_name}.view_review_receipt_line_items AS
            SELECT
                -- Reviewable contract fields
                'receipt_line_item:' || '{schema_name}' || ':' || rli.id::text AS id,
                'receipt_line_item'::text AS type,
                '{schema_name.replace('curlys_', '')}'::text AS entity,
                rli.created_at,
                jsonb_build_object(
                    'table', 'receipt_line_items',
                    'schema', '{schema_name}',
                    'pk', rli.id
                ) AS source_ref,

                -- Summary for table view
                '"' || COALESCE(rli.description, 'No description') || '" → ' ||
                COALESCE(rli.product_category, '?') AS summary,

                -- Confidence score
                rli.confidence_score AS confidence,

                -- Review flags
                rli.requires_review,
                COALESCE(rli.review_status, 'pending') AS status,
                rli.reviewed_by AS assignee,

                -- Domain-specific details (JSONB payload)
                jsonb_build_object(
                    'receipt_id', rli.receipt_id,
                    'line_number', rli.line_number,
                    'sku', rli.sku,
                    'description', rli.description,
                    'quantity', rli.quantity,
                    'unit_price', rli.unit_price,
                    'line_total', rli.line_total,
                    'account_code', rli.account_code,
                    'product_category', rli.product_category,
                    'categorization_source', rli.categorization_source,
                    'ai_cost', rli.ai_cost
                ) AS details,

                -- Sorting/filtering helpers
                NULL::text AS vendor,
                NULL::date AS date,
                rli.line_total AS amount,
                EXTRACT(EPOCH FROM (NOW() - rli.created_at)) / 3600 AS age_hours

            FROM {schema_name}.receipt_line_items rli
            WHERE rli.requires_review = true
        """)

        # Create indexes on materialized view
        op.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_{schema_name}_review_rli_id
            ON {schema_name}.view_review_receipt_line_items (id)
        """)
        op.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{schema_name}_review_rli_status
            ON {schema_name}.view_review_receipt_line_items (status)
        """)
        op.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{schema_name}_review_rli_confidence
            ON {schema_name}.view_review_receipt_line_items (confidence)
        """)

    # Create function to refresh review views
    op.execute("""
        CREATE OR REPLACE FUNCTION shared.refresh_review_views()
        RETURNS void AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY curlys_corp.view_review_receipt_line_items;
            REFRESH MATERIALIZED VIEW CONCURRENTLY curlys_soleprop.view_review_receipt_line_items;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger to auto-refresh on receipt_line_items changes
    # (In production, use a background job instead of triggers for perf)
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.execute(f"""
            CREATE OR REPLACE FUNCTION {schema_name}.refresh_review_view_on_change()
            RETURNS TRIGGER AS $$
            BEGIN
                REFRESH MATERIALIZED VIEW CONCURRENTLY {schema_name}.view_review_receipt_line_items;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
        """)

        op.execute(f"""
            CREATE TRIGGER trg_{schema_name}_refresh_review_view
            AFTER INSERT OR UPDATE OR DELETE ON {schema_name}.receipt_line_items
            FOR EACH STATEMENT
            EXECUTE FUNCTION {schema_name}.refresh_review_view_on_change()
        """)


def downgrade() -> None:
    # Drop triggers
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.execute(f'DROP TRIGGER IF EXISTS trg_{schema_name}_refresh_review_view ON {schema_name}.receipt_line_items')
        op.execute(f'DROP FUNCTION IF EXISTS {schema_name}.refresh_review_view_on_change()')

    # Drop refresh function
    op.execute('DROP FUNCTION IF EXISTS shared.refresh_review_views()')

    # Drop materialized views
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.execute(f'DROP MATERIALIZED VIEW IF EXISTS {schema_name}.view_review_receipt_line_items')

    # Drop columns from receipt_line_items
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.drop_column('receipt_line_items', 'review_status', schema=schema_name)
        # Don't drop reviewed_by/reviewed_at - they existed before

    # Drop indexes
    op.drop_index('idx_review_activity_created', 'review_activity', schema='shared')
    op.drop_index('idx_review_activity_entity', 'review_activity', schema='shared')
    op.drop_index('idx_review_activity_type', 'review_activity', schema='shared')
    op.drop_index('idx_review_activity_reviewable', 'review_activity', schema='shared')

    # Drop activity table
    op.drop_table('review_activity', schema='shared')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS shared.review_status')
    op.execute('DROP TYPE IF EXISTS shared.review_type')
