-- Run once before enabling n8n/handoff_alerts.json. The workflow writes a row
-- only after Slack accepts a message; no restaurant/customer message is sent.
create schema if not exists raw;

create table if not exists raw.handoff_notification_log (
    notification_key text primary key,
    account_id uuid not null,
    owner_key text not null,
    slack_user_id text not null,
    slack_message_ts text not null,
    notified_at timestamptz not null default now()
);
