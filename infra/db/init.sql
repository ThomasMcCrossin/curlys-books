-- Initialize Curly's Books Database
-- Creates separate schemas for Corp and Sole Prop entities
-- Run automatically by Docker on first start

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- For fuzzy string matching

-- Create schemas for multi-entity separation
CREATE SCHEMA IF NOT EXISTS curlys_corp;
CREATE SCHEMA IF NOT EXISTS curlys_soleprop;
CREATE SCHEMA IF NOT EXISTS shared;

-- Grant privileges
GRANT ALL PRIVILEGES ON SCHEMA curlys_corp TO curlys_admin;
GRANT ALL PRIVILEGES ON SCHEMA curlys_soleprop TO curlys_admin;
GRANT ALL PRIVILEGES ON SCHEMA shared TO curlys_admin;

-- Set default search path
ALTER DATABASE curlys_books SET search_path TO shared, curlys_corp, curlys_soleprop, public;

-- Create enum types in shared schema
CREATE TYPE shared.entity_type AS ENUM ('corp', 'soleprop');
CREATE TYPE shared.receipt_source AS ENUM ('pwa', 'email', 'drive', 'manual');
CREATE TYPE shared.transaction_status AS ENUM ('pending', 'matched', 'posted', 'void');
CREATE TYPE shared.payment_method AS ENUM ('bill_pay_to_card', 'eft', 'etransfer', 'pad', 'cash', 'check');
CREATE TYPE shared.confidence_level AS ENUM ('high', 'medium', 'low', 'failed');

-- Create audit trigger function
CREATE OR REPLACE FUNCTION shared.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create audit log function
CREATE OR REPLACE FUNCTION shared.log_audit_trail()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO shared.audit_log (
            table_name, record_id, action, new_data, changed_by, changed_at
        ) VALUES (
            TG_TABLE_NAME, NEW.id, 'INSERT', row_to_json(NEW), current_user, NOW()
        );
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO shared.audit_log (
            table_name, record_id, action, old_data, new_data, changed_by, changed_at
        ) VALUES (
            TG_TABLE_NAME, NEW.id, 'UPDATE', row_to_json(OLD), row_to_json(NEW), current_user, NOW()
        );
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO shared.audit_log (
            table_name, record_id, action, old_data, changed_by, changed_at
        ) VALUES (
            TG_TABLE_NAME, OLD.id, 'DELETE', row_to_json(OLD), current_user, NOW()
        );
        RETURN OLD;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create shared tables (used by both entities)
CREATE TABLE IF NOT EXISTS shared.audit_log (
    id BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    record_id UUID NOT NULL,
    action VARCHAR(10) NOT NULL,
    old_data JSONB,
    new_data JSONB,
    changed_by VARCHAR(100) NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_table_record ON shared.audit_log(table_name, record_id);
CREATE INDEX idx_audit_log_changed_at ON shared.audit_log(changed_at DESC);

-- Feature flags table
CREATE TABLE IF NOT EXISTS shared.feature_flags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    flag_key VARCHAR(100) UNIQUE NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT,
    config JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TRIGGER update_feature_flags_updated_at
    BEFORE UPDATE ON shared.feature_flags
    FOR EACH ROW
    EXECUTE FUNCTION shared.update_updated_at();

-- Insert default feature flags
INSERT INTO shared.feature_flags (flag_key, enabled, description) VALUES
    ('pad_matching_capital', true, 'Enable PAD autopay matching for Capital Foodservice'),
    ('pad_matching_gfs', true, 'Enable PAD autopay matching for GFS'),
    ('pad_matching_pepsi', true, 'Enable PAD autopay matching for Pepsi'),
    ('shopify_sync_canteen', true, 'Enable Shopify sync for curlyscanteen store'),
    ('shopify_sync_sports', true, 'Enable Shopify sync for curlys-sports-supplements store'),
    ('reimbursement_workflow_corp', true, 'Enable Monday reimbursement batches for Corp'),
    ('gpt_fallback_ocr', true, 'Enable GPT-4V fallback for low-confidence OCR'),
    ('item_catalog', false, 'Enable Item/VendorItem catalog (disabled by default)')
ON CONFLICT (flag_key) DO NOTHING;

-- Users/auth table (for Cloudflare Access integration)
CREATE TABLE IF NOT EXISTS shared.users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    roles TEXT[] NOT NULL DEFAULT '{}',
    last_login TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON shared.users
    FOR EACH ROW
    EXECUTE FUNCTION shared.update_updated_at();

-- Card registry (shared across entities for reimbursement tracking)
CREATE TABLE IF NOT EXISTS shared.card_registry (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_holder VARCHAR(255) NOT NULL, -- Primary account holder (who owns the account)
    cardholder_name VARCHAR(255) NOT NULL, -- Person who physically uses this card
    card_label VARCHAR(100) NOT NULL, -- e.g., "Dwayne Visa", "Thomas secondary"
    last_four CHAR(4) NOT NULL,
    card_type VARCHAR(50), -- mastercard, visa, debit_mc, amex
    account_last_four CHAR(4), -- Links cards on same account
    default_reimburse_entity shared.entity_type,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(cardholder_name, last_four)
);

CREATE TRIGGER update_card_registry_updated_at
    BEFORE UPDATE ON shared.card_registry
    FOR EACH ROW
    EXECUTE FUNCTION shared.update_updated_at();

-- Seed initial card registry
-- CIBC Visa Account (Dwayne's account, both cards appear on same statement)
INSERT INTO shared.card_registry (account_holder, cardholder_name, card_label, last_four, card_type, account_last_four, default_reimburse_entity, notes) VALUES
    ('Dwayne', 'Dwayne', 'Dwayne Visa Primary', '0318', 'visa', '0318', 'corp', 'Primary card on Dwayne CIBC Visa account'),
    ('Dwayne', 'Thomas', 'Thomas Visa Secondary', '4337', 'visa', '0318', 'corp', 'Secondary card on Dwayne CIBC Visa account')
ON CONFLICT (cardholder_name, last_four) DO NOTHING;

-- CIBC Mastercard Account (Dwayne's account, both cards appear on same statement)
INSERT INTO shared.card_registry (account_holder, cardholder_name, card_label, last_four, card_type, account_last_four, default_reimburse_entity, notes) VALUES
    ('Dwayne', 'Dwayne', 'Dwayne MC Primary', '7022', 'mastercard', '7022', 'corp', 'Primary card on Dwayne CIBC MC account'),
    ('Dwayne', 'Dwayne', 'Dwayne MC Secondary', '8154', 'mastercard', '7022', 'corp', 'Secondary card on Dwayne CIBC MC account')
ON CONFLICT (cardholder_name, last_four) DO NOTHING;

-- Personal cards (occasional business use)
INSERT INTO shared.card_registry (account_holder, cardholder_name, card_label, last_four, card_type, account_last_four, default_reimburse_entity, notes) VALUES
    ('Thomas', 'Thomas', 'Thomas Mosaik Debit', '7614', 'debit_mc', '7614', 'corp', 'Mosaik Credit Union debit MC, PDF statements only'),
    ('Thomas', 'Thomas', 'Thomas Scotiabank Visa', '7401', 'visa', '7401', 'corp', 'Scotiabank personal Visa, CSV statements')
ON CONFLICT (cardholder_name, last_four) DO NOTHING;

COMMENT ON DATABASE curlys_books IS 'Curly''s Books - Multi-entity accounting system for 14587430 Canada Inc. (Curly''s Canteen) and Sole Prop (Curly''s Sports & Supplements)';