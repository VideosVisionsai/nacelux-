-- Official Eurostat NACE Rev. 2.1 model. Additive only; legacy nace_codes is preserved.
CREATE TABLE IF NOT EXISTS nace_versions_official(
 id text PRIMARY KEY, version_code text NOT NULL UNIQUE, title text NOT NULL,
 status text NOT NULL, valid_from date, source_url text NOT NULL, source_checksum text,
 source_format text NOT NULL, retrieved_at timestamptz, activated_at timestamptz,
 item_count integer NOT NULL DEFAULT 0, metadata jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS nace_items_official(
 id text PRIMARY KEY, version_id text NOT NULL REFERENCES nace_versions_official(id),
 code text NOT NULL, level text NOT NULL, parent_code text, concept_uri text NOT NULL,
 sort_order integer, is_current boolean NOT NULL DEFAULT true, source_url text NOT NULL,
 retrieved_at timestamptz NOT NULL, UNIQUE(version_id,code));
CREATE TABLE IF NOT EXISTS nace_labels_official(
 id text PRIMARY KEY, item_id text NOT NULL REFERENCES nace_items_official(id),
 language char(2) NOT NULL, label_type text NOT NULL, label text NOT NULL,
 source_url text NOT NULL, retrieved_at timestamptz NOT NULL,
 UNIQUE(item_id,language,label_type));
CREATE TABLE IF NOT EXISTS nace_notes_official(
 id text PRIMARY KEY, item_id text NOT NULL REFERENCES nace_items_official(id),
 note_type text NOT NULL, language char(2) NOT NULL, note_text text NOT NULL,
 note_uri text, source_url text NOT NULL, retrieved_at timestamptz NOT NULL,
 UNIQUE(item_id,note_type,language,note_text));
CREATE TABLE IF NOT EXISTS nace_correspondences_official(
 id text PRIMARY KEY, source_version text NOT NULL, target_version text NOT NULL,
 source_code text NOT NULL, target_code text NOT NULL, relationship text,
 mapping_uri text NOT NULL, source_url text NOT NULL, retrieved_at timestamptz NOT NULL,
 UNIQUE(source_version,target_version,source_code,target_code,mapping_uri));
CREATE TABLE IF NOT EXISTS nace_import_runs(
 id text PRIMARY KEY, version_code text NOT NULL, status text NOT NULL,
 source_url text NOT NULL, source_checksum text, started_at timestamptz NOT NULL,
 completed_at timestamptz, sections integer NOT NULL DEFAULT 0,
 divisions integer NOT NULL DEFAULT 0, groups_count integer NOT NULL DEFAULT 0,
 classes integer NOT NULL DEFAULT 0, labels integer NOT NULL DEFAULT 0,
 notes integer NOT NULL DEFAULT 0, correspondences integer NOT NULL DEFAULT 0,
 error_code text, error_message text, metadata jsonb NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS nace_items_level_code_idx ON nace_items_official(version_id,level,code);
CREATE INDEX IF NOT EXISTS nace_labels_lang_idx ON nace_labels_official(language,label);
CREATE INDEX IF NOT EXISTS nace_notes_item_idx ON nace_notes_official(item_id,note_type);
CREATE INDEX IF NOT EXISTS nace_corr_source_idx ON nace_correspondences_official(source_version,source_code);
CREATE INDEX IF NOT EXISTS nace_corr_target_idx ON nace_correspondences_official(target_version,target_code);
