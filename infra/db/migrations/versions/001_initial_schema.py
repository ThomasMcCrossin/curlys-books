"""Initial schema for Curly's Books

Revision ID: 001_initial_schema
Revises: 
Create Date: 2025-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def create_entity_tables(schema_name):
    """Create tables for a single entity (corp or soleprop)"""
    
    # Chart of Accounts
    op.create_table(
        'chart_of_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('account_code', sa.String(20), nullable=False),
        sa.Column('account_name', sa.String(255), nullable=False),
        sa.Column('account_type', sa.String(50), nullable=False),  # asset, liability, equity, revenue, expense
        sa.Column('parent_code', sa.String(20)),
        sa.Column('gifi_code', sa.String(10)),
        sa.Column('t2125_line', sa.String(10)),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('requires_receipt', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('is_tax_account', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_unique_constraint(f'uq_{schema_name}_coa_code', 'chart_of_accounts', ['account_code'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_coa_type', 'chart_of_accounts', ['account_type'], schema=schema_name)
    
    # Vendors
    op.create_table(
        'vendors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('vendor_name', sa.String(255), nullable=False),
        sa.Column('vendor_aliases', postgresql.ARRAY(sa.String), server_default='{}'),
        sa.Column('default_account_code', sa.String(20)),
        sa.Column('default_tax_treatment', sa.String(50)),  # taxable, zero_rated, exempt
        sa.Column('payment_terms', sa.String(50)),  # Net 7, Net 14, 15th next month, etc.
        sa.Column('autopay_enabled', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('autopay_method', sa.String(50)),  # pad, eft
        sa.Column('pad_originator_id', sa.String(50)),
        sa.Column('matching_rules', postgresql.JSONB),  # date window, amount tolerance, etc.
        sa.Column('parsing_quirks', postgresql.JSONB),  # vendor-specific parsing rules
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_index(f'idx_{schema_name}_vendors_name', 'vendors', ['vendor_name'], schema=schema_name)
    
    # Receipts
    op.create_table(
        'receipts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('receipt_number', sa.String(50), unique=True),  # auto-generated
        sa.Column('source', sa.Enum('pwa', 'email', 'drive', 'manual', name='receipt_source', schema='shared'), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True)),
        sa.Column('vendor_guess', sa.String(255)),  # before vendor_id is confirmed
        sa.Column('purchase_date', sa.Date, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='CAD'),
        sa.Column('subtotal', sa.Numeric(12, 2), nullable=False),
        sa.Column('tax_total', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('total', sa.Numeric(12, 2), nullable=False),
        sa.Column('invoice_number', sa.String(100)),
        sa.Column('due_date', sa.Date),
        sa.Column('is_bill', sa.Boolean, nullable=False, server_default='false'),  # true = A/P, false = expense
        sa.Column('content_hash', sa.String(64), nullable=False),  # SHA256 of original file
        sa.Column('perceptual_hash', sa.String(64)),  # pHash for image similarity
        sa.Column('ocr_confidence', sa.Integer),  # 0-100
        sa.Column('ocr_method', sa.String(50)),  # tesseract, gpt4v
        sa.Column('normalized_data', postgresql.JSONB, nullable=False),  # Full ReceiptNormalized schema
        sa.Column('parsing_errors', postgresql.JSONB),
        sa.Column('status', sa.Enum('pending', 'matched', 'posted', 'void', name='transaction_status', schema='shared'), 
                  nullable=False, server_default='pending'),
        sa.Column('matched_bank_line_id', postgresql.UUID(as_uuid=True)),
        sa.Column('posted_journal_entry_id', postgresql.UUID(as_uuid=True)),
        sa.Column('review_notes', sa.Text),
        sa.Column('uploaded_by', sa.String(255)),
        sa.Column('reviewed_by', sa.String(255)),
        sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_index(f'idx_{schema_name}_receipts_date', 'receipts', ['purchase_date'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_receipts_vendor', 'receipts', ['vendor_id'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_receipts_status', 'receipts', ['status'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_receipts_hash', 'receipts', ['content_hash'], schema=schema_name)
    
    # Receipt Lines (detailed line items)
    op.create_table(
        'receipt_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('receipt_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('line_index', sa.Integer, nullable=False),
        sa.Column('line_type', sa.String(20), nullable=False),  # item, discount, deposit, fee
        sa.Column('raw_text', sa.Text),
        sa.Column('vendor_sku', sa.String(100)),
        sa.Column('upc', sa.String(20)),
        sa.Column('item_description', sa.String(500)),
        sa.Column('quantity', sa.Numeric(12, 4)),
        sa.Column('unit_price', sa.Numeric(12, 4)),
        sa.Column('line_total', sa.Numeric(12, 2), nullable=False),
        sa.Column('tax_flag', sa.String(1)),  # Y, N
        sa.Column('tax_amount', sa.Numeric(12, 2)),
        sa.Column('account_code', sa.String(20)),  # mapped GL account
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_index(f'idx_{schema_name}_receipt_lines_receipt', 'receipt_lines', ['receipt_id'], schema=schema_name)
    op.create_foreign_key(f'fk_{schema_name}_receipt_lines_receipt', 'receipt_lines', 'receipts', 
                          ['receipt_id'], ['id'], source_schema=schema_name, referent_schema=schema_name,
                          ondelete='CASCADE')
    
    # Bank Statements
    op.create_table(
        'bank_statements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('statement_date', sa.Date, nullable=False),
        sa.Column('account_name', sa.String(255), nullable=False),
        sa.Column('account_number_last4', sa.String(4)),
        sa.Column('opening_balance', sa.Numeric(12, 2)),
        sa.Column('closing_balance', sa.Numeric(12, 2)),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('imported_by', sa.String(255)),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_unique_constraint(f'uq_{schema_name}_statement_hash', 'bank_statements', ['file_hash'], schema=schema_name)
    
    # Bank Lines
    op.create_table(
        'bank_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('statement_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('transaction_date', sa.Date, nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('debit', sa.Numeric(12, 2)),
        sa.Column('credit', sa.Numeric(12, 2)),
        sa.Column('balance', sa.Numeric(12, 2)),
        sa.Column('extracted_merchant', sa.String(255)),
        sa.Column('extracted_reference', sa.String(100)),
        sa.Column('card_last_four', sa.String(4)),
        sa.Column('is_personal', sa.Boolean, server_default='false'),  # exclude from books
        sa.Column('status', sa.Enum('pending', 'matched', 'posted', 'void', name='transaction_status', schema='shared'), 
                  nullable=False, server_default='pending'),
        sa.Column('matched_receipt_id', postgresql.UUID(as_uuid=True)),
        sa.Column('matched_bill_id', postgresql.UUID(as_uuid=True)),
        sa.Column('posted_journal_entry_id', postgresql.UUID(as_uuid=True)),
        sa.Column('match_confidence', sa.Integer),  # 0-100
        sa.Column('manual_classification', sa.String(100)),  # Owner Draw, Due from Shareholder, etc.
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_index(f'idx_{schema_name}_bank_lines_date', 'bank_lines', ['transaction_date'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_bank_lines_status', 'bank_lines', ['status'], schema=schema_name)
    op.create_foreign_key(f'fk_{schema_name}_bank_lines_statement', 'bank_lines', 'bank_statements',
                          ['statement_id'], ['id'], source_schema=schema_name, referent_schema=schema_name,
                          ondelete='CASCADE')
    
    # Bills (Accounts Payable)
    op.create_table(
        'bills',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('bill_number', sa.String(50), unique=True),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('receipt_id', postgresql.UUID(as_uuid=True)),  # link to original receipt
        sa.Column('invoice_number', sa.String(100)),
        sa.Column('bill_date', sa.Date, nullable=False),
        sa.Column('due_date', sa.Date, nullable=False),
        sa.Column('total_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('amount_paid', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),  # open, paid, partial, cancelled
        sa.Column('autopay_expected_date', sa.Date),
        sa.Column('autopay_matched_bank_line_id', postgresql.UUID(as_uuid=True)),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_index(f'idx_{schema_name}_bills_vendor', 'bills', ['vendor_id'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_bills_due_date', 'bills', ['due_date'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_bills_status', 'bills', ['status'], schema=schema_name)
    
    # Journal Entries
    op.create_table(
        'journal_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('entry_number', sa.String(50), unique=True),
        sa.Column('entry_date', sa.Date, nullable=False),
        sa.Column('entry_type', sa.String(50), nullable=False),  # receipt, payment, adjustment, closing
        sa.Column('description', sa.Text),
        sa.Column('source_receipt_id', postgresql.UUID(as_uuid=True)),
        sa.Column('source_bank_line_id', postgresql.UUID(as_uuid=True)),
        sa.Column('source_bill_id', postgresql.UUID(as_uuid=True)),
        sa.Column('is_posted', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('posted_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('posted_by', sa.String(255)),
        sa.Column('is_void', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('void_reason', sa.Text),
        sa.Column('voided_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('voided_by', sa.String(255)),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_index(f'idx_{schema_name}_je_date', 'journal_entries', ['entry_date'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_je_posted', 'journal_entries', ['is_posted'], schema=schema_name)
    
    # Journal Entry Lines
    op.create_table(
        'journal_entry_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('journal_entry_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer, nullable=False),
        sa.Column('account_code', sa.String(20), nullable=False),
        sa.Column('debit', sa.Numeric(12, 2)),
        sa.Column('credit', sa.Numeric(12, 2)),
        sa.Column('description', sa.Text),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_index(f'idx_{schema_name}_je_lines_entry', 'journal_entry_lines', ['journal_entry_id'], schema=schema_name)
    op.create_foreign_key(f'fk_{schema_name}_je_lines_entry', 'journal_entry_lines', 'journal_entries',
                          ['journal_entry_id'], ['id'], source_schema=schema_name, referent_schema=schema_name,
                          ondelete='CASCADE')
    
    # Reimbursements (Corp only, but create in both for consistency)
    op.create_table(
        'reimbursements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('batch_number', sa.String(50), unique=True),
        sa.Column('batch_date', sa.Date, nullable=False),
        sa.Column('cardholder', sa.String(255), nullable=False),
        sa.Column('card_last_four', sa.String(4), nullable=False),
        sa.Column('total_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # pending, approved, paid
        sa.Column('approved_by', sa.String(255)),
        sa.Column('approved_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('paid_at', sa.Date),
        sa.Column('payment_method', sa.Enum('bill_pay_to_card', 'eft', 'etransfer', 'pad', 'cash', 'check', 
                                            name='payment_method', schema='shared')),
        sa.Column('payment_reference', sa.String(100)),
        sa.Column('receipt_ids', postgresql.ARRAY(postgresql.UUID), server_default='{}'),
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        schema=schema_name
    )
    op.create_index(f'idx_{schema_name}_reimb_batch_date', 'reimbursements', ['batch_date'], schema=schema_name)
    op.create_index(f'idx_{schema_name}_reimb_status', 'reimbursements', ['status'], schema=schema_name)


def upgrade():
    # Create tables for both entities
    create_entity_tables('curlys_corp')
    create_entity_tables('curlys_soleprop')
    
    # Enable audit triggers for key tables
    for schema in ['curlys_corp', 'curlys_soleprop']:
        for table in ['receipts', 'journal_entries', 'bills', 'reimbursements']:
            op.execute(f"""
                CREATE TRIGGER audit_{table}
                AFTER INSERT OR UPDATE OR DELETE ON {schema}.{table}
                FOR EACH ROW EXECUTE FUNCTION shared.log_audit_trail();
            """)
            
            op.execute(f"""
                CREATE TRIGGER update_{table}_updated_at
                BEFORE UPDATE ON {schema}.{table}
                FOR EACH ROW EXECUTE FUNCTION shared.update_updated_at();
            """)


def downgrade():
    # Drop all triggers first
    for schema in ['curlys_corp', 'curlys_soleprop']:
        for table in ['receipts', 'journal_entries', 'bills', 'reimbursements']:
            op.execute(f"DROP TRIGGER IF EXISTS audit_{table} ON {schema}.{table};")
            op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {schema}.{table};")
    
    # Drop all tables (foreign keys will cascade)
    for schema in ['curlys_corp', 'curlys_soleprop']:
        op.drop_table('reimbursements', schema=schema)
        op.drop_table('journal_entry_lines', schema=schema)
        op.drop_table('journal_entries', schema=schema)
        op.drop_table('bills', schema=schema)
        op.drop_table('bank_lines', schema=schema)
        op.drop_table('bank_statements', schema=schema)
        op.drop_table('receipt_lines', schema=schema)
        op.drop_table('receipts', schema=schema)
        op.drop_table('vendors', schema=schema)
        op.drop_table('chart_of_accounts', schema=schema)