-- Runtime recipient mapping. Populate privately; the public repo has no people.
create schema if not exists raw;

create table if not exists raw.handoff_owner_directory (
    owner_key text primary key,
    recipient_ref text not null
);
