-- PDF text extraction and OCR lineage. Additive only.
CREATE TABLE IF NOT EXISTS document_extractions(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 document_id text NOT NULL REFERENCES resa_documents(id), storage_object_id text NOT NULL REFERENCES storage_objects(id),
 source_checksum text NOT NULL, status text NOT NULL, extraction_method text,
 text_content text, text_hash text, page_count integer, extracted_pages integer NOT NULL DEFAULT 0,
 ocr_pages integer NOT NULL DEFAULT 0, char_count integer NOT NULL DEFAULT 0,
 quality_score double precision, ocr_language text, engine_version text NOT NULL,
 started_at timestamptz NOT NULL, completed_at timestamptz, error_code text, error_message text,
 UNIQUE(organization_id,document_id,source_checksum,engine_version));
CREATE TABLE IF NOT EXISTS document_page_extractions(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 extraction_id text NOT NULL REFERENCES document_extractions(id), document_id text NOT NULL REFERENCES resa_documents(id),
 page_number integer NOT NULL, extraction_method text NOT NULL, text_content text NOT NULL,
 char_count integer NOT NULL, confidence double precision, quality_score double precision,
 created_at timestamptz NOT NULL, UNIQUE(extraction_id,page_number));
CREATE INDEX IF NOT EXISTS document_extractions_document_idx ON document_extractions(organization_id,document_id,completed_at DESC);
CREATE INDEX IF NOT EXISTS document_pages_document_idx ON document_page_extractions(organization_id,document_id,page_number);
