-- Core dictionary with global words shared by all users
CREATE TABLE IF NOT EXISTS words (
    id SERIAL PRIMARY KEY,
    target_word TEXT NOT NULL UNIQUE,
    translate_word TEXT NOT NULL
);

-- Telegram users table
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,        -- telegram chat/user id
    username TEXT,
    first_seen_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- Link table mapping users to words in their personal set
CREATE TABLE IF NOT EXISTS user_words (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    username TEXT,
    word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    UNIQUE (user_id, word_id)
);

-- Helpful index for fast lookup by user
CREATE INDEX IF NOT EXISTS idx_user_words_user_id ON user_words(user_id);