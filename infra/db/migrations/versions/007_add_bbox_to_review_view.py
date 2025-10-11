"""add bounding box to review view details

Revision ID: 007_add_bbox_to_review_view
Revises: 006_add_bounding_boxes
Create Date: 2025-01-16 10:30:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '007_add_bbox_to_review_view'
down_revision = '006_add_bounding_boxes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Recreate materialized view with bounding_box in details
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        # Drop existing view
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {schema_name}.view_review_receipt_line_items CASCADE")

        # Recreate with bounding_box
        op.execute(f"""
            CREATE MATERIALIZED VIEW {schema_name}.view_review_receipt_line_items AS
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

                -- Domain-specific details (JSONB payload) - NOW WITH BOUNDING BOX
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
                    'ai_cost', rli.ai_cost,
                    'bounding_box', rli.bounding_box
                ) AS details,

                -- Sorting/filtering helpers
                NULL::text AS vendor,
                NULL::date AS date,
                rli.line_total AS amount,
                EXTRACT(EPOCH FROM (NOW() - rli.created_at)) / 3600 AS age_hours

            FROM {schema_name}.receipt_line_items rli
            WHERE rli.requires_review = true
        """)

        # Recreate indexes
        op.execute(f"""
            CREATE UNIQUE INDEX idx_{schema_name}_review_rli_id
            ON {schema_name}.view_review_receipt_line_items (id)
        """)
        op.execute(f"""
            CREATE INDEX idx_{schema_name}_review_rli_status
            ON {schema_name}.view_review_receipt_line_items (status)
        """)
        op.execute(f"""
            CREATE INDEX idx_{schema_name}_review_rli_confidence
            ON {schema_name}.view_review_receipt_line_items (confidence)
        """)

        # Trigger already exists from previous migration, no need to recreate


def downgrade() -> None:
    # Recreate view WITHOUT bounding_box (revert to previous version)
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {schema_name}.view_review_receipt_line_items CASCADE")

        op.execute(f"""
            CREATE MATERIALIZED VIEW {schema_name}.view_review_receipt_line_items AS
            SELECT
                'receipt_line_item:' || '{schema_name}' || ':' || rli.id::text AS id,
                'receipt_line_item'::text AS type,
                '{schema_name.replace('curlys_', '')}'::text AS entity,
                rli.created_at,
                jsonb_build_object(
                    'table', 'receipt_line_items',
                    'schema', '{schema_name}',
                    'pk', rli.id
                ) AS source_ref,
                '"' || COALESCE(rli.description, 'No description') || '" → ' ||
                COALESCE(rli.product_category, '?') AS summary,
                rli.confidence_score AS confidence,
                rli.requires_review,
                COALESCE(rli.review_status, 'pending') AS status,
                rli.reviewed_by AS assignee,
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
                NULL::text AS vendor,
                NULL::date AS date,
                rli.line_total AS amount,
                EXTRACT(EPOCH FROM (NOW() - rli.created_at)) / 3600 AS age_hours
            FROM {schema_name}.receipt_line_items rli
            WHERE rli.requires_review = true
        """)

        # Recreate indexes and trigger
        op.execute(f"CREATE UNIQUE INDEX idx_{schema_name}_review_rli_id ON {schema_name}.view_review_receipt_line_items (id)")
        op.execute(f"CREATE INDEX idx_{schema_name}_review_rli_status ON {schema_name}.view_review_receipt_line_items (status)")
        op.execute(f"CREATE INDEX idx_{schema_name}_review_rli_confidence ON {schema_name}.view_review_receipt_line_items (confidence)")
        op.execute(f"CREATE TRIGGER trg_{schema_name}_refresh_review_view AFTER INSERT OR UPDATE OR DELETE ON {schema_name}.receipt_line_items FOR EACH STATEMENT EXECUTE FUNCTION {schema_name}.refresh_review_view_on_change()")
