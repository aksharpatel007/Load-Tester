-- Table for Users
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100),
    email VARCHAR(150) UNIQUE,
    password_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for Test History
CREATE TABLE test_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    url TEXT,
    total_requests INTEGER,
    success_percentage FLOAT,
    avg_response_time FLOAT,
    tested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for Comparisons
CREATE TABLE comparison_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    url_1 TEXT,
    url_2 TEXT,
    better_site TEXT,
    tested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);