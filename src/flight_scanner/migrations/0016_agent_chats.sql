-- Watch assistant: one row per chat. `messages` is the Messages API history exactly as sent to
-- the model (owner messages, assistant turns with tool calls and thinking, tool results); it is
-- only ever appended to. Proposals are not stored: an accepted one becomes an ordinary Watch.
CREATE TABLE app.agent_chats (
    id bigserial PRIMARY KEY,
    messages jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
