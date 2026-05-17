from alembic import op


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        CREATE TABLE admins (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE device_groups (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          name TEXT NOT NULL UNIQUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE devices (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          name TEXT NOT NULL,
          location TEXT NOT NULL,
          timezone TEXT NOT NULL DEFAULT 'UTC',
          group_id UUID REFERENCES device_groups(id) ON DELETE SET NULL,
          status TEXT NOT NULL,
          last_seen_at TIMESTAMPTZ,
          token_version INT NOT NULL DEFAULT 1,
          people_counting_enabled BOOLEAN NOT NULL DEFAULT FALSE,
          config_version INT NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE pairing_codes (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          code_hash TEXT NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL,
          used_at TIMESTAMPTZ,
          created_by_admin_id UUID REFERENCES admins(id) ON DELETE SET NULL,
          device_name TEXT NOT NULL,
          location TEXT NOT NULL,
          timezone TEXT NOT NULL DEFAULT 'UTC'
        );

        CREATE TABLE device_tokens (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL,
          issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          expires_at TIMESTAMPTZ NOT NULL,
          revoked_at TIMESTAMPTZ
        );

        CREATE TABLE assets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          filename TEXT NOT NULL,
          mime_type TEXT NOT NULL,
          sha256 TEXT NOT NULL UNIQUE,
          size_bytes BIGINT NOT NULL,
          storage_path TEXT NOT NULL UNIQUE,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE playlists (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          name TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE playlist_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          playlist_id UUID NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
          asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
          position INT NOT NULL,
          duration_sec INT NOT NULL,
          UNIQUE (playlist_id, position)
        );

        CREATE TABLE schedules (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          name TEXT NOT NULL,
          timezone TEXT NOT NULL DEFAULT 'UTC',
          priority INT NOT NULL DEFAULT 100,
          active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE schedule_rules (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          schedule_id UUID NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
          playlist_id UUID NOT NULL REFERENCES playlists(id) ON DELETE RESTRICT,
          days_of_week INT[] NOT NULL,
          start_time TIME NOT NULL,
          end_time TIME NOT NULL,
          priority INT NOT NULL DEFAULT 100,
          valid_from DATE,
          valid_to DATE
        );

        CREATE TABLE schedule_exceptions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          schedule_id UUID NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
          starts_at_utc TIMESTAMPTZ NOT NULL,
          ends_at_utc TIMESTAMPTZ NOT NULL,
          playlist_id UUID NOT NULL REFERENCES playlists(id) ON DELETE RESTRICT,
          priority INT NOT NULL DEFAULT 100
        );

        CREATE TABLE device_schedule_bindings (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          device_id UUID REFERENCES devices(id) ON DELETE CASCADE,
          group_id UUID REFERENCES device_groups(id) ON DELETE CASCADE,
          schedule_id UUID NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
          priority INT NOT NULL DEFAULT 100,
          CHECK ((device_id IS NOT NULL) <> (group_id IS NOT NULL))
        );

        CREATE TABLE impression_aggregates (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          minute_utc TIMESTAMPTZ NOT NULL,
          device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
          people_count INT NOT NULL DEFAULT 0,
          play_count INT NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (device_id, asset_id, minute_utc)
        );

        CREATE TABLE device_batches (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          batch_id TEXT NOT NULL,
          payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (device_id, batch_id)
        );

        CREATE TABLE audit_logs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          admin_id UUID REFERENCES admins(id) ON DELETE SET NULL,
          action TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          entity_id TEXT,
          meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX idx_devices_last_seen ON devices(last_seen_at);
        CREATE INDEX idx_impression_minute ON impression_aggregates(minute_utc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS audit_logs;
        DROP TABLE IF EXISTS device_batches;
        DROP TABLE IF EXISTS impression_aggregates;
        DROP TABLE IF EXISTS device_schedule_bindings;
        DROP TABLE IF EXISTS schedule_exceptions;
        DROP TABLE IF EXISTS schedule_rules;
        DROP TABLE IF EXISTS schedules;
        DROP TABLE IF EXISTS playlist_items;
        DROP TABLE IF EXISTS playlists;
        DROP TABLE IF EXISTS assets;
        DROP TABLE IF EXISTS device_tokens;
        DROP TABLE IF EXISTS pairing_codes;
        DROP TABLE IF EXISTS devices;
        DROP TABLE IF EXISTS device_groups;
        DROP TABLE IF EXISTS admins;
        """
    )
