-- Supabase Auth identity linkage. Additive only.
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_user_id text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS users_auth_user_id_uidx ON users(auth_user_id) WHERE auth_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS organization_members_user_idx ON organization_members(user_id);
CREATE INDEX IF NOT EXISTS organization_members_org_role_idx ON organization_members(organization_id,role);
