CREATE TABLE IF NOT EXISTS user_words (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    username TEXT,
    target_word TEXT NOT NULL,
    translate_word TEXT NOT NULL,
    other_words TEXT[]
);