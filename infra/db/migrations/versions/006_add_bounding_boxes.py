"""add bounding boxes to receipt line items

Revision ID: 006_add_bounding_boxes
Revises: 005_review_system
Create Date: 2025-01-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '006_add_bounding_boxes'
down_revision = '005_review_system'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add bounding_box column to receipt_line_items in both schemas
    # This stores the Textract LINE bounding box that best matches this line item
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.add_column(
            'receipt_line_items',
            sa.Column(
                'bounding_box',
                postgresql.JSONB,
                comment='Textract bounding box for this line: {left, top, width, height, confidence}'
            ),
            schema=schema_name
        )


def downgrade() -> None:
    for schema_name in ['curlys_corp', 'curlys_soleprop']:
        op.drop_column('receipt_line_items', 'bounding_box', schema=schema_name)
