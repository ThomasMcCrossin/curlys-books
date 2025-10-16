"""add validation warnings to receipts

Revision ID: 008_add_validation_warnings
Revises: 007_add_bbox_to_review_view
Create Date: 2025-10-16 02:00:00.000000

Stores validation warnings when OCR/parsing detects issues like:
- Line items don't sum to subtotal (missing/faded items)
- OCR confidence below threshold
- Missing required fields
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '008_add_validation_warnings'
down_revision = '007_add_bbox_to_review_view'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add validation_warnings JSONB column to receipts in both schemas
    # Format: [{"type": "subtotal_mismatch", "message": "...", "data": {...}}, ...]
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.add_column(
            'receipts',
            sa.Column(
                'validation_warnings',
                postgresql.JSONB,
                nullable=True,
                comment='Array of validation warnings: [{type, message, data}, ...]'
            ),
            schema=schema_name
        )

        # Add index for querying receipts with warnings
        op.execute(f"""
            CREATE INDEX idx_{schema_name}_receipts_has_warnings
            ON {schema_name}.receipts ((validation_warnings IS NOT NULL AND jsonb_array_length(validation_warnings) > 0))
        """)


def downgrade() -> None:
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.execute(f'DROP INDEX IF EXISTS {schema_name}.idx_{schema_name}_receipts_has_warnings')
        op.drop_column('receipts', 'validation_warnings', schema=schema_name)
